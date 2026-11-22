"""The AI guide: a tool-using conversation per run domain.

The AI service owns the prompt, the tool schemas and the model call. This module owns
everything else: the conversation state, which question is current, the tools themselves
(they write to the company's database) and the limits.

Design:
- The backend decides which question is current (deterministic order), never the model.
- The model helps the user answer, rates requirements (`rate_requirements`), records the
  answer (`record_answer`), or asks for missing detail (`ask_follow_up`).
- `record_answer` is rejected until every requirement the question covers has a rating.
- AI ratings are always `ai_suggested`; people verify them in the UI.
- The transcript is append-only and stored verbatim as the AI service returns it, with a
  system prompt frozen at conversation start. Changing state (current question, ratings so
  far, attached evidence) goes in each new user turn.
- One user turn is up to MAX_STEPS model calls: each call may ask for tools; the backend runs
  them and sends the results in the next call.
"""

import logging
import uuid
from collections.abc import AsyncIterator

import ai_contracts as contracts
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import tenant_of
from app.models import (
    AppUser,
    AssessmentRun,
    Conversation,
    ConversationMessage,
    EvaluationCitation,
    Evidence,
    RequirementEvaluation,
    Response,
    ResponseEvidence,
    RunDomain,
    RunQuestion,
)
from app.services import ai
from app.services.runs import (
    RunScope,
    company_contract,
    current_question,
    evaluations_by_req,
    load_run_scope,
    now,
    question_requirements,
)

log = logging.getLogger("guide")

MAX_STEPS = 5  # model calls per user turn
NO_PROGRESS_LIMIT = 3  # consecutive turns without progress before a wrap-up turn
EXTRA_TURNS = 3  # user turns allowed on a question beyond its follow-up limit
POST_QUESTION_TURNS = 5  # chat turns allowed once a domain's questions are all answered

# Shown to the user while a tool call is being written.
TOOL_STATUS = {
    contracts.TOOL_RATE_REQUIREMENTS: "Suggesting ratings…",
    contracts.TOOL_RECORD_ANSWER: "Saving your answer…",
    contracts.TOOL_ASK_FOLLOW_UP: "Preparing a follow-up question…",
}
CUT_OFF = "Your response was cut off before this call finished. Call it again, more concisely."


def follow_up_limit(scope: "RunScope", req_ids: list[uuid.UUID]) -> int:
    """A domain's single question is broad, so allow about two follow-ups per control it covers."""
    controls = {scope.by_id[r].control for r in req_ids if r in scope.by_id}
    return max(3, 2 * len(controls))


class Busy(HTTPException):
    """Another message is still being handled for this domain."""

    def __init__(self) -> None:
        super().__init__(409, "The guide is still working on the previous message. Wait a moment and try again.")


class Turn:
    """One user message and the agent loop that follows it."""

    def __init__(self, db: AsyncSession, run: AssessmentRun, rd: RunDomain, user: AppUser):
        self.db, self.run, self.rd, self.user = db, run, rd, user
        self.rated_keys: list[str] = []
        self.progressed = False  # set when a turn saves ratings, an answer or a follow-up
        self.cross_payloads: list[dict] = []  # answers to analyse against the rest of the assessment afterwards
        self.events: list[tuple[str, dict]] = []  # (text, data) system events for the UI

    async def setup(self) -> None:
        self.scope = await load_run_scope(self.db, self.run.assessment_version_id)
        # The conversation row is locked for the turn: two turns at once would each save the whole
        # state and one would be lost. A second turn is refused instead of waiting.
        try:
            self.conv = (await self.db.execute(
                select(Conversation).where(Conversation.run_domain_id == self.rd.id)
                .with_for_update(nowait=True).execution_options(populate_existing=True))).scalar_one()
        except DBAPIError as e:
            await self.db.rollback()
            raise Busy() from e
        state = dict(self.conv.state or {})
        if "system" not in state:
            name = next(d.name for d in self.scope.domains if d.avd_id == self.rd.assessment_version_domain_id)
            state["system"] = await ai.guide_system(contracts.GuideSystemIn(
                company=await company_contract(self.db, self.run), domain_name=name,
                domains=[d.contract() for d in self.scope.domains]))
            state["transcript"] = []
        state.setdefault("follow_ups", {})
        state.setdefault("pending_evidence", [])
        state.setdefault("rated_this_question", [])
        state.setdefault("no_progress", 0)
        state.setdefault("question_turns", {})
        state.setdefault("post_turns", 0)
        # Results of tool calls from a turn that ran out of steps: sent with the next user turn.
        state.setdefault("unsent_tool_results", [])
        self.state = state

    async def _position(self, rq: RunQuestion) -> str:
        qs = (await self.db.execute(select(RunQuestion).where(RunQuestion.run_domain_id == self.rd.id, RunQuestion.kind == "base")
                                    .order_by(RunQuestion.sort_order))).scalars().all()
        base_id = rq.parent_run_question_id or rq.id
        idx = next((i for i, q in enumerate(qs) if q.id == base_id), 0)
        return f"question {idx + 1} of {len(qs)}" + (", follow-up" if rq.kind == "follow_up" else "")

    def _base_id(self, rq: RunQuestion) -> str:
        return str(rq.parent_run_question_id or rq.id)

    async def _ui(self, role: str, content: str, data: dict | None = None, author: uuid.UUID | None = None) -> None:
        self.db.add(ConversationMessage(conversation_id=self.conv.id, role=role,
                                        content=content, data=data, author_id=author))

    # ----- tools -----

    async def rate_requirements(self, ratings: list[dict]) -> str:
        evals = await evaluations_by_req(self.db, self.run.id)
        valid_evidence = {str(e) for e in (await self.db.execute(select(Evidence.id).where(Evidence.run_id == self.run.id))).scalars()}
        notes = []
        for item in ratings:
            req = self.scope.by_key.get(item["requirement"])
            if req is None:
                notes.append(f"{item['requirement']}: unknown key, skipped")
                continue
            na = bool(item["not_applicable"])
            rating = None if na else item["rating"]
            if not na and (rating is None or not 0 <= rating <= 4):
                notes.append(f"{req.key}: rating must be 0-4 unless not applicable")
                continue
            if na and not (item.get("na_reason") or "").strip():
                notes.append(f"{req.key}: not applicable needs a reason")
                continue
            existing = evals.get(req.id)
            if existing and existing.status in ("verified", "overridden"):
                notes.append(f"{req.key}: already verified by a person, left unchanged")
                continue
            ev = existing or RequirementEvaluation(run_id=self.run.id, requirement_version_id=req.id, rationale="")
            ev.rating, ev.is_na, ev.na_reason = rating, na, (item.get("na_reason") or None) if na else None
            ev.ai_rating, ev.ai_is_na, ev.rationale, ev.status = rating, na, item["rationale"], "ai_suggested"
            if existing is None:
                self.db.add(ev)
            await self.db.flush()
            await self.db.execute(delete(EvaluationCitation).where(EvaluationCitation.evaluation_id == ev.id))
            for eid in item.get("evidence_ids") or []:
                if eid in valid_evidence:
                    self.db.add(EvaluationCitation(evaluation_id=ev.id, evidence_id=uuid.UUID(eid), excerpt=item.get("quote")))
            self.state["rated_this_question"] = list(dict.fromkeys(self.state["rated_this_question"] + [str(ev.id)]))
            self.rated_keys.append(req.key)
            self.progressed = True
            notes.append(f"{req.key}: saved as a suggestion")
        await self.db.flush()
        return "; ".join(notes)

    async def _save_response(self, rq: RunQuestion, answer: str, na: bool, na_reason: str | None) -> Response:
        resp = (await self.db.execute(select(Response).where(Response.run_question_id == rq.id))).scalar_one_or_none()
        if resp is None:
            resp = Response(run_id=self.run.id, run_question_id=rq.id, answered_by=self.user.id)
            self.db.add(resp)
        resp.answer_text, resp.is_na, resp.na_reason = answer, na, na_reason if na else None
        resp.answered_by, resp.answered_at, resp.updated_at = self.user.id, now(), now()
        await self.db.flush()
        for eid in self.state["pending_evidence"]:
            exists = await self.db.get(ResponseEvidence, (resp.id, uuid.UUID(eid)))
            if not exists:
                self.db.add(ResponseEvidence(response_id=resp.id, evidence_id=uuid.UUID(eid)))
        return resp

    async def record_answer(self, answer: str, not_applicable: bool, na_reason: str | None) -> str:
        rq = await current_question(self.db, self.rd)
        if rq is None:
            return "There is no open question in this domain."
        reqs = await question_requirements(self.db, self.scope, rq)
        evals = await evaluations_by_req(self.db, self.run.id)
        missing = [self.scope.by_id[r].key for r in reqs if r not in evals or evals[r].status == "awaiting_ai"]
        if missing:
            return f"Not saved: rate these requirements first with rate_requirements: {', '.join(missing)}."
        if not_applicable and not (na_reason or "").strip():
            return "Not saved: a reason is required when the question doesn't apply."
        self.cross_payloads.append({"source": "chat", "text": answer, "evidence_ids": list(self.state["pending_evidence"])})
        resp = await self._save_response(rq, answer, not_applicable, na_reason)
        for ev_id in self.state["rated_this_question"]:
            self.db.add(EvaluationCitation(evaluation_id=uuid.UUID(ev_id), response_id=resp.id))
        rq.status = "skipped_na" if not_applicable else "answered"
        await self.db.flush()
        self.state["pending_evidence"], self.state["rated_this_question"] = [], []
        self.progressed = True
        await self._ui("system_event", "Answer saved", {"kind": "answer_saved", "run_question_id": str(rq.id), "not_applicable": not_applicable})
        return await self._announce_next("Answer saved.")

    async def ask_follow_up(self, answer_so_far: str, question: str) -> str:
        rq = await current_question(self.db, self.rd)
        if rq is None:
            return "There is no open question to follow up on."
        base_id = self._base_id(rq)
        count = self.state["follow_ups"].get(base_id, 0)
        if count >= follow_up_limit(self.scope, await question_requirements(self.db, self.scope, rq)):
            return "Follow-up limit reached for this question. Rate the requirements with what you have and record the answer."
        await self._save_response(rq, answer_so_far, False, None)
        rq.status = "answered"
        fu = RunQuestion(run_id=self.run.id, run_domain_id=self.rd.id, kind="follow_up",
                         parent_run_question_id=uuid.UUID(base_id), text=question.strip(), sort_order=rq.sort_order)
        self.db.add(fu)
        await self.db.flush()
        self.state["follow_ups"][base_id] = count + 1
        self.progressed = True
        await self._ui("system_event", question.strip(), {"kind": "question", "run_question_id": str(fu.id), "follow_up": True})
        return "Follow-up saved and shown to the user as the current question. Briefly say why you're asking; don't repeat it verbatim."

    async def _announce_next(self, prefix: str) -> str:
        nxt = await current_question(self.db, self.rd)
        if nxt is None:
            await self._ui("system_event", "All questions answered", {"kind": "domain_done"})
            return (f"{prefix} That was the last question in this domain. Tell the user to review and confirm the "
                    "suggested ratings in the side panel, then complete the domain.")
        await self._ui("system_event", nxt.text, {"kind": "question", "run_question_id": str(nxt.id), "follow_up": False})
        reqs = await question_requirements(self.db, self.scope, nxt)
        na = f" The intake suggested it may not apply: {nxt.proposed_na_reason}." if nxt.proposed_na else ""
        return (f"{prefix} Next ({await self._position(nxt)}), now shown to the user: \"{nxt.text}\". "
                f"It covers {', '.join(self.scope.by_id[r].key for r in reqs)}.{na}")

    # ----- loop -----

    async def run_turn(self, text: str, evidence: list[Evidence]) -> None:
        """Non-streaming convenience wrapper around stream_turn."""
        async for _ in self.stream_turn(text, evidence):
            pass

    async def stream_turn(self, text: str, evidence: list[Evidence]) -> AsyncIterator[dict]:
        """Run one user turn, yielding UI events as the model writes:
        {"type": "text", "delta": str} and {"type": "status", "text": str}.
        Database changes are flushed, not committed; the caller commits."""
        await self.setup()
        rq = await current_question(self.db, self.rd)
        reqs = await question_requirements(self.db, self.scope, rq) if rq else []
        evals = await evaluations_by_req(self.db, self.run.id)
        position = await self._position(rq) if rq else ""
        follow_ups = self.state["follow_ups"].get(self._base_id(rq), 0) if rq else 0

        limit = follow_up_limit(self.scope, reqs)
        base_id = self._base_id(rq) if rq else None
        question_turns = self.state["question_turns"].get(base_id, 0) if base_id else 0
        wrap_up = rq is not None and (self.state["no_progress"] >= NO_PROGRESS_LIMIT - 1 or question_turns >= limit + EXTRA_TURNS - 1)
        context = contracts.TurnContext(
            question=contracts.CurrentQuestion(
                text=rq.text, position=position, requirement_keys=[self.scope.by_id[r].key for r in reqs],
                follow_ups_asked=follow_ups, follow_up_limit=limit,
                proposed_na_reason=rq.proposed_na_reason if rq.proposed_na else None) if rq else None,
            ratings=[contracts.RatingSoFar(key=self.scope.by_id[rid].key, rating=e.rating, is_na=e.is_na, status=e.status)
                     for rid, e in evals.items() if rid in self.scope.by_id and e.status != "awaiting_ai"],
            wrap_up=wrap_up)
        for ev in evidence:
            if str(ev.id) not in self.state["pending_evidence"]:
                self.state["pending_evidence"].append(str(ev.id))
        user_turn = contracts.UserTurn(context=context, text=text, evidence=[
            contracts.EvidenceFile(id=str(ev.id), filename=ev.filename, summary=ev.summary, text=ev.extracted_text)
            for ev in evidence])
        transcript: list[dict] = self.state["transcript"]
        await self._ui("user", text, {"evidence_ids": [str(e.id) for e in evidence]}, author=self.user.id)

        if self.rd.status == "not_started":
            self.rd.status = "in_progress"

        usage = ai.UsageTag("guide", tenant_of(self.db), self.run.id)
        unsent = [contracts.ToolResult(**r) for r in self.state["unsent_tool_results"]]
        step = contracts.GuideStepIn(system=self.state["system"], transcript=transcript, user_turn=user_turn,
                                     tool_results=unsent or None)
        results: list[contracts.ToolResult] = []
        visible: list[str] = []
        for _ in range(MAX_STEPS):
            step_text = False
            final: contracts.FinalEvent | None = None
            async for event in ai.guide_step(step, usage):
                if isinstance(event, contracts.TextEvent):
                    if not step_text and visible:
                        yield {"type": "text", "delta": "\n\n"}  # separate text from an earlier step
                    step_text = True
                    yield {"type": "text", "delta": event.delta}
                elif isinstance(event, contracts.ToolStartEvent):
                    yield {"type": "status", "text": TOOL_STATUS.get(event.name, "Working…")}
                else:
                    final = event
            transcript.extend(final.messages)
            visible += final.text
            results = []

            if final.refused:
                note = "I can't help with that request. Let's continue with the assessment question."
                yield {"type": "text", "delta": ("\n\n" if visible else "") + note}
                visible.append(note)
                break
            if not final.tool_calls or final.stop_reason not in ("tool_use", "max_tokens"):
                break
            for call in final.tool_calls:
                if final.truncated:
                    # A cut-off tool call is never run. Answering it keeps the transcript valid and lets the model retry.
                    results.append(contracts.ToolResult(tool_use_id=call.id, content=CUT_OFF, is_error=True))
                    continue
                args = call.input
                if call.name == contracts.TOOL_RATE_REQUIREMENTS:
                    out = await self.rate_requirements(args.get("ratings", []))
                elif call.name == contracts.TOOL_RECORD_ANSWER:
                    out = await self.record_answer(args["answer"], bool(args["not_applicable"]), args.get("na_reason"))
                elif call.name == contracts.TOOL_ASK_FOLLOW_UP:
                    out = await self.ask_follow_up(args["answer_so_far"], args["question"])
                else:
                    out = f"Unknown tool {call.name}"
                results.append(contracts.ToolResult(tool_use_id=call.id, content=out))
            step = contracts.GuideStepIn(system=self.state["system"], transcript=transcript, tool_results=results)
        # If the turn ran out of steps right after tool calls, their results go out with the next user turn.
        self.state["unsent_tool_results"] = [r.model_dump() for r in results]

        if visible:
            await self._ui("assistant", "\n\n".join(visible), {"rated": list(dict.fromkeys(self.rated_keys))})

        # Turn accounting (enforced here, not left to the model).
        if base_id:
            self.state["question_turns"][base_id] = question_turns + 1
        else:
            self.state["post_turns"] += 1
        self.state["no_progress"] = 0 if self.progressed else self.state["no_progress"] + 1
        still_open = await current_question(self.db, self.rd)
        if wrap_up and still_open is not None and self._base_id(still_open) == base_id:
            await self._close_question(still_open)
            yield {"type": "status", "text": "Moving on to keep things short…"}
        self.state["transcript"] = transcript
        self.save_state()
        await self.db.flush()

    async def _close_question(self, rq: RunQuestion) -> None:
        """The model didn't wrap up within the limit: close the question ourselves. Requirements still
        unrated stay unrated and are rated by a person in the panel; we never invent ratings."""
        await self._save_response(rq, "Closed automatically after the conversation limit was reached.", False, None)
        rq.status = "answered"
        self.state["pending_evidence"], self.state["rated_this_question"], self.state["no_progress"] = [], [], 0
        await self._ui("system_event", "Question closed", {"kind": "question_closed", "run_question_id": str(rq.id)})
        await self._announce_next("")
        await self.db.flush()

    def save_state(self) -> None:
        self.conv.state = self.state
        flag_modified(self.conv, "state")


async def turn_block_reason(db: AsyncSession, run: AssessmentRun, rd: RunDomain) -> str | None:
    if await ai.over_budget(db, run.id):
        return "AI assistance for this assessment has reached its limit. Rate any remaining requirements in the panel."
    if await current_question(db, rd) is None:
        conv = (await db.execute(select(Conversation).where(Conversation.run_domain_id == rd.id))).scalar_one()
        if (conv.state or {}).get("post_turns", 0) >= POST_QUESTION_TURNS:
            return "All questions in this domain are answered. Review the ratings in the panel, then complete the domain."
    return None
