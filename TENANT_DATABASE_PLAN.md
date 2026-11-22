# One Database per Company: Plan

Status: built and verified (2026-11-22). This file is the design record (decision 42). §15 lists where the build differs from the original plan.

## 1. Decisions

| # | Decision |
|---|---|
| 1 | **One Postgres database per company.** Requested by the client. Each tenant's data lives in its own database, so it can be backed up, restored, moved or dropped on its own. |
| 2 | **One control database.** It holds the tenant registry, the super admin, the library (frameworks, domains, controls, assessments), master data, control imports, platform jobs and a login directory. |
| 3 | **The assessment is copied into the company database when a run starts.** Published versions never change, so the copy is safe. Foreign keys and joins between run data and library data stay inside one database. |
| 4 | **All databases are on the same Postgres server for now.** The registry stores a database name, not connection details. |
| 5 | **`tenant_id` columns are dropped** from tenant tables. In a company database, every row belongs to that company. |

## 2. What lives where

| Control database (`grc`) | Company database (`grc_t_<tenant id hex>`) |
|---|---|
| `tenant` (registry: name, industry, employees, profile, `db_name`, `status`) | `app_user` (that company's users only) |
| `login_directory` (email → tenant id; empty tenant id = super admin) | `assessment_run`, `run_domain`, `run_question`, `response`, `evidence`, `response_evidence`, `requirement_evaluation`, `evaluation_citation`, `conversation`, `conversation_message` |
| `app_user` (super admin only) | `run_rollup`, `action_item`, `action_item_requirement`, `risk`, `risk_requirement`, `report`, `review_comment` |
| Library: `framework*`, `domain*`, `control*`, `requirement*`, `assessment*`, `question*`, `control_import` | `notification`, `job`, `ai_usage` (company work); an empty `control_import` |
| `master_data_item`, `organisational_role` | **Snapshot copy** of the library rows that runs use (§3) |
| `job`, `ai_usage` (platform work), `notification` (none today) | **Mirror** of `master_data_item` and `organisational_role` (§4) |

The same SQLAlchemy model classes are used in both databases. Two sets in `app/models/__init__.py` decide which tables each migration tree leaves out: `CONTROL_ONLY_TABLES` (`tenant`, `login_directory`) and `TENANT_ONLY_TABLES` (everything in `models/run.py` and `models/outputs.py`).

## 3. The assessment snapshot

When a run starts, the published assessment version and everything it points to are copied into the company database. Rows keep their original ids, so:
- the copy is idempotent (`INSERT … ON CONFLICT (id) DO NOTHING`);
- a second run on the same version reuses the copy;
- ids in run data still match the library.

**Tables copied, limited to rows reachable from the assessment version:**
- `assessment`, `assessment_version`, `assessment_version_domain`, `assessment_version_control`, `question`, `question_requirement`;
- `domain`, `domain_version`;
- `control`, `control_version`, `control_version_classification`, `requirement`, `requirement_version`, `requirement_clause_map`;
- `framework`, `framework_version`, `framework_clause` (the mapped clauses and their parent clauses).

**Columns cleared on copy:** audit columns that point at the super admin (`published_by`, `created_by` on library rows) and `control_version.import_id`. Their foreign keys still exist in the company database, but the values are always empty there.

**Version status:** only one published version per assessment, control, domain or framework is allowed. Before copying, older copies that the control database has since deprecated are marked deprecated in the company database too.

**Deprecation:** when version N+1 is published, a fan-out (§7) marks the copied version N as `deprecated` in each company database that has it and creates the existing "assessment deprecated" notification there.

## 4. Master data mirror

`app_user.organisational_role_id` and `control_version` classifications point at master data, which the super admin can edit. Every company database keeps a full mirror of `master_data_item` and `organisational_role`:
- it is copied when the company database is created;
- every super admin change to master data or roles is re-synced to all company databases by a background task (upsert by id; values are never deleted, only switched off);
- it is also refreshed when a run starts, when a user is saved with a role, and at startup after seeding.

## 5. Connections and requests

- **Config:** `DATABASE_URL` stays the control database. Company URLs are built from it by swapping the database name.
- **Engines:** `core/db.py` holds the control engine and a lazily created cache of company engines, keyed by tenant id, with small pools (pool size 2, overflow 3). Only active tenants are looked up.
- **Dependencies:**
  - `ControlDB` is a session on the control database. Every endpoint that reads the library, the catalog or master data uses it, including tenant users.
  - `TenantDB` is a session on the current user's company database.
- **Auth:**
  - Login looks the email up in `login_directory`, opens that company database (or the control database for the super admin) and checks the password there.
  - The session token keeps `tid`. `current_user` uses it to pick the database, then loads the user from that database.
  - Creating a user, changing an email or deleting a user writes the directory first, then the company database, and removes the directory row if the second write fails.
- **Access checks:** the `run.tenant_id != user.tenant_id` checks go away, because another company's rows aren't in the database at all. The `run.id` checks on child rows stay.

## 6. Setting up a company

`services/tenants.py` `provision_tenant()`, used by signup:
1. Insert the `tenant` row with `status = 'provisioning'` and the `login_directory` row for the admin (this reserves the email).
2. Run `CREATE DATABASE grc_t_<hex>` in autocommit mode.
3. Run the company migrations on it.
4. Copy the master data mirror and create the tenant admin.
5. Set `status = 'active'`.

If any step fails, it drops the database and deletes the registry and directory rows, and signup returns an error. Login refuses tenants that aren't `active`.

Deleting a company, which isn't a feature yet, would be `DROP DATABASE` plus removing the registry and directory rows.

## 7. Work that spans companies

These loop over active tenants in the registry:
- the deprecation notices (§3);
- master data sync (§4);
- any super admin view of AI usage or tenant activity (rows are labelled with the tenant from the registry).

Each one runs as a background job on the control side, so a slow or failing company database doesn't block the super admin's request. Failures are logged per tenant and can be re-run.

## 8. Background jobs

- A job row lives in the database of whoever owns the work: the company database for run work, the control database for framework parsing and question generation.
- `enqueue()` takes the tenant id and passes it to arq together with the job id: `enqueue_job(type, job_id, tenant_id)`.
- The worker opens the right session from that tenant id. `GET /jobs/{id}` reads from the caller's database.

## 9. Migrations

- `backend/alembic/control/` is the existing history plus one migration that:
  - adds `tenant.db_name`, `tenant.status` and `login_directory`;
  - moves the existing data (§10);
  - drops the tenant tables from the control database.
- `backend/alembic/tenant/` is a new tree, starting from one initial migration that creates the company schema.
- `python -m app.tenants migrate` upgrades the control database, then every active company database, and reports any that fail. The backend container runs it on startup instead of `alembic upgrade head`.
- Every future model change needs a migration in the right tree. A change to a snapshot or mirror table needs one in both trees.

## 10. Moving the existing data

The control database has 2 tenants, 5 users (1 super admin) and no runs. The migration script will:
1. create a company database for each tenant;
2. move each tenant's users and notifications;
3. fill `login_directory`;
4. copy the master data mirror.

Tenant jobs and AI usage rows are discarded, because they only exist for runs that were already deleted.

## 11. Frontend

No changes expected: the API paths and responses stay the same. Signup can take a few seconds longer, so its button shows a "Setting up your workspace…" state.

## 12. Implementation order

1. **Config and engines:** the control engine, the company engine cache, the `ControlDB` and `TenantDB` dependencies.
2. **Models:** remove `TenantMixin` and `tenant_id`, then define the control and company table lists. Snapshot tables in the company database skip the foreign keys from §3.
3. **Migrations:** split Alembic into two trees, write the company initial migration and the control migration (registry columns, `login_directory`).
4. **Provisioning:** `provision_tenant()` and the `migrate` command. Signup uses them.
5. **Auth:** login through the directory, `current_user` choosing the database, keeping the directory in sync from user management.
6. **Snapshot copy and master data mirror:** the copy runs inside `start_run`.
7. **Rewire endpoints:** runs, registers, users, auth and platform move to `TenantDB`; library, frameworks, master data and the catalog move to `ControlDB`.
8. **Worker:** pass the tenant id through arq and pick the session from it.
9. **Fan-outs:** deprecation, master data sync and the super admin views.
10. **Data move:** the existing 2 tenants and their users, then drop the tenant tables from the control database.
11. **Docs:** `SCHEMA.md` conventions and diagrams, `PROJECT_IDEA.md`, `README.md`, session notes.
12. **Verify** (§13).

## 13. Verification

- `ruff check app`, `npx tsc --noEmit`, `npx eslint src`.
- Sign up two new companies:
  - each gets its own database (`\l` lists `grc_t_…`);
  - signing in works for both companies and for the super admin.
- Start a run in each company. The snapshot rows appear only in that company's database. Work through it: intake, answers, evidence, cross-analysis, outputs, report export.
- Using company A's session with company B's run id and evidence id returns 404.
- Publish a new assessment version. Company A's run shows the deprecation notice.
- Edit master data. The change appears in both company databases.
- Signup cleanup: force provisioning to fail and check that no database, registry row or directory row is left behind.
- Restart the worker and backend, then run `migrate` twice to check it does nothing the second time.

## 14. Risks and costs

- **Connections:** every company database has its own pool. With the default `max_connections = 100`, that is fine for tens of tenants, not hundreds. Past that, add PgBouncer.
- **Migrations:** they run per company, so a migration that fails halfway leaves companies on different versions until it is re-run.
- **No cross-database transactions:** the directory and company writes, and the fan-outs, are kept in step by write ordering and retries, not by one transaction.
- **Duplicated library rows:** each company database keeps copies of the assessments it has run. The copies are small text rows.

## 15. What the build does differently

| Plan | Built | Why |
|---|---|---|
| Super admin views across companies run as background jobs (§7). | The assessment list's run count reads every company database directly during the request. Deprecation notices and the master data sync are background tasks, as planned. | A count has to be in the response. A failing company database is logged and counted as 0. |
| `ai_usage.run_id` references `assessment_run`. | It is a plain id with an index, no foreign key. | The control database has `ai_usage` but no runs. Deleting a run no longer deletes its usage rows. |
| `control_import` isn't in company databases (§3). | The table exists there, empty. | `control_version.import_id` keeps its foreign key, so the models are identical in both databases. |
| The API responses stay the same (§11). | `user.tenant_id` is gone from the user object. The company is still in `GET /auth/me` as `tenant`. | The column no longer exists. The frontend never read it. |
| Signup can take a few seconds (§11). | It takes about half a second. The button still shows "Setting up your workspace…". | Creating a database and its tables is quick on the same server. |

## 16. Where the code is

| What | Where |
|---|---|
| Sessions, the engine cache, `tenant_of(session)` | `backend/app/core/db.py` |
| `ControlDB`, `TenantDB`, `HomeDB`, `CurrentUser` | `backend/app/core/auth.py` |
| Company setup and removal, migrations, work across companies | `backend/app/services/tenants.py` |
| Assessment copy, master data mirror, deprecation of a copy | `backend/app/services/snapshot.py` |
| `python -m app.tenants migrate` and `list` | `backend/app/tenants.py` |
| Background tasks `fanout_master_data`, `fanout_deprecation` | `backend/app/worker.py` |
| Migrations | `backend/alembic/control/`, `backend/alembic/tenant/` |

Adding a migration:
- control database: `alembic revision --autogenerate -m "..."`;
- company databases: `alembic -n tenant -x db=<a company database> revision --autogenerate -m "..."`;
- a table that exists in both (library, master data, `app_user`, `job`, `notification`, `ai_usage`) needs one in each tree.
