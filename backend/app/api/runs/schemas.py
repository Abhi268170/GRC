"""Request and response models of the run endpoints."""

import uuid
from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, Field


class StartIn(BaseModel):
    assessment_version_id: uuid.UUID

class Person(BaseModel):
    id: uuid.UUID
    full_name: str

class DomainSummary(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    assignee: Person | None
    questions_total: int
    questions_done: int
    requirements_total: int
    requirements_rated: int
    requirements_verified: int
    can_work: bool
    score: float | None
    open_comments: int

class RunSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    version: int
    version_deprecated: bool
    started_by: Person
    started_at: datetime | None
    approved_at: datetime | None
    progress: int  # % of requirements verified
    domains_total: int
    domains_completed: int
    score: float | None

class RunDetail(RunSummary):
    assessment_description: str | None
    intake: dict | None
    intake_job: str | None
    outputs_job_status: str | None
    outputs_job_error: str | None
    domains: list[DomainSummary]
    can_review: bool
    is_admin: bool
    ai_paused: bool  # the run's AI budget is used up; finish by rating manually

class IntakeIn(BaseModel):
    answers: dict[Annotated[str, Field(max_length=16)], Annotated[str, Field(max_length=2000)]] = Field(max_length=20)

class AssignIn(BaseModel):
    user_id: uuid.UUID | None

class MessageIn(BaseModel):
    content: str = Field(default="", max_length=4000)
    evidence_ids: list[uuid.UUID] = Field(default=[], max_length=20)

class NaIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

class EvaluationIn(BaseModel):
    rating: int | None = Field(default=None, ge=0, le=4)
    is_na: bool = False
    na_reason: str | None = Field(default=None, max_length=2000)

class ChangesIn(BaseModel):
    run_domain_id: uuid.UUID
    comment: str = Field(min_length=3, max_length=4000)

class EvidenceOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    processing_status: str
    summary: str | None
    uploaded_by: uuid.UUID
    created_at: datetime

class Citation(BaseModel):
    evidence_id: uuid.UUID | None
    evidence_filename: str | None
    response_id: uuid.UUID | None
    excerpt: str | None

class EvaluationOut(BaseModel):
    id: uuid.UUID
    rating: int | None
    is_na: bool
    na_reason: str | None
    rationale: str
    ai_rating: int | None
    ai_is_na: bool | None
    status: str
    verified_by: Person | None
    answer: str | None
    citations: list[Citation]

class RequirementState(BaseModel):
    id: uuid.UUID
    key: str
    control: str
    statement: str
    guidance: str  # how to meet it
    evidence: list[str]  # what can be checked to show the requirement is met
    mandatory: bool | None
    clauses: list[dict]
    evaluation: EvaluationOut | None

class QuestionState(BaseModel):
    id: uuid.UUID
    kind: str
    parent_id: uuid.UUID | None
    text: str
    help_text: str | None
    status: str
    proposed_na: bool
    proposed_na_reason: str | None
    requirement_keys: list[str]
    answer: str | None

class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    data: dict | None
    author: Person | None
    created_at: datetime

class Workspace(BaseModel):
    run_id: uuid.UUID
    run_status: str
    domain: DomainSummary
    current_question_id: uuid.UUID | None
    questions: list[QuestionState]
    requirements: list[RequirementState]
    messages: list[MessageOut]
    evidence: list[EvidenceOut]
    comments: list[dict]
    editable: bool
    ai_paused: bool
    analysis_pending: bool  # background cross-analysis queued or running for this run

class RequirementIn(BaseModel):
    answer: str | None = Field(default=None, max_length=4000)
    rating: int | None = Field(default=None, ge=0, le=4)
    is_na: bool = False
    na_reason: str | None = Field(default=None, max_length=2000)
    evidence_ids: list[uuid.UUID] = Field(default=[], max_length=20)

class ItemOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: str
    requirement_keys: list[str]

class ActionOut(ItemOut):
    priority: str | None
    owner: Person | None
    due_date: str | None

class RiskOut(ItemOut):
    category: str | None
    likelihood: int
    impact: int
    score: int
    treatment: str | None
    owner: Person | None

class Results(BaseModel):
    report: dict | None
    report_status: str | None
    actions: list[ActionOut]
    risks: list[RiskOut]
