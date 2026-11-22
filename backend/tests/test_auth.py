"""Sign-up, sign-in, sessions and who may call what. Uses the real databases."""

from contextlib import aclosing
import pytest
from sqlalchemy import select, text

from app.core import ratelimit
from app.core.config import get_settings
from app.core.db import ControlSession, session_for
from app.models import AppUser, LoginDirectory, Tenant
from app.services import snapshot, tenants
from tests.conftest import PASSWORD, new_client, signup, super_admin


async def test_health(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    ready = await client.get("/health/ready")
    assert ready.json()["checks"]["database"] == "ok" and ready.json()["checks"]["redis"] == "ok"
    assert (await client.get("/health/live")).headers["x-request-id"]


async def test_signup_creates_a_company_with_its_own_database(prepared):
    c, me = await signup("Northwind")
    async with aclosing(c):
        assert me["tenant"]["name"] == "Northwind" and me["user"]["platform_role"] == "tenant_admin"
        async with ControlSession() as control:
            tenant = await control.get(Tenant, me["tenant"]["id"])
            assert tenant.status == "active" and tenant.db_name.endswith(tenant.id.hex)
            assert (await control.get(LoginDirectory, me["email"])).tenant_id == tenant.id
            # the admin lives in the company database, not in the control database
            assert (await control.execute(select(AppUser).where(AppUser.email == me["email"]))).first() is None
        async with session_for(tenant.id) as db:
            assert (await db.execute(select(AppUser.email))).scalars().all() == [me["email"]]
            assert (await db.execute(text("select count(*) from master_data_item"))).scalar() > 0  # mirrored
        assert (await c.get("/auth/me")).json()["tenant"]["id"] == me["tenant"]["id"]


async def test_an_email_can_only_sign_up_once(prepared):
    c, me = await signup()
    async with aclosing(c), new_client() as other:
        r = await other.post("/auth/signup", json={"company_name": "Copy", "industry": "Other", "employee_count": "1-10",
                                                   "full_name": "X Y", "email": me["email"].upper(), "password": PASSWORD})
        assert r.status_code == 409


async def test_signup_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "signup_enabled", False)
    r = await client.post("/auth/signup", json={"company_name": "Late", "industry": "Other", "employee_count": "1-10",
                                                "full_name": "X Y", "email": "late@example.com", "password": PASSWORD})
    assert r.status_code == 403


async def test_a_failed_signup_leaves_nothing_behind(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(snapshot, "sync_master_data", boom)
    with pytest.raises(RuntimeError):
        await client.post("/auth/signup", json={"company_name": "Broken Co", "industry": "Other", "employee_count": "1-10",
                                                "full_name": "X Y", "email": "broken@example.com", "password": PASSWORD})
    async with ControlSession() as control:
        assert (await control.execute(select(Tenant).where(Tenant.name == "Broken Co"))).first() is None
        assert await control.get(LoginDirectory, "broken@example.com") is None
        leftovers = (await control.execute(text(
            "select count(*) from pg_database d where d.datname like '%\\_t\\_%' "
            "and not exists (select 1 from tenant t where t.db_name = d.datname)"))).scalar()
        assert leftovers == 0


async def test_login_wrong_password_then_lockout(prepared, monkeypatch):
    c, me = await signup()
    await c.aclose()
    monkeypatch.setattr(get_settings(), "login_max_failures_per_email", 3)
    async with new_client() as attacker:
        for _ in range(3):
            assert (await attacker.post("/auth/login", json={"email": me["email"], "password": "wrong"})).status_code == 401
        # locked now: even the right password is refused until the window passes
        assert (await attacker.post("/auth/login", json={"email": me["email"], "password": PASSWORD})).status_code == 429
        await ratelimit.clear(f"login-fail:{me['email']}")
        assert (await attacker.post("/auth/login", json={"email": me["email"], "password": PASSWORD})).status_code == 200
        unknown = await attacker.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
        assert unknown.status_code == 401 and unknown.json()["detail"] == "Incorrect email or password"


async def test_changing_the_password_ends_other_sessions(prepared):
    c, me = await signup()
    async with aclosing(c), new_client() as elsewhere:
        assert (await elsewhere.post("/auth/login", json={"email": me["email"], "password": PASSWORD})).status_code == 200
        same = await c.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": PASSWORD})
        assert same.status_code == 400
        changed = await c.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": PASSWORD + "-2"})
        assert changed.status_code == 204
        assert (await c.get("/auth/me")).status_code == 200          # this session got a new token
        assert (await elsewhere.get("/auth/me")).status_code == 401  # the other one is signed out


async def test_logout_revokes_the_token_itself(prepared):
    c, me = await signup()
    async with aclosing(c):
        token = c.cookies.get("grc_session")
        assert (await c.post("/auth/logout")).status_code == 204
        async with new_client() as thief:
            stolen = await thief.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert stolen.status_code == 401


async def test_team_management_and_temporary_passwords(prepared):
    c, me = await signup()
    async with aclosing(c), new_client() as member:
        created = (await c.post("/users", json={"email": "member-" + me["email"], "full_name": "Mia Member"})).json()
        login = await member.post("/auth/login", json={"email": created["user"]["email"], "password": created["temporary_password"]})
        assert login.status_code == 200 and login.json()["user"]["must_change_password"] is True
        assert (await member.get("/runs")).status_code == 403  # nothing but the password change is allowed
        await member.post("/auth/change-password", json={"current_password": created["temporary_password"], "new_password": PASSWORD})
        assert (await member.get("/runs")).status_code == 200
        assert (await member.post("/users", json={"email": "x@example.com", "full_name": "No Rights"})).status_code == 403
        # an admin reset signs the member out
        assert (await c.post(f"/users/{created['user']['id']}/reset-password")).status_code == 200
        assert (await member.get("/runs")).status_code == 401
        # the same email can't be used in another company
        other, _ = await signup("Other Co")
        async with aclosing(other):
            assert (await other.post("/users", json={"email": created["user"]["email"], "full_name": "Clash"})).status_code == 409
            assert [u["email"] for u in (await other.get("/users")).json()] != [u["email"] for u in (await c.get("/users")).json()]


async def test_roles_are_kept_apart(prepared):
    c, _ = await signup()
    admin = await super_admin()
    async with aclosing(c), aclosing(admin):
        for path in ("/library/controls", "/library/domains", "/frameworks", "/master-data?category=area", "/assessments"):
            assert (await c.get(path)).status_code == 403, path
            assert (await admin.get(path)).status_code == 200, path
        assert (await c.get("/master-data/organisational-roles")).status_code == 200      # the team page needs it
        assert (await c.get("/assessments/catalog/published")).status_code == 200
        for path in ("/runs", "/users", "/action-items", "/risks"):
            assert (await admin.get(path)).status_code == 403, path
    async with new_client() as anonymous:
        assert (await anonymous.get("/runs")).status_code == 401


async def test_oversized_requests_are_refused(client):
    huge = await client.post("/auth/login", content=b"x" * (get_settings().max_request_bytes + 1),
                             headers={"content-type": "application/json"})
    assert huge.status_code == 413


async def test_a_company_that_failed_to_migrate_is_offline_alone(prepared):
    c, me = await signup("Stuck Co")
    other, _ = await signup("Fine Co")
    async with aclosing(c), aclosing(other):
        async with ControlSession() as control:
            tenant = await control.get(Tenant, me["tenant"]["id"])
            tenant.status = "migration_failed"
            await control.commit()
        from app.core.db import forget_tenant

        await forget_tenant(tenant.id)  # as after a restart
        assert (await c.get("/runs")).status_code == 503
        assert (await other.get("/runs")).status_code == 200
        assert await tenants.migrate_all() == []  # the next deploy tries again and brings it back
        assert (await c.get("/runs")).status_code == 200
