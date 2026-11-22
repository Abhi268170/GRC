# Session notes: TrustUp (my_version)

Updated 2026-11-22. Read this first after a compaction.

## Project
- AI-powered GRC POC.
- Stack, run with Docker Compose (`docker-compose.yml` + `docker-compose.dev.yml`):
  - frontend: Next.js 16 + Tailwind v4 + shadcn + TanStack Query, on localhost:3100;
  - backend: FastAPI + async SQLAlchemy, on :8000, routes at `/` (the frontend proxies `/api`);
  - worker: arq;
  - postgres, redis, rustfs.
- Docs:
  - `PROJECT_IDEA.md` (decisions table, now up to #43);
  - `SCHEMA.md`;
  - `DESIGN_SYSTEM.md`;
  - `CONTROL_IMPORT_PLAN.md`;
  - `TENANT_DATABASE_PLAN.md` (one database per company; §15 deviations, §16 code map).

## Constraints from the user (always apply)
- Version control: a local git repository since 2026-11-22 (the user asked for it). No remote: never add one or push. `main` holds the baseline; work goes on a branch with one commit per logical change. Never commit `.env`.
- POC scope: data security isn't a concern yet.
- Never print secrets. The API key is in `.env`. `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` only go into a subprocess env (`set -a; . ./.env; set +a` then `-e VAR`), never echoed.
- Don't re-add decorative AI icons (Wand2, Sparkles, Zap were removed on purpose).
- Don't seed an example library or a demo assessment (cancelled). Keep the seeded domains (25 since decision 43).
- Use Playwright or agent-browser for browser checks, not `wslview`.
- Content max width is 1400px (`max-w-[87.5rem]`); the user found 1536px too stretched.
- Card hover is a static `hover:ring-2 hover:ring-brand/60`. The user removed the "shine" effect.
- Form radii: inputs `rounded-[10px]`, textareas `rounded-[12px]`.
- Ask clarifying questions on large specs. The user answers them and expects them followed exactly.

## Done in this session (all verified)
- **Domain list scroll:** the control library's domain list scrolls on its own and stays in place on large screens (`app/admin/library/page.tsx`).
- **Control import/export:** decisions 40 and 41; design in `CONTROL_IMPORT_PLAN.md`. Decisions:
  - Excel only, no AI;
  - changed controls become new drafts;
  - unknown references block the import, with suggestions;
  - all or nothing;
  - removing a requirement needs a tick;
  - the export holds only what can be imported;
  - draft assessments get an "update available" notice with "Use latest versions".
- **Import files:**
  - Backend:
    - `app/services/control_workbook.py`: the workbook layout, building and parsing it, and marking errors in it;
    - `app/services/control_import.py`: catalog, validation, diff, blockers, apply, export rows;
    - `app/api/library_import.py`: the `/library/export`, `/library/import-template` and `/library/imports` endpoints (preview, choices, the issues `.xlsx`, apply, publish, discard drafts, delete).
  - Model and migration:
    - the model is `ControlImport`, plus `ControlVersion.import_id`;
    - migration `20261122_a1c4e6f8b2d9_control_import.py`.
  - `ControlSummary.imported`.
  - Assessments:
    - `VersionDetail.control_updates`;
    - `POST /assessments/versions/{id}/use-latest-controls` keeps tags for requirements whose statement and guidance didn't change, then runs "uncovered" generation.
  - Frontend:
    - `app/admin/library/import/page.tsx`;
    - `components/library/import-review.tsx`;
    - the Export menu, Import button and "Imported" badge on the library page;
    - the notice on `app/admin/assessments/[versionId]/page.tsx`;
    - types in `lib/types.ts`.
- **Profile menu shift:** opening a menu, dialog or sheet shifted the page left by 7.5px. Cause: the Radix scroll lock adds a right margin while `html` already has `scrollbar-gutter: stable`. Fixed in `globals.css` with `html body[data-scroll-locked]{margin-right:0 !important}`. Verified with real 15px scrollbars.

- **One database per company (decision 42), built and verified.** The user decided: separate databases because the client asked; copy the assessment into the company database at run start; same Postgres server; drop `tenant_id` columns.
  - Control database `grc`: `tenant` registry (`db_name`, `status`), `login_directory` (email → tenant), super admin, library, master data, platform jobs and AI usage.
  - Company database `grc_t_<tenant id hex>`: users, runs and outputs, jobs, notifications, AI usage, copies of the library rows its runs use, a full mirror of master data and roles.
  - Code:
    - `core/db.py`: `ControlSession`, `session_for(tenant_id)`, `tenant_of(session)`;
    - `core/auth.py`: `ControlDB`, `TenantDB`, `HomeDB` (the session `CurrentUser` is loaded from);
    - `services/tenants.py`: `provision_tenant`, `remove_tenant`, `migrate_all`, `for_each_tenant`, `run_counts`;
    - `services/snapshot.py`: `copy_assessment_version`, `sync_master_data`, `deprecate_assessment_version`;
    - `core/queue.py`: `enqueue` passes the tenant id to arq; `enqueue_task` for the fan-outs;
    - `worker.py`: job functions take `(job_id, tenant_id)`; `fanout_master_data`, `fanout_deprecation`.
  - Migrations: `alembic/control` (new: `b7d2e9f1a3c5` registry, `c8e3f0a2b4d6` drop tenant tables) and `alembic/tenant` (`05b503c84f7f`). `python -m app.tenants migrate` runs both; `bootstrap.py` calls it.
  - The 2 existing companies and their 4 users were moved to their own databases.
  - Verified: `ruff`, `tsc`, `eslint`, `alembic check` on both trees, fresh install on an empty database, an API test over two new companies (full run, isolation 404s, users, run counts, deprecation, master data sync, failed-signup clean-up), a Playwright signup and super admin login. Test companies and test library content were removed afterwards.

## Current state
- **DB:** control database: 49 published controls (228 requirements), 0 assessments, 1 applied import; 25 domains, 22 org roles; six frameworks published (608 clauses); 2 tenants (`test`, `Northwind Labs`), each with its own database and no runs.
- **AI usage:** `ai_usage.run_id` has no foreign key now, so deleting runs no longer deletes usage rows. The control database has 3 rows from the verification run (question generation).
- **Open bugs / failing tests:** none known.
- **Client control workbook loaded (decision 43).** The user applied and published the import on 2026-11-22: 49 published controls, 228 requirements, 678 mappings, all stored as `ai_suggested`. Source workbook: `/mnt/c/Users/abhijith.sa/OneDrive - PITSOLUTIONS/Documents/360trustup/02-11-26/360TrustUp_Controls_Full_Set 02-11-2026.xlsx`.
  - The user decided: full public framework lists; mappings stored as `ai_suggested`; six new domains with the workbook's abbreviations; a converter script and the normal import.
  - Done and verified:
    - `backend/app/seed/frameworks.json` (+ `frameworks.py` loader): NIST-CSF 2.0 (134 clauses), ISO-27001 2022 (138: clauses 4-10 + 93 Annex A), ISO-27005 2022 (52), GDPR (125), CH-FADP 2023 (95), CH-DPO 2023 (64). Sources are in the `frameworks.py` docstring. `seed_frameworks` now adds missing clauses to existing published versions.
    - `backend/app/seed/library.py`: 25 domains (six new: LCM, AM, HRS, TVM, SML, ASM, with descriptions).
    - `backend/app/tools/convert_client_workbook.py`: stdin workbook, stdout import file, stderr report.
    - Output in `import-files/`: `360TrustUp_controls_import.xlsx` and `360TrustUp_controls_import_report.md`.
    - Conversion: all 678 references exist in the official lists; 44 have a paraphrased title (24 distinct, none looks like a wrong clause); 30 GDPR references name a paragraph and are linked to the whole article; 28 point at headings (not counted in coverage).
    - Import preview: 49 new, 0 errors, 0 warnings, 0 blockers; expected codes equal the workbook's IDs for all 49; none is missing a field needed to publish.
  - Not in scope (open questions for the client): the per-domain "Domain Question", selecting controls by company risk exposure (column blank), German content, a UI for the unverified flag.

## Gotchas
- The worker doesn't hot-reload. Restart it after changing backend services: `docker compose -f docker-compose.yml -f docker-compose.dev.yml restart worker`.
- The dev frontend sometimes serves stale CSS. Fix:
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml rm -sf frontend && docker volume rm grc_frontend_next`;
  - then `up -d frontend`.
- Headless Playwright hides scrollbars. Use `ignore_default_args=["--hide-scrollbars"]` to see layout shifts caused by the scrollbar.
- Playwright runs in Docker: `mcr.microsoft.com/playwright/python:v1.65.2-noble`, `--network host`, `pip install --break-system-packages playwright==1.65.2`.
- API test scripts are piped into `docker compose exec -T backend python -` (it has openpyxl), against http://localhost:8000.
- Checks:
  - `npx tsc --noEmit && npx eslint src` (in `frontend/`);
  - `~/.local/bin/ruff check app` (in `backend/`).
- DB access: `docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "…"'`. For a company database use `-d grc_t_<hex>` (`docker compose exec backend python -m app.tenants list` shows them).
- Schema changes need a migration in the right Alembic tree, or both for tables that exist in both databases (`README.md`).
- `alembic.ini` is baked into the backend image (not mounted in dev): rebuild `backend worker migrate` after changing it.
- Never call the Alembic helpers in `services/tenants.py` directly from async code; use `asyncio.to_thread` (the env files start their own event loop).
- A pre-split backup of the database is at `/tmp/claude-1000/-home-abhi-my-version/2b7be523-a799-41b2-92f5-d834bdbea036/scratchpad/grc_before_split.dump` (temporary location).
- `frontend/AGENTS.md`: Next 16 has breaking changes. Check `node_modules/next/dist/docs/` before using unfamiliar Next APIs.
