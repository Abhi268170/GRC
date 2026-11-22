"""The guided conversation: a tool-using model that helps a person answer one domain's questions.

The AI service is stateless. The backend keeps the conversation (the frozen system prompt and
the transcript, both opaque to it), decides which question is current, and runs the tools,
because the tools write to the company's database. One request to the AI service is one model
call ("step"):

1. `POST /v1/guide/system` once per conversation: builds the system prompt.
2. `POST /v1/guide/step` with `user_turn`: the service renders the user's message, calls the
   model and streams what it writes. The final event carries the messages to append to the
   transcript and the tool calls to run.
3. If there were tool calls, the backend runs them and calls `step` again with `tool_results`,
   until a step ends without tool calls.

The stream is Server-Sent Events; each `data:` line is one JSON event (see StepEvent)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from ai_contracts.common import Company, DomainScope, EvidenceFile, Usage

# Tool names. The backend implements them; the AI service defines their schemas.
TOOL_RATE_REQUIREMENTS = "rate_requirements"  # input: {"ratings": [{requirement, rating, not_applicable, na_reason, rationale, evidence_ids, quote}]}
TOOL_RECORD_ANSWER = "record_answer"          # input: {"answer", "not_applicable", "na_reason"}
TOOL_ASK_FOLLOW_UP = "ask_follow_up"          # input: {"answer_so_far", "question"}


class GuideSystemIn(BaseModel):
    company: Company
    domain_name: str
    domains: list[DomainScope]  # every requirement in the assessment (keys are stable)


class GuideSystemOut(BaseModel):
    system: str


class RatingSoFar(BaseModel):
    key: str
    rating: int | None = None
    is_na: bool = False
    status: str  # ai_suggested, verified, overridden


class CurrentQuestion(BaseModel):
    text: str
    position: str  # "question 1 of 3, follow-up"
    requirement_keys: list[str]
    follow_ups_asked: int
    follow_up_limit: int
    proposed_na_reason: str | None = None  # the intake suggested the question may not apply


class TurnContext(BaseModel):
    question: CurrentQuestion | None  # None: every question in the domain is answered
    ratings: list[RatingSoFar] = Field(default_factory=list)
    wrap_up: bool = False  # last turn allowed for this question: rate what is left and record the answer


class UserTurn(BaseModel):
    context: TurnContext
    text: str = ""
    evidence: list[EvidenceFile] = Field(default_factory=list)


class ToolResult(BaseModel):
    tool_use_id: str
    content: str
    is_error: bool = False


class GuideStepIn(BaseModel):
    """At least one of user_turn and tool_results. Both together: the previous turn ended with tool
    calls whose results were never sent (it ran out of steps), and the user has now written again."""

    system: str
    transcript: list[dict[str, Any]]  # as returned in earlier `final` events, in order
    user_turn: UserTurn | None = None
    tool_results: list[ToolResult] | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]


class TextEvent(BaseModel):
    type: Literal["text"] = "text"
    delta: str


class ToolStartEvent(BaseModel):
    type: Literal["tool_start"] = "tool_start"
    name: str


class FinalEvent(BaseModel):
    type: Literal["final"] = "final"
    messages: list[dict[str, Any]]  # append these to the transcript
    text: list[str]                 # the visible text the model wrote in this step
    stop_reason: str | None
    tool_calls: list[ToolCall]      # run these, then call `step` again with their results
    truncated: bool = False         # the output was cut off: don't run the tool calls, answer them with an error
    refused: bool = False
    usage: Usage


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


StepEvent = TextEvent | ToolStartEvent | FinalEvent | ErrorEvent

__all__ = [
    "TOOL_ASK_FOLLOW_UP", "TOOL_RATE_REQUIREMENTS", "TOOL_RECORD_ANSWER",
    "CurrentQuestion", "ErrorEvent", "FinalEvent", "GuideStepIn", "GuideSystemIn", "GuideSystemOut", "RatingSoFar",
    "StepEvent", "TextEvent", "ToolCall", "ToolResult", "ToolStartEvent", "TurnContext", "UserTurn",
]
