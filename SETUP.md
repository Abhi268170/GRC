# Setting up and running TrustUp

Everything runs in Docker Compose: there is nothing to install on the host except Docker.
For what the services are and how they fit together, see [README.md](README.md).

- [1. What you need](#1-what-you-need)
- [2. Get the code](#2-get-the-code)
- [3. Configure](#3-configure)
- [4. Start it (development)](#4-start-it-development)
- [5. First sign-in and first steps](#5-first-sign-in-and-first-steps)
- [6. Day-to-day commands](#6-day-to-day-commands)
- [7. Checks and tests](#7-checks-and-tests)
- [8. Run it like production](#8-run-it-like-production)
- [9. Share a running stack](#9-share-a-running-stack)
- [10. When something goes wrong](#10-when-something-goes-wrong)

## 1. What you need

| What | Why |
|---|---|
| Docker Engine with Docker Compose **2.24 or newer** (`docker compose version`) | The compose files use features older versions don't have. Docker Desktop on Windows (WSL 2) or macOS works. |
| About 6 GB of free memory and 10 GB of disk | Nine containers and their images. |
| An Anthropic API key | Every AI feature: framework import, question writing, guided assessments, results. Without it the app starts and the non-AI screens work, but AI steps fail. |
| Git | To get the code. |

Only needed if you want to run the lint and type checks outside Docker: Node.js 24 and [ruff](https://docs.astral.sh/ruff/).

## 2. Get the code

```bash
git clone git@github.com:Abhi268170/GRC.git
cd GRC
```

## 3. Configure

All settings live in one file, `.env`, which is never committed.

```bash
cp .env.example .env
```

Open `.env` and set at least these:

| Setting | Set it to |
|---|---|
| `ANTHROPIC_API_KEY` | Your key. |
| `SUPER_ADMIN_EMAIL`, `SUPER_ADMIN_PASSWORD` | The first sign-in. The account is created on first start. |
| `POSTGRES_PASSWORD` | Any password. **Choose it before the first start**: the database keeps the one it was created with. |
| `JWT_SECRET` | A long random value: `openssl rand -hex 32` |
| `RUSTFS_SECRET_KEY` | A random value: `openssl rand -hex 16` |

The placeholder values work for a first look on your own machine (`ENVIRONMENT=development`), but change them before anyone else can reach the stack.

Optional:

| Setting | Meaning |
|---|---|
| `FRONTEND_PORT`, `BACKEND_PORT` | Host ports in development (3000 and 8000). Change them if something else uses those ports. |
| `ZEFIX_USERNAME`, `ZEFIX_PASSWORD` | Company search in the Swiss commercial register at sign-up. Without them, people type their company in by hand. |
| `RUN_AI_BUDGET_USD` | Estimated AI spend allowed per assessment run (3). |

The full list of settings is in [README.md](README.md#run-in-production) and in `.env.example`.

## 4. Start it (development)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

The first start takes several minutes: it builds the images and the frontend installs its packages. Later starts take seconds.

To save typing, the rest of this guide uses a short name for that command:

```bash
alias dc='docker compose -f docker-compose.yml -f docker-compose.dev.yml'
```

Check that it is up:

```bash
dc ps                 # every service "running" (or "healthy"); migrate has exited with code 0
dc logs migrate       # ends with the seeding messages; any error here stops the backend from starting
dc logs -f frontend   # wait for "Ready" before opening the browser
```

| Address | What |
|---|---|
| http://localhost:3000 | The web app (`FRONTEND_PORT`) |
| http://localhost:8000/docs | API documentation, development only (`BACKEND_PORT`) |
| http://localhost:9001 | RustFS (file storage) console; sign in with `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` |

Code changes in `frontend/`, `backend/app/` and `ai-service/app/` are picked up without a restart. The one exception is the worker: see section 6.

What the first start sets up, by itself: the storage bucket, both sets of database tables, the super admin, six frameworks (NIST CSF 2.0, ISO/IEC 27001:2022, ISO/IEC 27005:2022, GDPR, Swiss FADP and DPO), 25 domains and the organisational roles. It is safe to run again: nothing is duplicated.

## 5. First sign-in and first steps

A new stack has frameworks and domains but **no controls and no assessments**, so a company that signs up has nothing to run yet. To get to a working assessment:

1. **Sign in as the super admin** at http://localhost:3000/login with `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`. You land in the admin area.
2. **Load the control library.** Open *Control library*, choose *Import*, and upload `import-files/360TrustUp_controls_import.xlsx` (49 controls, 228 requirements). Check the preview, apply it, then publish the imported drafts. `import-files/360TrustUp_controls_import_report.md` describes how that file was made.
3. **Build an assessment.** Open *Assessments*, create one from the published controls, let the AI write the questions, and publish it.
4. **Create a company.** Sign out and open http://localhost:3000/signup. Each sign-up creates a separate database for that company.
5. **Run the assessment as that company.** Confirm the company details when asked (required once before the first assessment), pick the assessment from the catalog and follow the guided conversation.

The product itself is described in [PROJECT_IDEA.md](PROJECT_IDEA.md).

## 6. Day-to-day commands

```bash
dc up -d                    # start
dc stop                     # stop, keep everything
dc ps                       # what is running
dc logs -f backend worker   # follow logs (any service names)
dc restart worker           # after changing backend/app/services or backend/app/worker.py
dc up -d --build            # after changing a Dockerfile, backend/pyproject.toml or ai-service/pyproject.toml
dc restart frontend         # after adding a frontend package (it runs npm install on start)
dc up migrate               # apply new database migrations
dc exec backend python -m app.tenants list   # companies and their databases
```

The worker does not reload by itself. If a background step (reading an uploaded file, producing results) behaves like old code, restart it.

Start again from nothing. **This deletes every database, every uploaded file and all accounts:**

```bash
dc down -v
```

Changing the data model needs a migration; the commands are in [README.md](README.md#databases-and-migrations).

## 7. Checks and tests

The tests run in their own containers against a throwaway Postgres and Redis. They never touch the development data and make no AI calls.

```bash
docker compose -f docker-compose.test.yml run --rm --build backend-tests
docker compose -f docker-compose.test.yml run --rm --build ai-service-tests
docker compose -f docker-compose.test.yml down -v

ruff check backend ai-service packages scripts              # Python lint
(cd frontend && npm ci && npx tsc --noEmit && npx eslint src)   # frontend types and lint
```

The same checks run on GitHub for every push and pull request (`.github/workflows/ci.yml`).

`scripts/e2e_smoke.py` takes a whole assessment through the API with real AI calls (a few cents) and leaves its test data behind. Run it against a throwaway stack only; the top of the file shows how.

## 8. Run it like production

In production only the reverse proxy is published; it serves the frontend and sends `/api` to the backend.

```bash
cp .env.example .env
# edit .env (below), then:
docker compose up -d --build
```

In `.env`:

| Setting | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `JWT_SECRET` | Random, at least 32 characters: `openssl rand -hex 32` |
| `AI_SERVICE_TOKEN` | Random, at least 24 characters: `openssl rand -hex 24` |
| `SUPER_ADMIN_PASSWORD` | At least 12 characters |
| `POSTGRES_PASSWORD`, `RUSTFS_SECRET_KEY` | Random; no placeholder left |
| `SITE_ADDRESS` | Your host name (`app.example.com`) for automatic HTTPS, or `:80` for plain HTTP behind something else that handles HTTPS |
| `ACCESS_PASSWORD_HASH` | Optional: one shared password in front of the whole app. How to make the hash is at the top of `deploy/Caddyfile`. Keep the single quotes around it. |

With `ENVIRONMENT=production` the backend and the AI service **refuse to start** while a secret is a placeholder or too short; `docker compose logs migrate backend ai-service` says which one. The app is then at `http://<host>` (or `https://<SITE_ADDRESS>`), on `HTTP_PORT` / `HTTPS_PORT`.

Before putting real data in it, read [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) section 3: backups and monitoring are not set up yet.

## 9. Share a running stack

`docker-compose.share.yml` gives a development stack a public `https://….ts.net` address through Tailscale Funnel, behind the shared password. The steps are in the header of that file. Never share without `ACCESS_PASSWORD_HASH` set.

## 10. When something goes wrong

| Symptom | What to do |
|---|---|
| `port is already allocated` on start | Something else uses the port. Set `FRONTEND_PORT` or `BACKEND_PORT` in `.env` and start again. Port 9001 (RustFS console, development only) is fixed in `docker-compose.dev.yml`. |
| The backend never starts | It waits for `migrate`. Run `dc logs migrate` and fix what it reports, then `dc up -d`. |
| `password authentication failed` in the migrate log | `POSTGRES_PASSWORD` was changed after the first start. Put the old one back, or start from nothing with `dc down -v` (deletes all data). |
| The browser shows the page but no styles, or old styles | `dc rm -sf frontend && docker volume rm grc_frontend_next && dc up -d frontend` |
| AI steps fail or answer "unavailable" | `ANTHROPIC_API_KEY` is missing or wrong. Fix `.env`, then `dc up -d ai-service`. `dc logs ai-service` shows the reason. |
| Guided chat stops with a budget message | The run reached `RUN_AI_BUDGET_USD`. Raise it in `.env`, then `dc up -d backend worker`. |
| An upload or "results" step never finishes | `dc logs worker`; then `dc restart worker`. |
| `additional_contexts` or `!override` is reported as invalid | Docker Compose is too old. Update to 2.24 or newer. |
