"""Shared fixtures. Tests that need the database use `client` (or `prepared`); the rest are plain unit tests.

The test stack (docker-compose.test.yml) provides a throwaway Postgres and Redis. The control
database is rebuilt once per run, through the real migrations and the real seed. The AI service
is never called: `fake_ai` replaces the client functions with canned answers."""

import uuid
from datetime import UTC, datetime

import ai_contracts as contracts
import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import ratelimit
from app.core.config import get_settings
from app.core.db import ControlSession, dispose_all, url_for_database
from app.main import app
from app.models import (
    Assessment,
    AssessmentVersion,
    AssessmentVersionControl,
    AssessmentVersionDomain,
    Control,
    ControlVersion,
    Domain,
    DomainVersion,
    Question,
    QuestionRequirement,
    Requirement,
    RequirementVersion,
)
from app.services import ai, tenants

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session")
async def prepared():
    """A fresh control database: dropped, created, migrated and seeded once per test run."""
    settings = get_settings()
    # Limits that would get in the way of tests that sign up and sign in many times.
    settings.signup_max_per_ip, settings.signup_max_total, settings.login_max_attempts_per_ip = 10_000, 10_000, 10_000
    admin = create_async_engine(url_for_database("postgres"), isolation_level="AUTOCOMMIT")
    control_db = get_settings().database_url.rsplit("/", 1)[-1]
    async with admin.connect() as conn:
        stale = (await conn.execute(text("SELECT datname FROM pg_database WHERE datname = :n OR datname LIKE :p"),
                                    {"n": control_db, "p": control_db + "\\_t\\_%"})).scalars().all()
        for database in stale:
            await conn.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{control_db}"'))
    await admin.dispose()
    await ratelimit._client().flushdb()

    assert await tenants.migrate_all() == []
    from app.seed.__main__ import seed_domains, seed_frameworks, seed_master_data, seed_organisational_roles, seed_super_admin

    async with ControlSession() as db, db.begin():
        await seed_master_data(db)
        admin_id = await seed_super_admin(db)
        await seed_organisational_roles(db)
        await seed_frameworks(db, admin_id)
        await seed_domains(db, admin_id)
    yield
    await ratelimit.close()
    await dispose_all()


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client(prepared):
    async with new_client() as c:
        yield c


CONFIRMED_DETAILS = {"description": "Builds accounting software.", "street": "Main Street", "house_number": "1", "zip": "8000",
                     "city": "Zurich", "country": "Switzerland"}


async def signup(company: str = "Acme", confirmed: bool = True) -> tuple[httpx.AsyncClient, dict]:
    """A new company with its admin signed in. The caller closes the client.
    confirmed: the admin has confirmed the company details, so assessments can be started."""
    c = new_client()
    email = f"admin-{uuid.uuid4().hex[:10]}@example.com"
    r = await c.post("/auth/signup", json={"company_name": company, "industry": "Software / SaaS", "employee_count": "11-50",
                                           "full_name": "Ada Admin", "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    if confirmed:
        done = await c.put("/company/profile", json={"name": company, "employee_count": "11-50", "noga_code": "582900",
                                                     "details": CONFIRMED_DETAILS, "confirm": True})
        assert done.status_code == 200, done.text
    return c, r.json() | {"email": email}


async def super_admin() -> httpx.AsyncClient:
    c = new_client()
    s = get_settings()
    r = await c.post("/auth/login", json={"email": s.super_admin_email, "password": s.super_admin_password})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture(scope="session")
async def assessment(prepared) -> dict:
    """One published assessment in the control database: one control, two requirements, one question."""
    now = datetime.now(UTC)
    async with ControlSession() as db:
        domain = (await db.execute(select(Domain).where(Domain.abbreviation == "IAM"))).scalar_one()
        domain_version = (await db.execute(select(DomainVersion).where(DomainVersion.domain_id == domain.id))).scalar_one()
        control = Control(code="IAM01")
        db.add(control)
        await db.flush()
        cv = ControlVersion(control_id=control.id, domain_id=domain.id, version=1, status="published", published_at=now,
                            title="Manage access rights", key_requirement="Access is managed.")
        db.add(cv)
        await db.flush()
        req_versions = []
        for n, statement in enumerate(("Access is reviewed twice a year.", "Admin accounts are approved."), start=1):
            req = Requirement(control_id=control.id, code=f"IAM01-R0{n}")
            db.add(req)
            await db.flush()
            rv = RequirementVersion(requirement_id=req.id, control_version_id=cv.id, statement=statement,
                                    guidance="Keep a record.", sort_order=n,
                                    action_templates=[{"title": "Start doing it", "description": "Set it up."}] if n == 1 else [],
                                    risk_templates=[])
            db.add(rv)
            req_versions.append(rv)
        a = Assessment(code="BASE")
        db.add(a)
        await db.flush()
        av = AssessmentVersion(assessment_id=a.id, version=1, status="published", published_at=now, title="Baseline", description="Test")
        db.add(av)
        await db.flush()
        avd = AssessmentVersionDomain(assessment_version_id=av.id, domain_version_id=domain_version.id, sort_order=0)
        db.add(avd)
        await db.flush()
        db.add(AssessmentVersionControl(assessment_version_id=av.id, control_version_id=cv.id,
                                        assessment_version_domain_id=avd.id, sort_order=0))
        question = Question(assessment_version_id=av.id, assessment_version_domain_id=avd.id, text="How do you manage access?",
                            help_text="- Access", sort_order=0, origin="manual")
        db.add(question)
        await db.flush()
        for rv in req_versions:
            db.add(QuestionRequirement(question_id=question.id, requirement_version_id=rv.id, source="manual"))
        await db.commit()
        return {"version_id": str(av.id), "assessment_id": str(a.id), "requirement_ids": [str(rv.id) for rv in req_versions]}


class FakeAI:
    """Stands in for the AI service. Answers by path; records what it was asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.steps: list[list] = []  # each entry: the events of one guide step
        self.usage = contracts.Usage(model="fake", input_tokens=10, output_tokens=5, cost_usd=0.01)

    async def call(self, path, body, output, usage=None):
        self.calls.append((path, body))
        await ai.record_usage(usage, self.usage)
        if path == "/intake/questions":
            return output(questions=[contracts.IntakeQuestion(id="i1", text="Where is it hosted?", hint=None, options=[])])
        if path == "/evidence/digest":
            return output(summary="An access review record.", extracted_text=None)
        if path == "/cross-analysis":
            return output(ratings=[])
        if path == "/results/narrative":
            return output(executive_summary="Fine.", overall_explanation="Average of the ratings.", domains=[],
                          adapted_actions=[], adapted_risks=[], action_items=[], risks=[])
        raise AssertionError(f"unexpected AI call {path}")

    async def guide_system(self, body):
        return "system prompt"

    async def guide_step(self, body, usage=None):
        self.calls.append(("/guide/step", body))
        for event in self.steps.pop(0):
            if isinstance(event, contracts.FinalEvent):
                await ai.record_usage(usage, event.usage)
            yield event

    def final(self, tool_calls=(), text=("Thanks.",), stop_reason=None) -> contracts.FinalEvent:
        calls = [contracts.ToolCall(id=f"tool-{i}", name=name, input=args) for i, (name, args) in enumerate(tool_calls)]
        return contracts.FinalEvent(messages=[{"role": "user", "content": []}, {"role": "assistant", "content": []}],
                                    text=list(text), stop_reason=stop_reason or ("tool_use" if calls else "end_turn"),
                                    tool_calls=calls, usage=self.usage)


@pytest.fixture
def fake_ai(monkeypatch) -> FakeAI:
    fake = FakeAI()
    monkeypatch.setattr(ai, "call", fake.call)
    monkeypatch.setattr(ai, "guide_system", fake.guide_system)
    monkeypatch.setattr(ai, "guide_step", fake.guide_step)
    return fake


@pytest.fixture
def storage(monkeypatch) -> dict:
    """An in-memory object store in place of S3."""
    from app.api.runs import evidence as runs_api

    objects: dict[str, bytes] = {}
    monkeypatch.setattr(runs_api, "put_object", lambda key, data, ctype: objects.__setitem__(key, data))
    monkeypatch.setattr(runs_api, "get_object", lambda key: objects[key])
    return objects
