# TrustUp

AI-powered governance, risk and compliance platform: AI-guided compliance and security assessments.

| Document | What it covers |
|---|---|
| [PROJECT_IDEA.md](PROJECT_IDEA.md) | The product and the decisions log |
| [SCHEMA.md](SCHEMA.md) | The data model |
| [TENANT_DATABASE_PLAN.md](TENANT_DATABASE_PLAN.md) | One database per company |
| [CONTROL_IMPORT_PLAN.md](CONTROL_IMPORT_PLAN.md) | Excel import and export of the control library |
| [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) | The technical review: what was fixed, what is left before going live |
| [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) | The UI design system |

## Architecture

```
browser ──> proxy (Caddy: TLS, compression, headers, size limit)
              ├── /api/*  ──> backend (FastAPI) ──┬──> postgres (control database + one database per company)
              └── /*      ──> frontend (Next.js)  ├──> redis (job queue, rate limits)
                                                  ├──> rustfs (files)
                              worker (arq jobs) ──┴──> ai-service ──> model provider
```

- **frontend**: the web app. It holds no secrets and talks only to `/api`.
- **backend** and **worker**: the same image. They own the data, the rules and the AI budget. Long work (reading files, writing results) runs in the worker.
- **ai-service**: every model call. It is stateless and has no database: it owns the prompts, output schemas and the provider key, and is reachable only from the backend and the worker. The models of its API are in `packages/ai_contracts`, shared by both sides.
- Only the proxy is published. In development there is no proxy: the frontend and backend are published directly.

## Run in development (hot reload)

```bash
cp .env.example .env        # then change the secrets
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

| URL | What |
|---|---|
| http://localhost:3000 (`FRONTEND_PORT` in `.env`) | Web app |
| http://localhost:8000/docs (`BACKEND_PORT`) | API docs (development only) |
| http://localhost:9001 | RustFS console |

Sign in as the super admin with `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` from `.env`, or create a company at `/signup`. If you add frontend packages, restart the `frontend` container (it runs `npm install` on start).

The `migrate` service runs once on every start: it creates the storage bucket, applies migrations, and seeds master data, the super admin, six frameworks as clause references and titles (NIST CSF 2.0, ISO/IEC 27001:2022, ISO/IEC 27005:2022, GDPR, Swiss FADP and DPO), 25 domains and the organisational roles. The control library starts empty. Seeding is idempotent.

## Run in production

```bash
cp .env.example .env
# In .env: ENVIRONMENT=production, real values for every secret (including AI_SERVICE_TOKEN),
# and SITE_ADDRESS=your.host.name for automatic HTTPS.
docker compose up -d --build
```

- With `ENVIRONMENT=production` the backend and the AI service refuse to start with placeholder or short secrets.
- The proxy listens on `HTTP_PORT` and `HTTPS_PORT` (80 and 443). Nothing else is published.
- Read [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) §3 first: backups, monitoring and a sign-up policy are not in place yet.

| Setting | Default | Meaning |
|---|---|---|
| `SIGNUP_ENABLED` | `true` | Self-service sign-up. Each sign-up creates a database. |
| `SIGNUP_MAX_PER_IP`, `SIGNUP_MAX_TOTAL` | 5, 60 | Sign-ups per hour, per address and in total. |
| `RUN_AI_BUDGET_USD` | 3 | Estimated AI spend allowed per assessment run. |
| `TENANT_AI_BUDGET_USD_MONTH` | 100 | Estimated AI spend allowed per company per month. |
| `MAX_OPEN_RUNS_PER_TENANT` | 25 | Runs a company can have open at once. |
| `BACKEND_WORKERS` | 2 | API processes. |
| `WORKER_MAX_JOBS` | 8 | Background jobs at once per worker. |
| `AI_MAX_CONCURRENT_CALLS` | 16 | Model calls at once per AI service process. |
| `TENANT_POOL_CACHE_SIZE` | 50 | Company database pools kept open per process. |
| `POSTGRES_MAX_CONNECTIONS` | 300 | Past a few hundred companies, add PgBouncer. |

## Checks

```bash
ruff check backend ai-service packages scripts                            # lint (Python)
(cd frontend && npx tsc --noEmit && npx eslint src)                       # types and lint (frontend)
docker compose -f docker-compose.test.yml run --rm --build backend-tests      # 39 tests, throwaway Postgres and Redis
docker compose -f docker-compose.test.yml run --rm --build ai-service-tests   # 19 tests, no model calls
docker compose -f docker-compose.test.yml down -v
```

`scripts/e2e_smoke.py` runs a whole assessment through the public API with real AI calls. It leaves test data behind, so run it against a throwaway stack only (the file's header shows how).

## What's built

- **Super admin:** control library with versioning and clause mapping, AI framework import (document to clause hierarchy), AI assessment builder with a coverage gate, master data.
- **Tenants:** self-signup, team management, assessment catalog, AI pre-assessment intake and question tailoring, AI-guided domain conversations with evidence upload, rating verification, domain assignment, completion and submission, formula scoring with AI explanations, framework coverage, AI action items / risks / report, review (approve or request changes), PDF/DOCX export, action item and risk registers, in-app notifications.

## Services

| Service | Purpose |
|---|---|
| `proxy` | Caddy. The only published service (production). See `deploy/Caddyfile`. |
| `frontend` | Next.js UI |
| `backend` | FastAPI: the API |
| `worker` | Background jobs (arq), same image as the backend |
| `ai-service` | FastAPI: prompts and model calls. Internal only. |
| `migrate` | One-shot: bucket, migrations (control database, then every company database), seed |
| `postgres` | PostgreSQL 17 |
| `redis` | Job queue and rate limits |
| `rustfs` | S3-compatible object storage |

## Repository layout

| Path | What |
|---|---|
| `frontend/` | Next.js app |
| `backend/app/api/` | HTTP endpoints (`runs/` is a package: lifecycle, workspace, evidence) |
| `backend/app/services/` | Business logic: runs, guide, jobs, tenants, snapshot, control import, `ai.py` (client of the AI service) |
| `backend/app/core/` | Config, database sessions, auth, queue, storage, rate limits, uploads, logging |
| `backend/alembic/` | Two migration trees: `control/` and `tenant/` |
| `backend/tests/`, `ai-service/tests/` | Automated tests |
| `ai-service/app/` | `tasks.py` (prompts per task), `guide.py` (the guided chat), `provider.py` (the model SDK), `rendering.py` |
| `packages/ai_contracts/` | Request and response models of the AI service API, used by both sides |
| `deploy/Caddyfile` | Reverse proxy configuration |
| `scripts/e2e_smoke.py` | End-to-end smoke test |

## Databases and migrations

Each company has its own Postgres database on the same server, named `<POSTGRES_DB>_t_<tenant id>`. The control database (`POSTGRES_DB`) holds the tenant registry, the login directory, the super admin, the library and master data. Design: `TENANT_DATABASE_PLAN.md`.

There are two migration trees: `backend/alembic/control` and `backend/alembic/tenant`. The `migrate` service upgrades the control database and then every company database.

```bash
# after changing models in backend/app/models

# control database (library, master data, registry)
docker compose run --rm --no-deps -v ./backend:/app migrate alembic revision --autogenerate -m "describe change"

# company databases (users, runs, results); <db> is any existing company database
docker compose run --rm --no-deps -v ./backend:/app migrate alembic -n tenant -x db=<db> revision --autogenerate -m "describe change"

# a table that exists in both (library, master data, app_user, job, notification, ai_usage) needs both

docker compose up migrate                                    # apply everywhere
docker compose exec backend python -m app.tenants list       # companies and their databases
```
