"""Tenant assessment runs: start, intake, domains, guided conversation, evidence, verification,
submission, review and approval, results and report export.

- schemas.py: request and response models
- views.py: read helpers shared by the endpoints
- lifecycle.py: a run from start to approval
- workspace.py: working on one domain (chat, ratings)
- evidence.py: evidence files"""

from fastapi import APIRouter

from app.api.runs import evidence, lifecycle, workspace
from app.api.runs.schemas import ActionOut, RiskOut
from app.api.runs.views import action_out, risk_out

router = APIRouter()
for module in (lifecycle, workspace, evidence):
    router.include_router(module.router)

__all__ = ["ActionOut", "RiskOut", "action_out", "risk_out", "router"]
