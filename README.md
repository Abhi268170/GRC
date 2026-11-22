# TrustUp (POC)

AI-powered governance, risk and compliance platform.

AI-guided compliance and security assessments. See [PROJECT_IDEA.md](PROJECT_IDEA.md) for the product, [SCHEMA.md](SCHEMA.md) for the data model, and [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) for the UI design system.

## Run

```bash
cp .env.example .env        # then change the secrets
docker compose up -d --build
```

| URL | What |
|---|---|
| http://localhost:3100 (`FRONTEND_PORT` in `.env`) | Web app |
| http://localhost:8000/docs (`BACKEND_PORT`) | API docs |

Sign in as the super admin with `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` from `.env`, or create a tenant at `/signup`.

The `migrate` service runs once on every start: it creates the storage bucket, applies migrations, and seeds master data, the super admin (`SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`), six frameworks as clause references and titles (NIST CSF 2.0, ISO/IEC 27001:2022, ISO/IEC 27005:2022, GDPR, Swiss FADP and DPO), 25 domains and the organisational roles. The control library starts empty. Seeding is idempotent.

### Development (hot reload)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Also exposes the RustFS console at http://localhost:9001. If you add frontend packages, restart the `frontend` container (it runs `npm install` on start).

## What's built

- **Super admin:** control library with versioning and clause mapping, AI framework import (document to clause hierarchy), AI assessment builder with a coverage gate, master data.
- **Tenants:** self-signup, team management, assessment catalog, AI pre-assessment intake and question tailoring, AI-guided domain conversations with evidence upload, rating verification, domain assignment, completion and submission, formula scoring with AI explanations, framework coverage, AI action items / risks / report, review (approve or request changes), PDF/DOCX export, action item and risk registers, in-app notifications.

## Services

| Service | Purpose |
|---|---|
| `frontend` | Next.js UI; proxies `/api/*` to the backend |
| `backend` | FastAPI |
| `worker` | Background jobs (arq) |
| `migrate` | One-shot: bucket, migrations (control database, then every company database), seed |
| `postgres` | PostgreSQL 17 + pgvector |
| `redis` | Job queue |
| `rustfs` | S3-compatible object storage |

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
