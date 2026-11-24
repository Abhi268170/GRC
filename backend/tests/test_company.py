"""Company lookup at sign-up. The commercial register and Wikidata are replaced by a fake HTTP
transport, and the AI service by `fake_industry`: nothing outside the test stack is called."""

import uuid
from contextlib import aclosing

import httpx
import pytest
from ai_contracts import noga

from app.core import cache
from app.core.config import get_settings
from app.core.db import ControlSession
from app.models import Tenant
from app.services import ai, company_lookup
from tests.conftest import CONFIRMED_DETAILS, PASSWORD, new_client, signup

ACME = {
    "name": "Acme Messer AG", "uid": "CHE123456789", "legalSeat": "Schwyz", "status": "ACTIVE", "canton": "SZ",
    "legalForm": {"name": {"de": "Aktiengesellschaft", "en": "Corporation"}, "shortName": {"de": "AG", "en": "Ltd"}},
    "purpose": "Herstellung von und Handel mit Messerwaren.",
    "address": {"street": "Schmiedgasse", "houseNumber": "57", "swissZipCode": "6438", "city": "Ibach", "careOf": "", "poBox": ""},
}
CUTLERY = "256100"
# One company registered under two names: the same number, a seat and an address per name.
TWIN_AG = ACME | {"name": "Twin AG", "uid": "CHE222222222", "legalSeat": "Cham"}
TWIN_SA = TWIN_AG | {"name": "Twin SA", "legalSeat": "Vevey", "address": ACME["address"] | {"city": "Vevey", "swissZipCode": "1800"}}


class Outside:
    """Stands in for the register and Wikidata, and records what was asked."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.search_status = 200
        self.wikidata = [{"item": {"value": "http://www.wikidata.org/entity/Q1"}, "website": {"value": "https://acme.example"},
                          "employees": {"value": "640"}, "date": {"value": "2023-01-01T00:00:00Z"}},
                         {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "employees": {"value": "90"}}]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "query.wikidata.org":
            return httpx.Response(200, json={"results": {"bindings": self.wikidata}})
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path.endswith("/company/search"):
            if self.search_status == 400:
                return httpx.Response(400, json={"error": {"type": "RESULTLIST_TO_LARGE", "message": "too many results"}})
            if self.search_status != 200:
                return httpx.Response(self.search_status)
            if b'"Twin' in request.content:
                return httpx.Response(200, json=[TWIN_SA, TWIN_AG, TWIN_AG])
            others = [ACME | {"name": "Acme Messer Holding AG", "uid": "CHE999999999"}, ACME | {"name": "Acme AG", "uid": "CHE111111111"}]
            return httpx.Response(200, json=[*others, ACME])
        if request.url.path.endswith("/company/uid/CHE123456789"):
            return httpx.Response(200, json=[ACME])
        if request.url.path.endswith("/company/uid/CHE222222222"):
            return httpx.Response(200, json=[TWIN_AG, TWIN_SA])
        return httpx.Response(200, json=[])

    def count(self, part: str) -> int:
        return sum(part in str(r.url) for r in self.requests)


@pytest.fixture
async def outside(prepared, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "zefix_username", "user")
    monkeypatch.setattr(s, "zefix_password", "secret")
    monkeypatch.setattr(s, "signup_enabled", True)
    await cache._client().flushdb()  # also clears the rate limits
    fake = Outside()
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    monkeypatch.setattr(company_lookup, "http", lambda: client)
    yield fake
    await client.aclose()


@pytest.fixture
def fake_industry(monkeypatch) -> list:
    calls = []

    async def call(path, body, output, usage=None):
        calls.append((path, body, usage))
        return output(candidates=[noga.candidate(CUTLERY, "high"), noga.candidate("256300", "low")])

    monkeypatch.setattr(ai, "call", call)
    return calls


# ---------- plain functions ----------


def test_uid_formats():
    assert company_lookup.normalize_uid(" che-123.456.789 ") == "CHE123456789"
    assert company_lookup.normalize_uid("CHE123456789") == "CHE123456789"
    assert company_lookup.normalize_uid("CHE12345678") is None and company_lookup.normalize_uid("123456789") is None
    assert company_lookup.format_uid("CHE123456789") == "CHE-123.456.789"


@pytest.mark.parametrize(("headcount", "expected"), [(None, None), (0, None), (1, "1-10"), (10, "1-10"), (11, "11-50"),
                                                      (200, "51-200"), (201, "201-1000"), (1000, "201-1000"), (1001, "1000+")])
def test_headcount_to_employee_range(headcount, expected):
    assert company_lookup.employee_range(headcount) == expected


def test_wikidata_rows_give_the_newest_dated_headcount():
    facts = company_lookup._facts(Outside().wikidata)
    assert (facts.website, facts.employees, facts.employees_year) == ("https://acme.example", 640, 2023)


def test_wikidata_rows_about_two_items_are_ignored():
    rows = [{"item": {"value": "Q1"}, "website": {"value": "https://a.example"}}, {"item": {"value": "Q2"}}]
    assert company_lookup._facts(rows) is None and company_lookup._facts([]) is None


def test_wikidata_name_query_drops_the_legal_form_and_escapes_quotes():
    by_uid, by_name = company_lookup._wikidata_queries("CHE-123.456.789", 'Acme "Messer" AG')
    assert '"CHE-123.456.789"' in by_uid and '"CHE123456789"' in by_uid
    assert '"Acme \\"Messer\\""@de' in by_name and '"Acme \\"Messer\\" AG"@en' in by_name and "wd:Q39" in by_name


def test_the_industry_list_is_complete_and_searchable():
    assert len(noga.types()) == 798 and noga.candidate(CUTLERY).section == "C" and noga.candidate("25") is None
    assert [e.level for e in noga.path(CUTLERY)] == [1, 2, 3, 4, 5]
    found = company_lookup.search_industries("cutlery")
    assert found[0].code == CUTLERY and found[0].confidence is None
    assert company_lookup.search_industries("Schneidwaren")[0].code == CUTLERY       # German titles too
    assert all(c.code.startswith("2561") for c in company_lookup.search_industries("2561"))
    assert company_lookup.search_industries("zzzz") == [] and company_lookup.search_industries("  ") == []


# ---------- the endpoints ----------


async def test_search_ranks_the_closest_name_first_and_is_cached(client, outside):
    r = await client.post("/company/search", json={"name": "Acme Messer"})
    assert r.status_code == 200 and r.json()["too_many"] is False
    assert [h["name"] for h in r.json()["results"]] == ["Acme Messer AG", "Acme Messer Holding AG", "Acme AG"]
    assert r.json()["results"][0] == {"uid": "CHE-123.456.789", "name": "Acme Messer AG", "legal_seat": "Schwyz", "legal_form": "Corporation"}
    await client.post("/company/search", json={"name": "acme  messer"})
    assert outside.count("/company/search") == 1


async def test_search_reports_too_many_matches_and_an_unavailable_register(client, outside, monkeypatch):
    outside.search_status = 400
    assert (await client.post("/company/search", json={"name": "Sch"})).json() == {"results": [], "too_many": True}
    outside.search_status = 401
    r = await client.post("/company/search", json={"name": "Other"})
    assert r.status_code == 503 and "by hand" in r.json()["detail"]
    monkeypatch.setattr(get_settings(), "zefix_password", "")
    assert (await client.post("/company/search", json={"name": "Third"})).status_code == 503
    assert (await client.post("/company/search", json={"name": "ab"})).status_code == 422


async def test_enrich_merges_register_wikidata_and_industry(client, outside, fake_industry):
    r = await client.post("/company/enrich", json={"uid": "che123456789"})
    assert r.status_code == 200
    p = r.json()
    assert (p["uid"], p["name"], p["legal_form"], p["canton"]) == ("CHE-123.456.789", "Acme Messer AG", "Corporation", "SZ")
    assert p["address_line"] == "Schmiedgasse 57, 6438 Ibach" and p["website"] == "https://acme.example"
    assert (p["employees"], p["employees_year"], p["employee_range"]) == (640, 2023, "201-1000")
    assert [c["code"] for c in p["industries"]] == [CUTLERY, "256300"] and p["sources"] == ["zefix", "wikidata"]
    path, body, usage = fake_industry[0]
    assert path == "/noga/classify" and body.text == ACME["purpose"] and usage.feature == "company_industry" and usage.tenant_id is None
    # the second preview of the same company costs nothing
    await client.post("/company/enrich", json={"uid": "CHE-123.456.789"})
    assert len(fake_industry) == 1 and outside.count("/company/uid/") == 1 and outside.count("wikidata") == 1


async def test_a_company_registered_under_two_names_lists_each_once_and_fills_in_the_picked_one(client, outside, fake_industry):
    found = (await client.post("/company/search", json={"name": "Twin"})).json()["results"]
    assert [(h["uid"], h["name"], h["legal_seat"]) for h in found] == [
        ("CHE-222.222.222", "Twin AG", "Cham"), ("CHE-222.222.222", "Twin SA", "Vevey")]
    picked = (await client.post("/company/enrich", json={"uid": "CHE-222.222.222", "name": "twin  sa"})).json()
    assert (picked["name"], picked["legal_seat"], picked["address"]["city"]) == ("Twin SA", "Vevey", "Vevey")
    first = (await client.post("/company/enrich", json={"uid": "CHE-222.222.222"})).json()
    other = (await client.post("/company/enrich", json={"uid": "CHE-222.222.222", "name": "Not its name"})).json()
    assert first["name"] == other["name"] == "Twin AG" and first["address"]["city"] == "Ibach"
    assert outside.count("/company/uid/CHE222222222") == 1  # every name comes from one call to the register


async def test_enrich_works_without_wikidata_and_without_the_ai_service(client, outside, monkeypatch):
    outside.wikidata = []

    async def down(*args, **kwargs):
        raise ai.AIError("Could not reach the AI service")

    monkeypatch.setattr(ai, "call", down)
    p = (await client.post("/company/enrich", json={"uid": "CHE-123.456.789"})).json()
    assert p["name"] == "Acme Messer AG" and p["industries"] == [] and p["website"] is None and p["employee_range"] is None
    assert p["sources"] == ["zefix"]


async def test_enrich_rejects_unknown_and_malformed_numbers(client, outside, fake_industry):
    assert (await client.post("/company/enrich", json={"uid": "CHE-000.000.000"})).status_code == 404
    assert (await client.post("/company/enrich", json={"uid": "not-a-number"})).status_code == 422
    assert fake_industry == []


async def test_classify_a_description_and_search_the_list(client, outside, fake_industry):
    r = await client.post("/company/classify", json={"description": "We make pocket knives.", "company_name": "Acme"})
    assert r.status_code == 200 and r.json()[0]["code"] == CUTLERY and r.json()[0]["confidence"] == "high"
    assert (await client.post("/company/classify", json={"description": "short"})).status_code == 422
    found = await client.get("/company/industries", params={"q": "cutlery"})
    assert found.status_code == 200 and found.json()[0]["label_en"] == "Manufacture of cutlery"


async def test_lookups_are_limited_per_address_and_closed_with_signup(client, outside, fake_industry, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "company_ai_max_per_ip", 2)
    codes = [(await client.post("/company/classify", json={"description": f"We make pocket knives, batch {i}."})).status_code for i in range(3)]
    assert codes == [200, 200, 429]
    assert (await client.post("/company/enrich", json={"uid": "CHE-123.456.789"})).status_code == 429  # same budget
    assert (await client.post("/company/search", json={"name": "Acme"})).status_code == 200            # searching is separate
    monkeypatch.setattr(s, "signup_enabled", False)
    assert (await client.post("/company/search", json={"name": "Acme"})).status_code == 403
    assert (await client.get("/company/industries", params={"q": "cutlery"})).status_code == 403


# ---------- sign-up and the company profile ----------

DETAILS = {"registration_number": "CHE-123.456.789", "legal_form": "Corporation", "street": " Schmiedgasse ", "house_number": "57",
           "zip": "6438", "city": "Ibach", "region": "SZ", "country": "Switzerland", "website": "acme.example",
           "description": "Herstellung von\nMesserwaren."}


def _signup(**extra) -> dict:
    return {"company_name": "Acme Messer AG", "employee_count": "201-1000", "full_name": "Ada Acme",
            "email": f"ada-{uuid.uuid4().hex[:10]}@example.com", "password": PASSWORD} | extra


async def test_signup_saves_the_details_the_user_confirmed(prepared, outside, fake_industry):
    async with new_client() as c:
        r = await c.post("/auth/signup", json=_signup(noga_code=CUTLERY, details=DETAILS | {"house_number": "", "po_box": "ignored"}))
        assert r.status_code == 201, r.text
        tenant = r.json()["tenant"]
        assert tenant["industry"] == "Manufacture of cutlery" and tenant["employee_count"] == "201-1000"
        async with ControlSession() as control:
            profile = (await control.get(Tenant, tenant["id"])).profile
        assert profile == tenant["profile"] == {
            "registration_number": "CHE-123.456.789", "legal_form": "Corporation", "street": "Schmiedgasse", "zip": "6438",
            "city": "Ibach", "region": "SZ", "country": "Switzerland", "website": "https://acme.example",
            "description": "Herstellung von Messerwaren.", "noga_code": CUTLERY, "noga_label": "Manufacture of cutlery",
            "noga_section": "C", "noga_section_label": "Manufacturing"}
    # sign-up takes what the user confirmed: it calls neither the register nor the model
    assert fake_industry == [] and outside.requests == []


async def test_signup_checks_its_input(prepared, outside):
    async with new_client() as c:
        assert (await c.post("/auth/signup", json=_signup(noga_code="999999"))).status_code == 422   # not a code
        assert (await c.post("/auth/signup", json=_signup(noga_code="25"))).status_code == 422       # not six digits
        assert (await c.post("/auth/signup", json=_signup())).status_code == 422                      # no industry at all
        bad = await c.post("/auth/signup", json=_signup(noga_code=CUTLERY, details={"website": "not a site"}))
        assert bad.status_code == 422 and "web address" in bad.text
        assert (await c.post("/auth/signup", json=_signup(noga_code=CUTLERY, details={"city": "x" * 101}))).status_code == 422
        plain = await c.post("/auth/signup", json=_signup(noga_code=CUTLERY))                         # details are optional
        assert plain.status_code == 201 and set(plain.json()["tenant"]["profile"]) == {"noga_code", "noga_label", "noga_section", "noga_section_label"}
        legacy = await c.post("/auth/signup", json=_signup(industry="Other"))                         # free text still works
        assert legacy.status_code == 201 and legacy.json()["tenant"]["industry"] == "Other" and legacy.json()["tenant"]["profile"] == {}


async def test_company_profile_is_read_by_members_and_saved_by_admins(prepared, outside):
    async with new_client() as admin:
        me = (await admin.post("/auth/signup", json=_signup(industry="Other", company_name="Old Name Ltd"))).json()
        first = (await admin.get("/company/profile")).json()
        assert first == {"name": "Old Name Ltd", "industry": "Other", "noga": None, "employee_count": "201-1000",
                         "details": dict.fromkeys(DETAILS), "verified_at": None, "verified_by": None,
                         "missing": ["What the company does", "Industry", "Street", "Postcode", "City", "Country"]}

        # details without an industry code: the free-text industry stays
        r = await admin.put("/company/profile", json={"name": "  New  Name AG ", "employee_count": "51-200", "details": DETAILS})
        assert r.status_code == 200, r.text
        assert (r.json()["name"], r.json()["industry"], r.json()["noga"], r.json()["employee_count"]) == ("New Name AG", "Other", None, "51-200")
        assert r.json()["details"]["website"] == "https://acme.example" and r.json()["details"]["street"] == "Schmiedgasse"

        # with a code: the industry becomes its title; a field left empty is removed
        r = await admin.put("/company/profile", json={"name": "New Name AG", "employee_count": "51-200", "noga_code": CUTLERY,
                                                      "details": DETAILS | {"website": "", "region": None}})
        assert r.json()["industry"] == "Manufacture of cutlery" and r.json()["noga"]["code"] == CUTLERY
        assert r.json()["details"]["website"] is None and r.json()["details"]["region"] is None
        # saving again without a code keeps the code
        r = await admin.put("/company/profile", json={"name": "New Name AG", "employee_count": "51-200", "details": {"city": "Bern"}})
        assert r.json()["noga"]["code"] == CUTLERY and r.json()["details"]["city"] == "Bern" and r.json()["details"]["street"] is None
        async with ControlSession() as control:
            tenant = await control.get(Tenant, me["tenant"]["id"])
            assert tenant.name == "New Name AG" and tenant.profile["noga_code"] == CUTLERY and "street" not in tenant.profile
        assert (await admin.get("/auth/me")).json()["tenant"]["name"] == "New Name AG"

        bad = {"name": "New Name AG", "employee_count": "51-200", "details": {}}
        assert (await admin.put("/company/profile", json=bad | {"employee_count": "lots"})).status_code == 422
        assert (await admin.put("/company/profile", json=bad | {"noga_code": "000000"})).status_code == 422
        assert (await admin.put("/company/profile", json=bad | {"name": "x"})).status_code == 422
        assert (await admin.put("/company/profile", json=bad | {"details": {"website": "nope"}})).status_code == 422

        # a team member can read it but not change it
        created = await admin.post("/users", json={"email": f"member-{uuid.uuid4().hex[:8]}@example.com", "full_name": "Mia Member"})
        assert created.status_code == 201, created.text
        async with new_client() as member:
            login = await member.post("/auth/login", json={"email": created.json()["user"]["email"], "password": created.json()["temporary_password"]})
            assert login.status_code == 200
            changed = await member.post("/auth/change-password", json={"current_password": created.json()["temporary_password"],
                                                                       "new_password": PASSWORD + "-2"})
            assert changed.status_code == 204
            assert (await member.get("/company/profile")).json()["name"] == "New Name AG"
            assert (await member.put("/company/profile", json=bad)).status_code == 403
    async with new_client() as visitor:
        assert (await visitor.get("/company/profile")).status_code == 401


async def test_lookups_stay_open_to_signed_in_users_when_signup_is_closed(prepared, outside, monkeypatch):
    async with new_client() as admin:
        assert (await admin.post("/auth/signup", json=_signup(noga_code=CUTLERY))).status_code == 201
        monkeypatch.setattr(get_settings(), "signup_enabled", False)
        assert (await admin.post("/company/search", json={"name": "Acme"})).status_code == 200
    async with new_client() as visitor:
        assert (await visitor.post("/company/search", json={"name": "Acme"})).status_code == 403


async def test_details_must_be_confirmed_by_an_admin_before_the_first_assessment(prepared, outside, assessment, fake_ai):
    start = {"assessment_version_id": assessment["version_id"]}
    c, me = await signup("Unchecked Ltd", confirmed=False)
    async with aclosing(c):
        blocked = await c.post("/runs", json=start)
        assert blocked.status_code == 409 and "Confirm your company details" in blocked.json()["detail"]

        # a team member is told who has to do it
        created = (await c.post("/users", json={"email": f"member-{uuid.uuid4().hex[:8]}@example.com", "full_name": "Mia Member"})).json()
        async with new_client() as member:
            await member.post("/auth/login", json={"email": created["user"]["email"], "password": created["temporary_password"]})
            await member.post("/auth/change-password", json={"current_password": created["temporary_password"], "new_password": PASSWORD + "-2"})
            told = await member.post("/runs", json=start)
            assert told.status_code == 409 and "workspace admin needs to confirm" in told.json()["detail"]
            body = {"name": "Unchecked Ltd", "employee_count": "11-50", "noga_code": CUTLERY, "details": CONFIRMED_DETAILS, "confirm": True}
            assert (await member.put("/company/profile", json=body)).status_code == 403

            # saving is not confirming, and confirming needs the details to be complete
            saved = await c.put("/company/profile", json=body | {"confirm": False})
            assert saved.status_code == 200 and saved.json()["verified_at"] is None and saved.json()["missing"] == []
            assert (await c.post("/runs", json=start)).status_code == 409
            incomplete = await c.put("/company/profile", json=body | {"details": CONFIRMED_DETAILS | {"city": "", "zip": None}})
            assert incomplete.status_code == 422 and incomplete.json()["detail"] == "Still needed: Postcode, City"

            done = await c.put("/company/profile", json=body)
            assert done.status_code == 200 and done.json()["verified_by"] == "Ada Admin" and done.json()["verified_at"]
            assert (await c.get("/auth/me")).json()["tenant"]["profile"]["verified_at"]
            assert (await c.post("/runs", json=start)).status_code == 201
            assert (await member.post("/runs", json=start)).status_code == 201   # asked once, for everyone

        # later saves keep the confirmation, but can't empty what it was given for
        first = done.json()["verified_at"]
        later = await c.put("/company/profile", json={"name": "Unchecked Ltd", "employee_count": "51-200",
                                                      "details": CONFIRMED_DETAILS | {"website": "unchecked.example"}})
        assert later.status_code == 200 and later.json()["verified_at"] == first and later.json()["details"]["website"] == "https://unchecked.example"
        emptied = await c.put("/company/profile", json={"name": "Unchecked Ltd", "employee_count": "51-200", "details": {"city": "Bern"}})
        assert emptied.status_code == 422 and "Street" in emptied.json()["detail"]
