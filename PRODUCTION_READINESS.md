# Production Readiness: What Was Done and What Is Left

Date: 2026-11-22. Branch: `production-readiness` (baseline is `main`).

This is the record of the technical review and the hardening work that followed it. It lists every review finding with its status, the decisions that were made while the owner was away, and what still has to happen before real customers use the system.

## 1. Summary

- The app is now three deployables: **frontend**, **backend** (API and worker) and **AI service**. Only a reverse proxy is published.
- Three read-only reviews (backend security, backend architecture, frontend) produced **73 findings**. **38 are fixed, 16 are partly fixed and 19 are open.** Every one is listed in §5.
- There is now an automated test suite (58 tests), an end-to-end smoke test, and a CI workflow.
- It is **not** ready for paying customers yet. §3 lists what is missing; the largest items are backups, monitoring, a sign-up policy and a verification of the AI-written framework mappings.

## 2. What changed

| Area | Change |
|---|---|
| Architecture | All model calls moved into `ai-service/` (stateless, no database). It owns prompts, output schemas, tool definitions and the provider key. The backend sends structured data and keeps state, rules and the AI budget. Shared request and response models are in `packages/ai_contracts/`. |
| Sign-in | Sessions can be revoked (password change, reset, deactivation, role change, logout). Login is limited per address and per email. Sign-up is limited and can be switched off. |
| Configuration | `ENVIRONMENT=production` refuses to start with placeholder or short secrets, sets Secure cookies and turns the API docs off. |
| Abuse limits | Request size cap, upload content checks, decompression-bomb checks, a monthly AI budget per company, a cap on open runs, a bounded cache of company database pools. |
| Permissions | Tenants can't read the control library. Intake, submission, evidence upload and the registers check who may act. |
| Background jobs | Per-job time limits. A job that fails, times out, is interrupted or can't be queued never leaves a run, file or version stuck. |
| Concurrency | Run status changes and chat turns are serialised with row locks. Background analysis can't overwrite a person's rating. |
| Operations | Request ids in logs and responses, readiness checks, timeouts on the database, storage and HTTP calls, health checks and memory limits for every container. |
| Deployment | `docker-compose.yml` is the production shape: a Caddy proxy (TLS, compression, security headers, body limit) in front; `/api` goes straight to the backend. `docker-compose.dev.yml` keeps the old development setup. |
| Frontend | Error pages with retry, a failed chat turn gives the message back, only "not signed in" redirects to login, the cache is cleared between users, clearer error messages. |
| Code structure | `api/runs.py` split into a package; job failure rules in `services/jobs.py`; file helpers in `core/uploads.py`; rate limits in `core/ratelimit.py`. |
| Tests | `backend/tests` (39), `ai-service/tests` (19), `scripts/e2e_smoke.py`, `docker-compose.test.yml`, `.github/workflows/ci.yml`. |

## 3. Before real customers use it

These are not done. The first four need a decision or an account that only the owner has.

1. **Backups.** Nothing backs up Postgres or the file store. One database per company makes per-company backup and restore possible, but no job does it yet.
2. **Monitoring and alerting.** There are health endpoints and structured log lines, but no metrics, error reporting or alerts.
3. **Sign-up policy.** Anyone can create a company. It is rate-limited and can be switched off (`SIGNUP_ENABLED=false`), but there is no email verification, invitation or captcha. Each sign-up creates a database.
4. **Framework mappings.** The 678 mappings loaded from the client's workbook were written by an AI and are stored as unverified. Someone has to check them against the standards.
5. **A domain and HTTPS.** Set `SITE_ADDRESS` to the host name; the proxy then obtains certificates itself. This was not tested with a real domain.
6. **Database role.** The app connects as the Postgres superuser. It needs a role that can create databases and nothing more.
7. **Secrets.** Generate real values for every secret in `.env`, including the new `AI_SERVICE_TOKEN`.
8. **Load.** Nothing was load-tested. Past a few hundred companies, PgBouncer is needed in front of Postgres.

## 4. Decisions made without the owner

The owner was away, so these were decided on their behalf. Each can be changed.

| Decision | Why | How to change it |
|---|---|---|
| The AI service is a third container called over HTTP with a shared bearer token. | It was the request ("frontend, backend, AI service"). HTTP keeps it independent of the backend's code and language. | — |
| Prompts moved into the AI service unchanged. | A move, not a rewrite: behaviour stays the same. | Edit `ai-service/app/tasks.py` and `guide.py`. |
| The backend keeps the AI budget and records usage. | Budgets are business rules and need the database. | — |
| A monthly AI budget of 100 USD per company and at most 25 open runs per company. | The review found that spend was only capped per run. | `TENANT_AI_BUDGET_USD_MONTH`, `MAX_OPEN_RUNS_PER_TENANT`. |
| Login locks an email for 15 minutes after 10 failed attempts. | Unlimited password guessing was possible. An attacker can use this to lock someone out for 15 minutes. | `login_*` settings in `backend/app/core/config.py`. |
| Sign-up: 5 per address and 60 in total per hour. | Each sign-up creates a database. | `SIGNUP_MAX_PER_IP`, `SIGNUP_MAX_TOTAL`, `SIGNUP_ENABLED`. |
| Logging out signs the user out on every device. | The simplest way to make a stolen token useless. | — |
| Tenants can no longer read the control library, frameworks or master data lists. | The tenant screens never used them, and they exposed the whole library, drafts included. | `backend/app/api/library.py`, `frameworks.py`, `master_data.py`. |
| Only the person who started a run, or an admin, can answer or skip the intake and submit the run. | Any member of the company could do it before. | `_require_reviewer` in `backend/app/api/runs/views.py`. |
| Action items and risks can be edited by an admin, the owner or the run's reviewer. | Any member could close or hide any risk before. | `_editable` in `backend/app/api/registers.py`. |
| Evidence other than PDFs and images always downloads; it never opens in the browser. | Opening uploaded files on the app's own address is a risk. | `download_evidence` in `backend/app/api/runs/evidence.py`. |
| A company whose database can't be migrated goes offline; the platform still starts. | One broken database stopped every company before. | `migrate_all` in `backend/app/services/tenants.py`. |
| The base compose file publishes only the proxy (ports 80 and 443). | The backend was reachable directly, which let callers bypass limits. | `HTTP_PORT`, `HTTPS_PORT`. Development is unchanged with the dev override. |
| A user who starts a run can still approve it. | This looks intended. It is listed as open (S9) for the owner to confirm. | — |

## 5. Every finding and its status

Status: **Fixed**, **Partly** (the note says what is left), **Open**.

### 5.1 Security (22)

| # | Finding | Status | Note |
|---|---|---|---|
| S1 | Open sign-up creates a database and a held connection per request | Partly | Limited per address and in total; can be switched off; company pools are bounded. Open: email verification or invitations. |
| S2 | AI spend capped per run only | Fixed | Monthly budget per company, cap on open runs. |
| S3 | Login not throttled; timing shows which emails exist | Fixed | Lockout per email, limit per address, same timing for unknown emails. Sign-up still answers "already exists". |
| S4 | A crafted file can take down the worker | Partly | Size checks before unpacking, page and sheet caps, memory limit, no retries. Open: parse in a separate process with a time limit. |
| S5 | No limit on uploads and request bodies | Fixed | Cap in the app and at the proxy; uploads read in chunks. |
| S6 | Tenants can read the whole control library and drafts | Fixed | |
| S7 | Sessions can't be revoked | Fixed | |
| S8 | Placeholder secrets accepted; API exposed directly | Partly | Checked in production; backend not published; docs off. Open: non-superuser database role. |
| S9 | A user can start a run and approve it themself | Open | Looks intended; needs the owner's decision. |
| S10 | Intake and submit have no permission check | Fixed | |
| S11 | Any member can edit or hide any action item or risk | Fixed | |
| S12 | Background AI writes can overwrite a verified rating | Fixed | Covered by a test. |
| S13 | Runs and jobs can get stuck | Fixed | Covered by a test. |
| S14 | State changes have no row locking | Fixed | Run status, chat turns, first question. |
| S15 | Blocking work on the event loop; connection held for a chat turn | Partly | Blocking calls moved to threads; the request's connection is released. A turn still holds one connection while it runs. |
| S16 | Download file names not sanitised | Fixed | |
| S17 | Prompt injection through evidence | Partly | Evidence can't break out of its block. Open: showing AI origin on results, explicit acceptance of AI-written items. |
| S18 | Internal error text shown to tenants | Fixed | |
| S19 | Missing length limits | Fixed | |
| S20 | Evidence served inline with a guessed type | Fixed | Content is checked on upload; `nosniff`; attachment by default. |
| S21 | Super admin check trusts the role in any database | Fixed | |
| S22 | Two-database clean-up paths are fragile | Partly | Half-built companies are only removed after 15 minutes; migrations take a lock. Open: a command that reconciles orphan login directory rows. |

### 5.2 Architecture (26)

| # | Finding | Status | Note |
|---|---|---|---|
| A1 | Company connection pools never close; fan-outs open every database | Partly | At most 50 pools per process (least recently used closes); run counts cached for two minutes. Open: keep run counts in the control database. |
| A2 | A chat turn holds two connections from a pool of five | Partly | The request's connection is released; pool is now 5 plus 5. The turn holds one. |
| A3 | Jobs and runs can get stuck | Fixed | |
| A4 | Blocking calls on the event loop | Fixed | Storage, hashing, report export. Building Excel exports is still synchronous. |
| A5 | One company's failed migration stops the platform | Partly | That company goes offline alone; one run at a time. Open: skip companies already up to date, migrate in parallel. |
| A6 | The run page makes about 95 queries and is polled | Partly | The run scope is cached. Open: grouped queries, paging for the run list. |
| A7 | The workspace reloads large text on every poll | Open | |
| A8 | The chat transcript is one JSON value rewritten every turn | Open | |
| A9 | No concurrency control on run state | Fixed | |
| A10 | Failed evidence can't be retried | Fixed | Uploading the same file again retries it. |
| A11 | Transactions held across AI calls; no overall deadline | Open | Each call has timeouts; a whole turn has no deadline. |
| A12 | AI spend and transient failures | Partly | Budgets fixed. Open: keep partial question generation, retry transient AI errors. |
| A13 | One queue and four slots for everything | Partly | Per-job time limits, configurable slots, no duplicate master data fan-outs. Open: separate queues. |
| A14 | No timeouts on Postgres, Redis or storage | Fixed | |
| A15 | Health checks are thin | Fixed | `/health/ready`, worker and frontend health checks. |
| A16 | Raw exception text reaches users | Fixed | Unique-constraint races still answer 500, not 409. |
| A17 | No metrics; worker logs lack ids | Partly | Job ids on worker logs and passed to the AI service. Open: metrics, tracing, error reporting. |
| A18 | Uploads read fully before the size check | Fixed | Downloads still load the file (at most 25 MB) into memory. |
| A19 | List endpoints with per-row queries and no paging | Open | |
| A20 | Compose and server settings are development defaults | Fixed | Open: backups, a Redis password. |
| A21 | Modules mix HTTP, rules and persistence | Partly | Run endpoints split; job rules in one place. Open: the Excel import calls into the API layer; services raise HTTP errors. |
| A22 | The environment name is free text | Fixed | |
| A23 | Duplicated logic | Partly | Budget checks and failure handling unified. Open: rating rules exist in four places. |
| A24 | Indexes don't match the queries | Fixed | |
| A25 | Dead code | Open | The non-streaming message endpoint, unused job type and columns. |
| A26 | Dockerfile details | Fixed | |

### 5.3 Frontend (25)

| # | Finding | Status | Note |
|---|---|---|---|
| F1 | Failed queries show an endless skeleton or a false empty state | Fixed | Error pages with retry. |
| F2 | A failed chat turn loses the answer; cut streams fail silently | Fixed | Open: a stop button. |
| F3 | Any failure of the session check sends the user to login | Fixed | |
| F4 | No security headers | Fixed | Set by the proxy and by Next. Open: a full content security policy for scripts. |
| F5 | Cached data survives a change of user | Fixed | |
| F6 | Backend address fixed at build time; no compression; API through the Next server | Fixed | The proxy handles all three in production. |
| F7 | The requirement sheet discards input; failed evidence blocks saving | Fixed | |
| F8 | Whole-list saves built from stale data overwrite changes | Open | |
| F9 | Irreversible actions fire on one click | Open | |
| F10 | Unsaved edits are lost without warning | Open | |
| F11 | Route protection is client-side only | Open | No data leaks: the API enforces access. |
| F12 | No paging or virtual lists | Open | |
| F13 | Every streamed token re-renders the workspace | Open | |
| F14 | Polling never stops | Open | The backend now settles stale jobs, so flags no longer stay set for ever. |
| F15 | API client gaps | Fixed | |
| F16 | Date-only values parsed as UTC | Fixed | |
| F17 | Every page is a client component | Open | |
| F18 | Large files mix fetching, state and presentation | Open | |
| F19 | Duplicated logic | Open | |
| F20 | Accessibility basics | Open | |
| F21 | Double-submit gaps | Open | The backend now refuses the duplicates. |
| F22 | Clause search sends a request per keystroke | Open | |
| F23 | API docs reachable through the frontend | Fixed | Off in production. |
| F24 | Unhandled errors on small actions | Fixed | |
| F25 | Dead code and build hygiene | Partly | Build context cleaned; one dead hook removed. |

## 6. How it was verified

- **Lint:** `ruff check backend ai-service packages scripts`, `npx tsc --noEmit`, `npx eslint src`.
- **Tests:** `docker compose -f docker-compose.test.yml run --rm backend-tests` (39 pass) and `... ai-service-tests` (19 pass).
- **Schema:** `alembic check` reports no drift for the control database and a company database.
- **End to end:** `scripts/e2e_smoke.py` against a throwaway stack built from `docker-compose.yml` with `ENVIRONMENT=production`, through the proxy, with real AI calls. It covers sign-up, a whole run, isolation between two companies, user management, deprecation and streaming chat.
- **Not verified:** HTTPS with a real domain, behaviour under load, and the Next.js error-page convention against the Next 16 documentation (the bundled docs could not be read; it was checked by building and by loading a page that fails).
