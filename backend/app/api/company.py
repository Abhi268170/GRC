"""The company profile, and the lookups that help fill it in: find the company in the Swiss
commercial register, read its entry, and work out its industry (NOGA 2025).

The lookups are used at sign-up, so anyone can call them (the visitor has no account yet): every
one is limited per address, and the ones that can cost a model call are also limited in total.
When sign-up is closed they are only open to signed-in users (the company profile page)."""

from datetime import UTC, datetime

import ai_contracts as contracts
from ai_contracts import noga
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.schemas import CompanyDetails
from app.core import ratelimit
from app.core.auth import ControlDB, HomeDB, TenantAdmin, TenantMember, claims_of
from app.core.config import get_settings
from app.core.db import tenant_of
from app.models import Tenant
from app.models.tenancy import EMPLOYEE_RANGES
from app.services import ai, company_lookup
from app.services.company_lookup import CompanyHit, CompanyProfile

router = APIRouter(prefix="/company", tags=["company"])

REGISTER_DOWN = "Company search isn't available right now. You can enter your company by hand."


class SearchIn(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    canton: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")


class SearchOut(BaseModel):
    results: list[CompanyHit]
    too_many: bool = False   # the register refused: the name matches too many companies


class EnrichIn(BaseModel):
    uid: str = Field(min_length=9, max_length=20)
    # The name of the row that was picked: one company can be registered under several names.
    name: str | None = Field(default=None, max_length=200)


class ClassifyIn(BaseModel):
    description: str = Field(min_length=10, max_length=2000)
    company_name: str | None = Field(default=None, max_length=200)


async def _open(request: Request, *, costs_ai: bool) -> None:
    s = get_settings()
    if not s.signup_enabled and claims_of(request) is None:
        raise HTTPException(403, "Sign-up is closed at the moment.")
    ip = ratelimit.client_ip(request)
    if costs_ai:
        if await ratelimit.hit(f"company-ai-ip:{ip}", s.company_lookup_window_seconds) > s.company_ai_max_per_ip:
            raise ratelimit.too_many("Too many company lookups from this address. Try again later.")
        if await ratelimit.hit("company-ai-total", s.company_lookup_window_seconds) > s.company_ai_max_total:
            raise ratelimit.too_many("Company lookup is busy right now. You can enter your company by hand.")
    elif await ratelimit.hit(f"company-search-ip:{ip}", s.company_lookup_window_seconds) > s.company_search_max_per_ip:
        raise ratelimit.too_many("Too many searches from this address. Try again later.")


@router.post("/search", response_model=SearchOut)
async def search(body: SearchIn, request: Request) -> SearchOut:
    """Active companies in the commercial register whose name starts with the text, best match first."""
    await _open(request, costs_ai=False)
    try:
        return SearchOut(results=await company_lookup.search(body.name, body.canton))
    except company_lookup.TooManyResults:
        return SearchOut(results=[], too_many=True)
    except company_lookup.Unavailable:
        raise HTTPException(503, REGISTER_DOWN) from None


@router.post("/enrich", response_model=CompanyProfile)
async def enrich(body: EnrichIn, request: Request) -> CompanyProfile:
    """One company from the register, with its website and headcount where Wikidata has them, and
    its likely industries."""
    if company_lookup.normalize_uid(body.uid) is None:
        raise HTTPException(422, "That is not a company identification number (CHE-000.000.000)")
    await _open(request, costs_ai=True)
    try:
        profile = await company_lookup.enrich(body.uid, body.name)
    except company_lookup.Unavailable:
        raise HTTPException(503, REGISTER_DOWN) from None
    if profile is None:
        raise HTTPException(404, "No company with this number in the commercial register")
    return profile


@router.post("/classify", response_model=list[contracts.NogaCandidate])
async def classify(body: ClassifyIn, request: Request) -> list[contracts.NogaCandidate]:
    """Likely industries for a description of what a company does, best first."""
    await _open(request, costs_ai=True)
    try:
        return await company_lookup.classify(body.description, body.company_name)
    except ai.AIError:
        raise HTTPException(503, "We couldn't suggest an industry right now. Search for it instead.") from None


@router.get("/industries", response_model=list[contracts.NogaCandidate])
async def industries(request: Request, q: str = Query(min_length=2, max_length=100)) -> list[contracts.NogaCandidate]:
    """Search the industry list by words or by code, for choosing one by hand."""
    await _open(request, costs_ai=False)
    return company_lookup.search_industries(q)


# ---------- the company's own profile ----------

NOGA_KEYS = ("noga_code", "noga_label", "noga_section", "noga_section_label")
# Who confirmed the details and when. Kept across later saves: confirming is asked once.
VERIFIED_KEYS = ("verified_at", "verified_by", "verified_by_id")
# What must be filled in before the details can be confirmed, with the label shown to the user.
REQUIRED = {"description": "What the company does", "noga_code": "Industry", "street": "Street", "zip": "Postcode",
            "city": "City", "country": "Country"}


def industry_fields(code: str) -> tuple[str, dict]:
    """The industry title and the profile fields for a NOGA code. 422 if it isn't a six-digit code."""
    chosen = noga.candidate(code.strip())
    if chosen is None:
        raise HTTPException(422, "Unknown industry code")
    return chosen.label_en, {"noga_code": chosen.code, "noga_label": chosen.label_en, "noga_section": chosen.section,
                             "noga_section_label": chosen.section_label_en}


class ProfileOut(BaseModel):
    name: str
    industry: str | None                    # the title of the code, or free text from before codes were used
    noga: contracts.NogaCandidate | None
    employee_count: str | None
    details: CompanyDetails
    verified_at: datetime | None            # when a workspace admin confirmed the details; None = not yet
    verified_by: str | None
    missing: list[str]                      # labels of what still has to be filled in before confirming


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    employee_count: str
    noga_code: str | None = Field(default=None, max_length=6)   # left out: the industry stays as it is
    details: CompanyDetails = CompanyDetails()
    # True: the admin states the details are right and complete. Asked once, before the first assessment.
    confirm: bool = False


def _missing(stored: dict) -> list[str]:
    return [label for key, label in REQUIRED.items() if not stored.get(key)]


def _profile(tenant: Tenant) -> ProfileOut:
    stored = tenant.profile or {}
    details = CompanyDetails(**{k: v for k, v in stored.items() if k in CompanyDetails.model_fields})
    return ProfileOut(name=tenant.name, industry=tenant.industry, noga=noga.candidate(stored.get("noga_code") or ""),
                      employee_count=tenant.employee_count, details=details, verified_at=stored.get("verified_at"),
                      verified_by=stored.get("verified_by"), missing=_missing(stored))


@router.get("/profile", response_model=ProfileOut)
async def profile(user: TenantMember, db: HomeDB, control: ControlDB) -> ProfileOut:
    return _profile(await control.get(Tenant, tenant_of(db)))


@router.put("/profile", response_model=ProfileOut)
async def save_profile(body: ProfileIn, user: TenantAdmin, db: HomeDB, control: ControlDB) -> ProfileOut:
    """Replaces the company details with what the admin saved. With `confirm`, also records that the
    admin checked them; from then on the fields needed for that can't be emptied again."""
    if body.employee_count not in EMPLOYEE_RANGES:
        raise HTTPException(422, "Invalid employee count")
    tenant = await control.get(Tenant, tenant_of(db))
    stored = tenant.profile or {}
    kept = {k: stored[k] for k in (*NOGA_KEYS, *VERIFIED_KEYS) if k in stored}
    industry = tenant.industry
    if body.noga_code:
        industry, code_fields = industry_fields(body.noga_code)
        kept |= code_fields
    updated = kept | body.details.stored()
    if (body.confirm or tenant.profile_confirmed) and (missing := _missing(updated)):
        raise HTTPException(422, "Still needed: " + ", ".join(missing))
    if body.confirm:
        updated |= {"verified_at": datetime.now(UTC).isoformat(timespec="seconds"), "verified_by": user.full_name,
                    "verified_by_id": str(user.id)}
    tenant.name, tenant.employee_count, tenant.industry = " ".join(body.name.split()), body.employee_count, industry
    tenant.profile = updated  # a new dict, so the change is saved
    await control.commit()
    return _profile(tenant)
