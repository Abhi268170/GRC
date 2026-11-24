"""NOGA 2025, the Swiss classification of economic activities.

Source: Federal Statistical Office, code list "NOGA 2025" (version 2.0.1) on the I14Y
interoperability platform. `data/noga2025.json` holds every code of the five levels with its
German and English title. The six-digit codes (level 5, "types") are the ones a company is
classified into; the levels above are used to show where a code sits.

    level 1  section   "C"       Manufacturing
    level 2  division  "25"
    level 3  group     "256"
    level 4  class     "2561"
    level 5  type      "256100"  Manufacture of cutlery

The English section titles are upper case in the source and were changed to sentence case.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from ai_contracts.tasks import NogaCandidate

DATA_FILE = Path(__file__).parent / "data" / "noga2025.json"
TYPE_LEVEL = 5


@dataclass(frozen=True)
class NogaEntry:
    code: str
    level: int
    parent: str | None
    en: str
    de: str


@lru_cache
def entries() -> dict[str, NogaEntry]:
    """Every code, in the order of the classification (parents before their children)."""
    rows = [NogaEntry(**row) for row in json.loads(DATA_FILE.read_text(encoding="utf-8"))]
    by_code = {r.code: r for r in rows}
    rows.sort(key=lambda e: _order_key(e, by_code))
    return {e.code: e for e in rows}


def _order_key(entry: NogaEntry, by_code: dict[str, NogaEntry]) -> tuple[str, str]:
    """Sections are letters and everything below is digits, so sort by (section, code)."""
    top = entry
    while top.parent:
        top = by_code[top.parent]
    return top.code, "" if entry.level == 1 else entry.code


def get(code: str) -> NogaEntry | None:
    return entries().get(code)


@lru_cache
def types() -> tuple[NogaEntry, ...]:
    """The six-digit codes a company can be classified into."""
    return tuple(e for e in entries().values() if e.level == TYPE_LEVEL)


def path(code: str) -> list[NogaEntry]:
    """The entry and everything above it, section first. Empty for an unknown code."""
    found, entry = [], get(code)
    while entry is not None:
        found.append(entry)
        entry = get(entry.parent) if entry.parent else None
    return found[::-1]


def section_of(code: str) -> NogaEntry | None:
    line = path(code)
    return line[0] if line else None


def division_of(code: str) -> NogaEntry | None:
    return next((e for e in path(code) if e.level == 2), None)


def candidate(code: str, confidence: Literal["high", "medium", "low"] | None = None) -> NogaCandidate | None:
    """A six-digit code with its section and division, as the API returns it. None if it isn't one."""
    entry = get(code)
    if entry is None or entry.level != TYPE_LEVEL:
        return None
    section, division = section_of(code), division_of(code)
    return NogaCandidate(
        code=entry.code, label_en=entry.en, label_de=entry.de,
        section=section.code, section_label_en=section.en, section_label_de=section.de,
        division=division.code, division_label_en=division.en, division_label_de=division.de,
        confidence=confidence)


__all__ = ["DATA_FILE", "TYPE_LEVEL", "NogaEntry", "candidate", "division_of", "entries", "get", "path", "section_of", "types"]
