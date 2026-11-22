"""Jobs (status polling) and notifications. Both are read from the signed-in user's own database:
their company's, or the control database for the super admin."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from app.core.auth import CurrentUser, HomeDB
from app.models import Job, Notification

router = APIRouter(tags=["platform"])


class JobOut(BaseModel):
    id: uuid.UUID
    type: str
    status: str
    error: str | None
    result: dict | None


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    payload: dict
    read_at: datetime | None
    created_at: datetime


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: HomeDB, user: CurrentUser) -> JobOut:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return JobOut(id=job.id, type=job.type, status=job.status, error=job.error, result=job.result)


@router.get("/notifications", response_model=list[NotificationOut])
async def notifications(db: HomeDB, user: CurrentUser) -> list[NotificationOut]:
    rows = (await db.execute(select(Notification).where(Notification.user_id == user.id)
                             .order_by(Notification.created_at.desc()).limit(50))).scalars()
    return [NotificationOut(id=n.id, type=n.type, payload=n.payload, read_at=n.read_at, created_at=n.created_at)
            for n in rows]


@router.post("/notifications/read-all", status_code=204)
async def read_all(db: HomeDB, user: CurrentUser) -> None:
    await db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                     .values(read_at=datetime.now(UTC)))
    await db.commit()
