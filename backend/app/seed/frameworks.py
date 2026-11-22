"""Framework content: references and titles of every clause, loaded from frameworks.json.

Each clause is (ref, title, parent ref or None, is_assessable). Headings that only group
other clauses are not assessable.

Where the lists come from (fetched 2026-11-22):
- NIST-CSF 2.0: NIST CSF 2.0 Reference Tool export. 6 functions, 22 categories, 106 subcategories.
- GDPR: the Official Journal text of Regulation (EU) 2016/679. Chapters, sections, 99 articles.
- CH-FADP and CH-DPO: Fedlex English translations of SR 235.1 and SR 235.11, as in force on
  1 September 2023. Chapters, sections and articles.
- ISO-27001 2022: clause headings 4 to 10 from the standard's official preview (contents page);
  the 93 Annex A control titles as listed in the client's control workbook.
- ISO-27005 2022: clause headings 5 to 10 from the standard's official preview (contents page).

ISO/IEC texts are copyrighted: only clause numbers and headings are stored, never the text."""

import json
from pathlib import Path

FRAMEWORKS: list[dict] = json.loads(Path(__file__).with_name("frameworks.json").read_text(encoding="utf-8"))
