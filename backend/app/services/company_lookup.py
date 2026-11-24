"""Company lookup for sign-up.

- The Swiss commercial register (Zefix, official API with credentials): search by name, and the
  entry of one company (legal form, seat, address, purpose).
- Wikidata: the website and the headcount, where it has them (mostly larger companies).
- The AI service: the industry as NOGA 2025 codes, from the purpose in the register or from a
  description typed by the visitor.

What is found is only a proposal: the browser shows it, the user changes what is wrong and saves
it (at sign-up, or on the company profile page). Everything that comes from outside is cached in
Redis, because the same company is often looked up more than once."""

import asyncio
import hashlib
import logging
import re
from typing import Any

import ai_contracts as contracts
import httpx
from ai_contracts import noga
from pydantic import BaseModel

from app.core import cache
from app.core.config import get_settings
from app.models.tenancy import EMPLOYEE_RANGES
from app.services import ai

log = logging.getLogger("company_lookup")

SEARCH_RESULTS = 20
SEARCH_TTL = 10 * 60
ENTRY_TTL = 24 * 3600
WIKIDATA_TTL = 24 * 3600
INDUSTRY_TTL = 7 * 24 * 3600
WIKIDATA_URL = "https://query.wikidata.org/sparql"
# Wikidata asks automated clients to identify themselves; nothing about the visitor is sent.
USER_AGENT = "TrustUpApp/1.0 (company profile lookup)"

_UID = re.compile(r"^CHE-?(\d{3})\.?(\d{3})\.?(\d{3})$", re.IGNORECASE)
# Legal form endings, so "Victorinox AG" is also found as "Victorinox".
_LEGAL_ENDING = re.compile(
    r"[,\s]+(AG|SA|GmbH|Sàrl|Sarl|S\.à r\.l\.|Sagl|S\.A\.|Ltd\.?|LLC|Inc\.?|KlG|KmG|Genossenschaft|Holding|"
    r"in Liquidation|en liquidation|in liquidazione)$", re.IGNORECASE)


class Unavailable(Exception):
    """The register can't be used right now (not configured, down, or it refused us)."""


class TooManyResults(Exception):
    """The register refuses searches that match too many companies."""


# ---------- what the API returns ----------


class CompanyHit(BaseModel):
    uid: str                 # "CHE-105.977.463"
    name: str
    legal_seat: str | None
    legal_form: str | None   # "Corporation"


class Address(BaseModel):
    street: str | None = None
    house_number: str | None = None
    zip: str | None = None
    city: str | None = None
    care_of: str | None = None
    po_box: str | None = None

    def line(self) -> str:
        street = " ".join(p for p in (self.street, self.house_number) if p)
        town = " ".join(p for p in (self.zip, self.city) if p)
        return ", ".join(p for p in (street, town) if p)


class RegisterEntry(BaseModel):
    uid: str
    name: str
    legal_form: str | None = None
    legal_form_short: str | None = None
    legal_seat: str | None = None
    canton: str | None = None
    purpose: str | None = None
    address: Address = Address()
    register_url: str | None = None


class WikidataFacts(BaseModel):
    website: str | None = None
    employees: int | None = None
    employees_year: int | None = None


class CompanyProfile(BaseModel):
    """One company from the register, with what Wikidata and the classification added."""

    uid: str
    name: str
    legal_form: str | None
    legal_seat: str | None
    canton: str | None
    purpose: str | None
    address: Address
    address_line: str
    website: str | None
    employees: int | None
    employees_year: int | None
    employee_range: str | None            # one of EMPLOYEE_RANGES, when a headcount is known
    industries: list[contracts.NogaCandidate]  # best first; empty when it could not be worked out
    sources: list[str]                    # "zefix", "wikidata"


# ---------- helpers ----------


def normalize_uid(value: str) -> str | None:
    """'CHE-105.977.463' or 'che105977463' -> 'CHE105977463'. None if it isn't a UID."""
    m = _UID.match(value.strip())
    return "CHE" + "".join(m.groups()) if m else None


def format_uid(uid: str) -> str:
    """'CHE105977463' -> 'CHE-105.977.463'."""
    return f"CHE-{uid[3:6]}.{uid[6:9]}.{uid[9:12]}"


def employee_range(headcount: int | None) -> str | None:
    if headcount is None or headcount < 1:
        return None
    for label, top in zip(EMPLOYEE_RANGES, (10, 50, 200, 1000), strict=False):
        if headcount <= top:
            return label
    return EMPLOYEE_RANGES[-1]


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


def _text(value: Any) -> str | None:
    """A register field as clean text: multilingual fields prefer English, then German."""
    if isinstance(value, dict):
        value = value.get("en") or value.get("de") or value.get("fr") or value.get("it")
    value = " ".join(str(value).split()) if value is not None else ""
    return value or None


_http: httpx.AsyncClient | None = None


def http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), headers={"User-Agent": USER_AGENT})
    return _http


async def close() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


# ---------- the commercial register ----------


def configured() -> bool:
    s = get_settings()
    return bool(s.zefix_username and s.zefix_password)


async def _zefix(method: str, path: str, body: dict | None = None) -> Any:
    s = get_settings()
    if not configured():
        raise Unavailable("the company register is not configured")
    try:
        response = await http().request(method, s.zefix_url.rstrip("/") + path, json=body,
                                        auth=(s.zefix_username, s.zefix_password), headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        log.warning("company register unreachable: %r", e)
        raise Unavailable("the company register could not be reached") from e
    if response.status_code == 400 and "RESULTLIST_TO_LARGE" in response.text:
        raise TooManyResults
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        # 401/403: the credentials are wrong or were withdrawn. Never log the body of the request.
        log.error("company register answered %s for %s", response.status_code, path)
        raise Unavailable(f"the company register answered {response.status_code}")
    return response.json()


def _hit(row: dict) -> CompanyHit | None:
    uid = normalize_uid(row.get("uid") or "")
    name = _text(row.get("name"))
    if not uid or not name:
        return None
    return CompanyHit(uid=format_uid(uid), name=name, legal_seat=_text(row.get("legalSeat")),
                      legal_form=_text((row.get("legalForm") or {}).get("name")))


def _rank(name: str, query: str) -> tuple[int, int, str]:
    """Exact name first, then names that start with the query, shortest first."""
    n, q = name.casefold(), query.casefold().strip()
    return (0 if n == q else 1 if n.startswith(q) else 2, len(n), n)


async def search(name: str, canton: str | None = None) -> list[CompanyHit]:
    """Active companies whose name starts with `name`. Raises TooManyResults or Unavailable."""
    query = " ".join(name.split())
    canton = canton.upper() if canton else None
    key = f"co-search:{_digest(query.casefold(), canton or '')}"
    cached = await cache.get_json(key)
    if cached is None:
        body: dict[str, Any] = {"name": query, "activeOnly": True}
        if canton:
            body["canton"] = canton
        rows = await _zefix("POST", "/company/search", body)
        hits = [h for h in (_hit(r) for r in rows if isinstance(r, dict)) if h is not None]
        hits.sort(key=lambda h: _rank(h.name, query))
        # One company can be registered under several names (same UID, one row per name): each
        # name stays in the list, but the same row is never listed twice.
        hits = list({(h.uid, h.name, h.legal_seat): h for h in reversed(hits)}.values())[::-1]
        cached = [h.model_dump() for h in hits[:SEARCH_RESULTS]]
        await cache.set_json(key, cached, SEARCH_TTL)
    return [CompanyHit(**h) for h in cached]


def _entry(uid: str, row: dict) -> RegisterEntry:
    a = row.get("address") or {}
    form = row.get("legalForm") or {}
    return RegisterEntry(
        uid=format_uid(uid), name=_text(row.get("name")), legal_form=_text(form.get("name")),
        legal_form_short=_text(form.get("shortName")), legal_seat=_text(row.get("legalSeat")),
        canton=_text(row.get("canton")), purpose=_text(row.get("purpose")),
        address=Address(street=_text(a.get("street")), house_number=_text(a.get("houseNumber")),
                        zip=_text(a.get("swissZipCode")), city=_text(a.get("city")),
                        care_of=_text(a.get("careOf")), po_box=_text(a.get("poBox"))),
        register_url=_text(row.get("zefixDetailWeb")))


async def register_entry(uid: str, name: str | None = None) -> RegisterEntry | None:
    """The register entry of one company. None if the UID is unknown. Raises Unavailable.

    A company registered under several names has one entry per name, each with its own seat and
    address: `name` picks the entry with that name; without it, or if none matches, the first."""
    uid = normalize_uid(uid) or ""
    if not uid:
        return None
    key = f"co-entries:{uid}"
    cached = await cache.get_json(key)
    if cached is None:
        rows = await _zefix("GET", f"/company/uid/{uid}")
        rows = [r for r in rows if isinstance(r, dict) and _text(r.get("name"))] if isinstance(rows, list) else []
        rows = [r for r in rows if r.get("status") == "ACTIVE"] or rows[:1]
        cached = [_entry(uid, r).model_dump() for r in rows]
        # "Unknown" is remembered for a short time only.
        await cache.set_json(key, cached, ENTRY_TTL if cached else SEARCH_TTL)
    entries = [RegisterEntry(**e) for e in cached]
    wanted = " ".join((name or "").split()).casefold()
    return next((e for e in entries if e.name.casefold() == wanted), entries[0] if entries else None)


# ---------- Wikidata ----------


def _literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _wikidata_queries(uid: str, name: str) -> list[str]:
    """First by the company's UID (exact). Then by its name, with and without the legal form, but only
    Swiss businesses: a company called "Davos AG" must not pick up the town."""
    facts = """OPTIONAL { ?item wdt:P856 ?website }
  OPTIONAL { ?item p:P1128 ?s . ?s ps:P1128 ?employees . OPTIONAL { ?s pq:P585 ?date } }"""
    plain = normalize_uid(uid) or ""
    by_uid = f"""SELECT ?item ?website ?employees ?date WHERE {{
  VALUES ?uid {{ {_literal(format_uid(plain))} {_literal(plain)} }}
  ?item wdt:P4829 ?uid .
  {facts} }} LIMIT 50"""
    names = {name, _LEGAL_ENDING.sub("", name).strip()} - {""}
    labels = " ".join(f"{_literal(n)}@{lang}" for n in sorted(names) for lang in ("de", "en", "fr", "it"))
    by_name = f"""SELECT ?item ?website ?employees ?date WHERE {{
  VALUES ?label {{ {labels} }}
  ?item rdfs:label ?label ; wdt:P17 wd:Q39 ; wdt:P31/wdt:P279* wd:Q4830453 .
  {facts} }} LIMIT 50"""
    return [by_uid, by_name]


def _facts(bindings: list[dict]) -> WikidataFacts | None:
    """Website and the most recent headcount, if the rows are about exactly one item."""
    items = {b["item"]["value"] for b in bindings if "item" in b}
    if len(items) != 1:
        return None  # nothing found, or the name is ambiguous
    website = next((b["website"]["value"] for b in bindings if "website" in b), None)
    if website and not website.lower().startswith(("http://", "https://")):
        website = None
    counts = []
    for b in bindings:
        try:
            n = int(float(b["employees"]["value"]))
        except (KeyError, ValueError):
            continue
        date = b.get("date", {}).get("value", "")
        counts.append((date[:4] if date[:4].isdigit() else "", n))
    employees = year = None
    if counts:
        latest = max(counts, key=lambda c: c[0])  # dated figures first, the newest of them
        employees, year = latest[1], int(latest[0]) if latest[0] else None
    return WikidataFacts(website=website[:500] if website else None, employees=employees, employees_year=year)


async def wikidata_facts(uid: str, name: str) -> WikidataFacts:
    """Never raises: Wikidata is a bonus, sign-up works without it."""
    if not get_settings().wikidata_enabled:
        return WikidataFacts()
    key = f"co-wikidata:{normalize_uid(uid)}"
    cached = await cache.get_json(key)
    if cached is not None:
        return WikidataFacts(**cached)
    facts = WikidataFacts()
    try:
        for query in _wikidata_queries(uid, name):
            response = await http().get(WIKIDATA_URL, params={"format": "json", "query": query})
            response.raise_for_status()
            found = _facts(response.json()["results"]["bindings"])
            if found is not None:
                facts = found
                break
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log.warning("Wikidata lookup failed: %r", e)
        return facts  # not cached: try again next time
    await cache.set_json(key, facts.model_dump(), WIKIDATA_TTL)
    return facts


# ---------- industry ----------


async def classify(text: str, company_name: str | None = None, limit: int = 5) -> list[contracts.NogaCandidate]:
    """NOGA 2025 codes for a description of what a company does, best first. Raises ai.AIError."""
    text = " ".join(text.split())
    key = f"co-industry:{_digest(text, company_name or '', str(limit))}"
    cached = await cache.get_json(key)
    if cached is None:
        ranking = await ai.call("/noga/classify", contracts.NogaClassifyIn(text=text, company_name=company_name, limit=limit),
                                contracts.NogaRanking, ai.UsageTag("company_industry"))
        cached = [c.model_dump() for c in ranking.candidates]
        await cache.set_json(key, cached, INDUSTRY_TTL)
    return [contracts.NogaCandidate(**c) for c in cached]


def search_industries(query: str, limit: int = 20) -> list[contracts.NogaCandidate]:
    """Six-digit codes whose title (English or German) contains every word of the query, or whose
    code starts with it. For picking an industry by hand."""
    words = [w for w in re.split(r"[^\w]+", query.casefold()) if w]
    if not words:
        return []
    found = []
    for entry in noga.types():
        en, de = entry.en.casefold(), entry.de.casefold()
        if len(words) == 1 and words[0].isdigit():
            if not entry.code.startswith(words[0]):
                continue
            score = 0
        elif all(w in en or w in de for w in words):
            # titles that start with the query, then titles where it starts a word, then the rest
            first = words[0]
            score = 0 if en.startswith(first) or de.startswith(first) else 1 if re.search(rf"\b{re.escape(first)}", en + " " + de) else 2
        else:
            continue
        found.append((score, len(entry.en), entry.code))
    return [c for c in (noga.candidate(code) for _, _, code in sorted(found)[:limit]) if c is not None]


# ---------- one company, everything together ----------


async def enrich(uid: str, name: str | None = None) -> CompanyProfile | None:
    """The register entry plus website, headcount and industry. None if the UID is unknown.
    `name` is the registered name that was picked, for a company that has more than one.
    Raises Unavailable only when the register itself can't be used."""
    entry = await register_entry(uid, name)
    if entry is None:
        return None

    async def industries() -> list[contracts.NogaCandidate]:
        if not entry.purpose:
            return []
        try:
            return await classify(entry.purpose, entry.name)
        except ai.AIError as e:  # the visitor can still pick an industry by hand
            log.warning("industry classification failed: %s", e)
            return []

    facts, ranked = await asyncio.gather(wikidata_facts(entry.uid, entry.name), industries())
    found = facts.website is not None or facts.employees is not None
    return CompanyProfile(
        uid=entry.uid, name=entry.name, legal_form=entry.legal_form, legal_seat=entry.legal_seat, canton=entry.canton,
        purpose=entry.purpose, address=entry.address, address_line=entry.address.line(),
        website=facts.website, employees=facts.employees, employees_year=facts.employees_year,
        employee_range=employee_range(facts.employees), industries=ranked,
        sources=["zefix", "wikidata"] if found else ["zefix"])

