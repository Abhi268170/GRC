"""Pieces shared by several tasks."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class Usage(BaseModel):
    """What one model call used. The backend records it (it owns the per-run AI budget)."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


class TaskResponse(BaseModel, Generic[T]):
    output: T
    usage: Usage


# Error codes in ErrorBody.code.
ERROR_REFUSAL = "refusal"                # the model declined the request
ERROR_TRUNCATED = "truncated"            # the output hit the token limit
ERROR_INVALID_OUTPUT = "invalid_output"  # the output didn't match the schema
ERROR_PROVIDER = "provider_error"        # the model provider returned an error
ERROR_UNAVAILABLE = "unavailable"        # the provider couldn't be reached, or no API key is configured
ERROR_BAD_REQUEST = "bad_request"        # the request to the AI service was invalid
ERROR_UNAUTHORIZED = "unauthorized"


class ErrorBody(BaseModel):
    code: str
    message: str  # safe to show to a user


class ErrorResponse(BaseModel):
    error: ErrorBody
    usage: Usage | None = None  # set when the failed call still cost something


class Company(BaseModel):
    name: str
    industry: str | None = None
    employees: str | None = None
    # Summary written from the pre-assessment intake, when there is one.
    context_summary: str | None = None


class ControlContext(BaseModel):
    """The descriptive fields of a control, as the control library holds them."""

    label: str  # "IAM02 Manage Access Rights in a Structured Manner"
    area: str | None = None
    risk_exposure_level: str | None = None
    responsible_role: str | None = None
    classification: dict[str, list[str]] = Field(default_factory=dict)  # "Use case" -> values
    texts: dict[str, str] = Field(default_factory=dict)                 # "Key requirement" -> text


class Requirement(BaseModel):
    key: str  # short and stable within one assessment: R1, R2, ...
    statement: str
    guidance: str = ""
    evidence: list[str] = Field(default_factory=list)
    mandatory: bool | None = None


class ControlScope(BaseModel):
    context: ControlContext
    requirements: list[Requirement]


class DomainScope(BaseModel):
    name: str
    description: str | None = None
    controls: list[ControlScope]


class FileInput(BaseModel):
    """An uploaded file. Give `text` when the text is already extracted, otherwise the file itself."""

    filename: str
    content_type: str
    text: str | None = None
    data_b64: str | None = None


class EvidenceFile(BaseModel):
    """An evidence file that was already read: its summary and extracted text."""

    id: str
    filename: str
    summary: str | None = None
    text: str | None = None


__all__ = [
    "ERROR_BAD_REQUEST", "ERROR_INVALID_OUTPUT", "ERROR_PROVIDER", "ERROR_REFUSAL", "ERROR_TRUNCATED",
    "ERROR_UNAUTHORIZED", "ERROR_UNAVAILABLE",
    "Company", "ControlContext", "ControlScope", "DomainScope", "ErrorBody", "ErrorResponse", "EvidenceFile",
    "FileInput", "Requirement", "TaskResponse", "Usage",
]
