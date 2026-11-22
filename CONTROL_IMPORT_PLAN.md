# Control Import & Export: Plan

Status: built (backend, frontend, tests). This file is the design record.

## 1. Decisions so far

| # | Decision |
|---|---|
| 1 | **Fixed Excel template, no AI.** The template is a downloadable `.xlsx`. Exporting the library produces the same file, so the loop is: export, edit, import again. |
| 2 | **Re-import creates drafts.** A changed control gets a new draft version (IAM02.0002), and an unchanged one is skipped. If the control already has a draft, the preview asks: overwrite that draft or skip the control. Publishing is a separate step: per control, or "Publish all from this import". |
| 3 | **Unknown references block the import.** A missing domain, master data value, organisational role or framework clause is an error. The error says what was given, suggests the closest match ("did you mean …"), and asks you to fix the file or add the value in master data, then import again. The import never creates master data, roles or domains. |
| 4 | **All or nothing.** A preview validates the whole file first. Import is enabled only when there are zero errors (warnings are allowed). It is applied in a single transaction. |
| 5 | **Controls not in the file are untouched.** An import never deletes or deprecates anything. |
| 6 | **Draft assessments get an "update available" notice.** After imported drafts are published, a draft assessment that still points to older control versions shows the notice with a "Use latest versions" action. Links are never swapped silently. |
| 7 | **Removing a requirement needs an explicit tick.** A requirement missing from the file is listed in the preview, and the import stays disabled until each removal is ticked (or the file is fixed). |
| 8 | **The export holds only what can be imported.** No changelog or history sheet. |

## 2. File format

One workbook. A hidden `_meta` sheet holds the format version (`trustup-controls/1`), the export time and who exported it.

**Sheet `Instructions`:** how to fill the file in, the rules and an example row. Read only.

**Sheet `Controls`:** one row per control.

| Column | Notes |
|---|---|
| Control code | Blank = new control. Existing code (IAM02) = update that control. |
| Import key | Needed only for new controls (any short text, e.g. `N1`) so the Requirements sheet can point at them. |
| Base version | Filled in by export (IAM02.0003) and used to detect stale files (§5). Leave it as is. |
| Domain | Abbreviation (IAM). Dropdown. |
| Title | Required. |
| Area, Company risk exposure | One value each. Dropdown of master data labels. |
| Responsible role | Organisational role abbreviation or name. Dropdown. |
| Control types, Protection domains, Security capabilities, Protection objectives, Use cases | Several values, separated by `;`. Matched by label or code, case-insensitive. |
| Short description … Subject-specific support | The 8 text fields. |

**Sheet `Requirements`:** one row per requirement. The row order within a control becomes the requirement order.

| Column | Notes |
|---|---|
| Control | Control code or import key. |
| Requirement code | Blank = new requirement. Existing code (IAM02-R03) = the same requirement, so its history is kept. |
| Import key | Only for a new requirement that has templates (any short text, e.g. R1), so the Templates sheet can point to it. |
| Statement, Guidance | Required. |
| Mandatory | `Yes` / `No` / blank. |
| Evidence | One line per item, written as line breaks inside the cell. |
| Framework clauses | `FRAMEWORK:ref` separated by `;`, e.g. `ISO27001:A.5.15; SOC2:CC6.1`. Resolved against the framework's **published** version. |

**Sheet `Templates`:** one row per action or risk template.

| Column | Notes |
|---|---|
| Requirement | Requirement code, or the new requirement's import key. |
| Kind | `Action` / `Risk`. |
| Title, Description | Both required. |

**Hidden list sheets** feed the dropdowns: domains, every master data category, roles, frameworks and their clauses. They are regenerated on every template download or export, so they always match the current master data.

Why a separate Templates sheet: a requirement can have any number of templates, and fixed "Action 1 / Action 2" column pairs would either limit that or leave the sheet half empty.

## 3. Export

- Covers all domains, or a domain filter from the library page.
- Exports the **published** version of each control. An option includes drafts instead; their Base version is then the draft's code.
- **Round-trip guarantee:** importing an unedited export reports 0 changes. This is the main automated test.

## 4. Import flow

1. **Upload:** on `/admin/library/import`. Max 10 MB and 1,000 controls. The file is stored in rustfs.
2. **Preview** (`POST /library/imports`): parse, validate and diff, without writing anything to the library. The result is saved as an import batch with status `preview`.
3. **Review screen:**
   - **Counts:** new / changed / unchanged / conflicts / errors / warnings.
   - **Errors tab:** sheet, row, column, value, message and suggestion. "Download file with errors marked" returns the same workbook with the bad cells highlighted and the message as a cell comment.
   - **Changes:** each changed control expands to a field-by-field diff, including requirements added, removed, reordered or edited, and clause links added or removed.
   - **Conflicts:** controls that already have a draft, each with an "Overwrite draft / Skip" choice.
4. **Apply** (`POST /library/imports/{id}/apply`): re-validates against the current state, then writes everything in one transaction.
5. **Result:** lists the drafts created, with links. "Publish all from this import" runs the normal publish checks per control and reports the ones that can't be published yet and why.

## 5. Matching and change rules

| Situation | Outcome |
|---|---|
| Blank control code | New control. Its code is assigned on apply, in file order, using the existing per-domain lock. The preview shows the codes it expects to assign. |
| Code exists, content identical to the published version | Unchanged, skipped. |
| Code exists, content differs | A new draft version with the file's content. |
| Code exists and already has a draft | Conflict: overwrite or skip. Overwriting replaces the draft completely. |
| Base version older than the current published version | **Error (stale file).** Someone published since the export. Re-export and re-apply your edits. |
| Code doesn't exist | Error. Codes are assigned by the app and can't be chosen. Clear the cell to create a new control. |
| Domain differs on a control that has been published | Error: the domain is locked (decision 32). |
| Domain differs on a never-published draft | Allowed. The control is recoded, as in the editor. |
| An existing requirement is missing from the file | It is removed from the new version, but only once you tick the removal in the preview (decision 7). Until then, apply is disabled. Old versions keep it. |
| A requirement code belongs to another control | Error. |
| More than 99 controls in a domain | Error. |

"Content" means every versioned field (SCHEMA §2: control_version and its requirement versions and clause mappings). It is compared after the same cleanup the editor applies (trimmed text, blank evidence lines dropped).

## 6. Validation layers

Errors block the import; warnings don't.

1. **File:** it's an `.xlsx`; the sheets and headers are present; the format version is supported. A file that fails here stops at this stage with a single error.
2. **Cells:** required values are present, lengths are within the API limits (title ≤ 300, guidance 5–1000, …), Mandatory is Yes/No/blank, and templates have both a title and a description.
3. **References:**
   - domain, master data values (checked against the right category), roles and clauses must exist;
   - **an inactive master data value or role is an error** ("switched off");
   - a clause in a framework with no published version is an error;
   - suggestions come from a fuzzy match on label, code and abbreviation.
4. **Across rows:**
   - no duplicate control codes or import keys;
   - no requirements without a control, and no templates without a requirement;
   - 1–10 requirements per control;
   - a requirement code appears at most once.
5. **Library state:** stale base, existing drafts, domain lock, the 99-control limit.
6. **Publish readiness (warnings):** fields that `missing_for_publish` would flag. The draft is still created, but it won't publish until they are filled in. Also: the domain is unpublished, so the control can't be published yet.

The checks reuse the existing `ControlIn` / `RequirementIn` / `Template` models and `_apply_fields`, so the import can't accept something the editor would reject.

## 7. Effect on related modules

| Module | Effect | Plan |
|---|---|---|
| **Published assessments and runs** | None. They point to exact control and requirement versions, which never change. | None. |
| **Responses, evaluations, outputs** | None. They point to requirement versions. | None. |
| **Assessments using a control that gets a newer version** | After publishing, those assessments still use the old version. That is correct, but you can't see it. | The result screen lists "N assessments use an older version of these controls". Creating a new assessment draft picks up the latest versions (this already works). |
| **Draft assessments** | They point to the published control version, which becomes deprecated after publishing. | An "update available" notice on the draft with a "Use latest versions" action, which swaps the links and regenerates the questions for changed controls (decision 6). |
| **Framework coverage** | Changes when imported drafts are published (clause links added or removed). | The preview shows the clause changes per framework. |
| **Framework clause links on re-import** | Export writes `FRAMEWORK:ref`, and import resolves it against the **current** published framework version. If a new framework version has been published since, re-importing moves the links to it. | This shows in the diff as clauses removed and added. Refs that no longer exist in the new version are errors. |
| **Framework delete** | Imported links count toward `mapped_requirements`, so they block deleting the framework, as intended. | None. |
| **Master data and roles** | Read only. The import never creates or changes them. | The dropdown lists in the template come from the current values. |
| **AI** | Question writing and the guide use controls only when an assessment is built or rebuilt. | None. |
| **Concurrent edits** | Someone may edit or publish a control between preview and apply. | Apply re-checks a fingerprint per control (the published version id plus the draft's `updated_at`). On any mismatch, nothing is applied and you are asked to preview again. One import is applied at a time (an advisory lock). |

## 8. Data model

A new table, `control_import`:

| Column | Notes |
|---|---|
| id | |
| file_key | The upload in rustfs. |
| filename | |
| status | `preview` / `applied` / `expired` / `failed`. |
| created_by, created_at | |
| applied_at | |
| summary | JSONB: the counts. |
| report | JSONB: errors, warnings, diffs and the conflict choices. |
| fingerprints | JSONB: per control, used for the re-check on apply. |

A new column, `control_version.import_id`, is a nullable FK to `control_import`. It records which drafts an import created, for "Publish all from this import", "Discard drafts from this import" and history.

A preview expires after 24 hours or when a newer preview is made.

## 9. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/library/export?domain_id=&include_drafts=` | Download the `.xlsx`. |
| GET | `/library/import-template` | Download an empty template with current dropdowns. |
| POST | `/library/imports` | Upload and preview. Returns the batch with its report. |
| GET | `/library/imports` and `/library/imports/{id}` | History and detail. |
| PUT | `/library/imports/{id}/choices` | Overwrite/skip choices for conflicts, and the ticked requirement removals. |
| GET | `/library/imports/{id}/errors.xlsx` | The workbook with errors marked. |
| POST | `/library/imports/{id}/apply` | Apply. |
| POST | `/library/imports/{id}/publish` | Publish every publishable draft from the import. Returns the ones that couldn't be published, and why. |
| DELETE | `/library/imports/{id}/drafts` | Discard the drafts it created that are not yet published. |

All of these are for the super admin only. The preview runs inside the request (≤ 1,000 controls is fast), so no worker job is needed.

## 10. Frontend

- Library page header: an **Import** button and an **Export** menu (all domains, or the selected domain).
- `/admin/library/import`: a 3-step page (Upload → Review → Done), plus import history below.
  - Review uses the same accordion cards as the control editor for the diffs.
  - Errors are shown in a table, with the download button.
- Library list: a small "imported" badge on drafts from an import, with a filter to show them.

## 11. Build order

1. Workbook writer: the template plus export, with the hidden lists and dropdowns. Round-trip read.
2. Parser and validation layers 1–4, with the error workbook.
3. Diff engine, state checks (layer 5) and the publish-readiness warnings.
4. The `control_import` table and migration; preview, apply and publish endpoints; fingerprints and the lock.
5. Frontend: the import page, the export menu and the badges.
6. Docs: SCHEMA §4.4 and a decision row in PROJECT_IDEA.

## 12. Tests

- **Round trip:** export, then import → 0 changes. Export, edit one guidance, import → exactly 1 changed control and a 1-field diff.
- **Each error class:** a file with one of each produces the right sheet, row, column and suggestion.
- **Stale base, draft conflict (overwrite and skip), domain lock, and removed-requirement warning.**
- **New controls in two domains:** codes assigned in file order, no gaps or clashes, while a control is being created in the editor at the same time.
- **Concurrent edits:** a control edited between preview and apply → apply refuses, and nothing is written.
- **Publish all:** a mix of ready and not-ready drafts → the ready ones are published and the rest are listed with reasons.

## 13. Open questions

None. A, B and C were answered and are recorded as decisions 6, 7 and 8.
