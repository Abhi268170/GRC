import logging

from fastapi import FastAPI

from app.api import (
    assessments,
    auth,
    frameworks,
    health,
    library,
    library_import,
    master_data,
    platform,
    registers,
    runs,
    users,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

# Served behind the Next.js proxy at /api (uvicorn --root-path /api).
app = FastAPI(title="TrustUp API", version="0.1.0")
for module in (health, auth, library, library_import, frameworks, assessments, master_data, users, platform, runs, registers):
    app.include_router(module.router)
