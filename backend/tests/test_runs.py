"""Assessment runs: starting one, isolation between companies, permissions, files, the guided chat, jobs."""

from contextlib import aclosing
import io
import zipfile
from datetime import UTC, datetime, timedelta

import ai_contracts as contracts
from sqlalchemy import select, text

from app.api.runs import evidence as runs_api
from app.core.config import get_settings
from app.core.db import session_for
from app.models import AiUsage, AssessmentRun, Job, RequirementEvaluation
from app.services import cross_analysis, jobs
from tests.conftest import PASSWORD, new_client, signup


async def start_run(c, assessment) -> dict:
    r = await c.post("/runs", json={"assessment_version_id": assessment["version_id"]})
    assert r.status_code == 201, r.text
    run = r.json()
    skipped = await c.post(f"/runs/{run['id']}/intake/skip")
    assert skipped.status_code == 200, skipped.text
    return skipped.json()


async def add_member(admin, email_prefix: str = "member") -> tuple:
    me = (await admin.get("/auth/me")).json()
    created = (await admin.post("/users", json={"email": f"{email_prefix}-{me['user']['email']}", "full_name": "Mia Member"})).json()
    member = new_client()
    await member.post("/auth/login", json={"email": created["user"]["email"], "password": created["temporary_password"]})
    await member.post("/auth/change-password", json={"current_password": created["temporary_password"], "new_password": PASSWORD})
    return member, created["user"]


async def test_a_run_works_on_the_companys_own_copy(assessment):
    c, me = await signup()
    async with aclosing(c):
        run = await start_run(c, assessment)
        assert run["status"] == "in_progress" and len(run["domains"]) == 1
        async with session_for(me["tenant"]["id"]) as db:
            counts = dict((await db.execute(text(
                "select 'control_version', count(*) from control_version union all "
                "select 'requirement_version', count(*) from requirement_version union all "
                "select 'question', count(*) from question"))).all())
            assert counts == {"control_version": 1, "requirement_version": 2, "question": 1}
        workspace = (await c.get(f"/runs/{run['id']}/domains/{run['domains'][0]['id']}")).json()
        assert [r["key"] for r in workspace["requirements"]] == ["R1", "R2"]
        assert workspace["messages"][0]["data"]["kind"] == "question"


async def test_companies_cannot_see_each_others_runs(assessment):
    a, _ = await signup("Company A")
    b, _ = await signup("Company B")
    async with aclosing(a), aclosing(b):
        run = await start_run(a, assessment)
        domain = run["domains"][0]["id"]
        assert (await b.get("/runs")).json() == []
        for path in (f"/runs/{run['id']}", f"/runs/{run['id']}/domains/{domain}", f"/runs/{run['id']}/results"):
            assert (await b.get(path)).status_code == 404, path
        assert (await b.post(f"/runs/{run['id']}/submit")).status_code == 404


async def test_open_runs_and_monthly_ai_budget_are_capped(assessment, monkeypatch):
    c, me = await signup()
    async with aclosing(c):
        monkeypatch.setattr(get_settings(), "max_open_runs_per_tenant", 1)
        await start_run(c, assessment)
        second = await c.post("/runs", json={"assessment_version_id": assessment["version_id"]})
        assert second.status_code == 409 and "too many" in second.json()["detail"]
        monkeypatch.setattr(get_settings(), "max_open_runs_per_tenant", 25)
        async with session_for(me["tenant"]["id"]) as db:
            db.add(AiUsage(feature="test", model="fake", input_tokens=1, output_tokens=1, cost_usd=500))
            await db.commit()
        over = await c.post("/runs", json={"assessment_version_id": assessment["version_id"]})
        assert over.status_code == 409 and "AI allowance" in over.json()["detail"]


async def test_only_reviewers_run_the_intake_and_submit(assessment):
    admin, _ = await signup()
    member, _ = await add_member(admin)
    async with aclosing(admin), aclosing(member):
        run = (await admin.post("/runs", json={"assessment_version_id": assessment["version_id"]})).json()
        assert (await member.post(f"/runs/{run['id']}/intake/skip")).status_code == 403
        assert (await admin.post(f"/runs/{run['id']}/intake/skip")).status_code == 200
        assert (await member.post(f"/runs/{run['id']}/submit")).status_code == 403
        assert (await admin.post(f"/runs/{run['id']}/submit")).status_code == 409  # allowed, but domains aren't complete


async def test_rating_completing_and_assigned_domains(assessment):
    admin, _ = await signup()
    member, member_user = await add_member(admin)
    async with aclosing(admin), aclosing(member):
        run = await start_run(admin, assessment)
        domain = run["domains"][0]["id"]
        # assigned to the admin: the member can't work on it
        me = (await admin.get("/auth/me")).json()["user"]["id"]
        assert (await admin.put(f"/runs/{run['id']}/domains/{domain}/assignee", json={"user_id": me})).status_code == 200
        blocked = await member.put(f"/runs/{run['id']}/requirements/{assessment['requirement_ids'][0]}", json={"rating": 3})
        assert blocked.status_code == 403
        assert (await admin.post(f"/runs/{run['id']}/domains/{domain}/complete")).status_code == 409  # nothing rated yet
        for rid in assessment["requirement_ids"]:
            saved = await admin.put(f"/runs/{run['id']}/requirements/{rid}", json={"rating": 3})
            assert saved.status_code == 200, saved.text
        done = await admin.post(f"/runs/{run['id']}/domains/{domain}/complete")
        assert done.status_code == 200 and done.json()["domains"][0]["status"] == "completed"
        assert (await admin.put(f"/runs/{run['id']}/requirements/{assessment['requirement_ids'][0]}", json={"rating": 1})).status_code == 409


async def test_evidence_upload_checks_and_download_headers(assessment, storage, monkeypatch):
    c, me = await signup()
    async with aclosing(c):
        run = await start_run(c, assessment)
        url = f"/runs/{run['id']}/evidence"
        assert (await c.post(url, files={"file": ("tool.exe", b"MZ\x90", "application/octet-stream")})).status_code == 422
        fake_pdf = await c.post(url, files={"file": ("policy.pdf", b"<html>not a pdf</html>", "application/pdf")})
        assert fake_pdf.status_code == 422 and "doesn't look like a PDF" in fake_pdf.json()["detail"]
        monkeypatch.setattr(runs_api, "MAX_EVIDENCE", 10)
        assert (await c.post(url, files={"file": ("big.txt", b"x" * 11, "text/plain")})).status_code == 413
        monkeypatch.setattr(runs_api, "MAX_EVIDENCE", 25 * 1024 * 1024)

        ok = await c.post(url, files={"file": ("../Política – 2026.txt", "Zugriffsprüfung 2026".encode(), "text/plain")})
        assert ok.status_code == 201, ok.text
        evidence = ok.json()
        assert evidence["filename"] == "Política – 2026.txt"
        key = next(iter(storage))
        assert key == f"tenants/{me['tenant']['id']}/runs/{run['id']}/evidence/{evidence['id']}"  # no file name in the key
        again = await c.post(url, files={"file": ("copy.txt", "Zugriffsprüfung 2026".encode(), "text/plain")})
        assert again.json()["id"] == evidence["id"] and len(storage) == 1  # the same content is stored once

        download = await c.get(f"{url}/{evidence['id']}/file")
        assert download.status_code == 200 and download.content == "Zugriffsprüfung 2026".encode()
        assert download.headers["x-content-type-options"] == "nosniff"
        assert download.headers["content-disposition"].startswith("attachment;")  # text never opens in the browser
        assert "filename*=UTF-8''Pol%C3%ADtica" in download.headers["content-disposition"]


async def test_a_zip_bomb_fails_the_evidence_job_not_the_worker(assessment, storage, monkeypatch, fake_ai):
    from app.services import documents, evidence

    c, me = await signup()
    async with aclosing(c):
        run = await start_run(c, assessment)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", b"0" * 500_000)
        uploaded = (await c.post(f"/runs/{run['id']}/evidence", files={"file": (
            "bomb.docx", out.getvalue(), documents.DOCX)})).json()
        monkeypatch.setattr(documents, "MAX_UNZIPPED_BYTES", 1000)
        monkeypatch.setattr(evidence, "get_object", lambda key: storage[key])
        async with session_for(me["tenant"]["id"]) as db:
            try:
                await evidence.process(db, uploaded["id"])
                raise AssertionError("expected the file to be refused")
            except Exception as e:  # noqa: BLE001
                assert jobs.safe_message(e) == "The file is too large to read once it is unpacked"
        assert fake_ai.calls == []  # never sent to the AI service


async def test_a_guided_turn_saves_ratings_as_suggestions(assessment, fake_ai):
    c, me = await signup()
    async with aclosing(c):
        run = await start_run(c, assessment)
        domain = run["domains"][0]["id"]
        await c.get(f"/runs/{run['id']}/domains/{domain}")
        rate = (contracts.TOOL_RATE_REQUIREMENTS, {"ratings": [
            {"requirement": "R1", "rating": 3, "not_applicable": False, "na_reason": None, "rationale": "Reviewed twice a year.",
             "evidence_ids": [], "quote": "twice a year"},
            {"requirement": "R2", "rating": 9, "not_applicable": False, "na_reason": None, "rationale": "x", "evidence_ids": [], "quote": None},
            {"requirement": "R99", "rating": 1, "not_applicable": False, "na_reason": None, "rationale": "x", "evidence_ids": [], "quote": None},
        ]})
        fake_ai.steps = [
            [contracts.TextEvent(delta="Thanks. "), contracts.ToolStartEvent(name=contracts.TOOL_RATE_REQUIREMENTS), fake_ai.final([rate])],
            [contracts.TextEvent(delta="One more thing."), fake_ai.final(text=["One more thing."])],
        ]
        r = await c.post(f"/runs/{run['id']}/domains/{domain}/messages/stream", json={"content": "We review access twice a year."})
        events = [line for line in r.text.splitlines() if line.startswith("data: ")]
        assert '"type": "done"' in events[-1] and any("Suggesting ratings" in e for e in events)

        steps = [body for path, body in fake_ai.calls if path == "/guide/step"]
        assert steps[0].user_turn.context.question.requirement_keys == ["R1", "R2"] and steps[0].tool_results is None
        # the tool's answers went back to the model: saved, out of range, unknown key
        result = steps[1].tool_results[0].content
        assert "R1: saved as a suggestion" in result and "R2: rating must be 0-4" in result and "R99: unknown key" in result

        workspace = (await c.get(f"/runs/{run['id']}/domains/{domain}")).json()
        ratings = {r["key"]: r["evaluation"] for r in workspace["requirements"]}
        assert ratings["R1"]["status"] == "ai_suggested" and ratings["R1"]["rating"] == 3 and ratings["R2"] is None
        assert [m["role"] for m in workspace["messages"]][-2:] == ["user", "assistant"]
        async with session_for(me["tenant"]["id"]) as db:
            assert [(f, float(c)) for f, c in await db.execute(select(AiUsage.feature, AiUsage.cost_usd).where(AiUsage.feature == "guide"))] == [
                ("guide", 0.01), ("guide", 0.01)]


async def test_a_failed_turn_saves_nothing(assessment, fake_ai):
    from app.services import ai

    c, _ = await signup()
    async with aclosing(c):
        run = await start_run(c, assessment)
        domain = run["domains"][0]["id"]
        before = (await c.get(f"/runs/{run['id']}/domains/{domain}")).json()

        async def broken_step(body, usage=None):
            yield contracts.TextEvent(delta="Thanks")
            raise ai.AIError("Could not reach the AI service")

        ai.guide_step = broken_step  # restored by the fake_ai fixture's monkeypatch
        r = await c.post(f"/runs/{run['id']}/domains/{domain}/messages/stream", json={"content": "Hello"})
        assert '"type": "error"' in r.text and "Could not reach the AI service" in r.text
        after = (await c.get(f"/runs/{run['id']}/domains/{domain}")).json()
        assert len(after["messages"]) == len(before["messages"])


async def test_background_analysis_never_overwrites_a_persons_rating(assessment, fake_ai):
    """The person rates while the model is still working: their rating stays."""
    c, me = await signup()
    async with aclosing(c):
        run = await start_run(c, assessment)
        r1, r2 = assessment["requirement_ids"]

        async def slow_model(path, body, output, usage=None):
            # While the analysis waits for the model, a person confirms R1 themself.
            saved = await c.put(f"/runs/{run['id']}/requirements/{r1}", json={"rating": 4})
            assert saved.status_code == 200
            return output(ratings=[
                contracts.CrossRating(requirement="R1", rating=0, not_applicable=False, na_reason=None, rationale="AI says 0", evidence_ids=[], quote=None),
                contracts.CrossRating(requirement="R2", rating=2, not_applicable=False, na_reason=None, rationale="AI says 2", evidence_ids=[], quote=None),
            ])

        from app.services import ai

        ai.call = slow_model
        async with session_for(me["tenant"]["id"]) as db:
            result = await cross_analysis.analyze(db, run["id"], {"source": "chat", "text": "We do reviews.", "evidence_ids": []})
            await db.commit()
        assert result == {"updated": ["R2"]}
        async with session_for(me["tenant"]["id"]) as db:
            rows = {str(e.requirement_version_id): e for e in (await db.execute(select(RequirementEvaluation))).scalars()}
            assert rows[r1].rating == 4 and rows[r1].status in ("verified", "overridden")
            assert rows[r2].rating == 2 and rows[r2].status == "ai_suggested"


async def test_a_job_that_never_finished_does_not_leave_the_run_stuck(assessment):
    c, me = await signup()
    async with aclosing(c):
        run = await start_run(c, assessment)
        async with session_for(me["tenant"]["id"]) as db:
            row = await db.get(AssessmentRun, run["id"])
            row.status = "generating_outputs"
            long_ago = datetime.now(UTC) - timedelta(hours=3)
            db.add(Job(type="generate_outputs", status="running", ref_type="assessment_run", ref_id=row.id, started_at=long_ago))
            db.add(Job(type="cross_analyze", status="queued", ref_type="assessment_run", ref_id=row.id, created_at=datetime.now(UTC)))
            await db.commit()
        detail = (await c.get(f"/runs/{run['id']}")).json()
        assert detail["status"] == "in_progress"                       # usable again
        assert detail["outputs_job_status"] == "failed" and detail["outputs_job_error"] == jobs.INTERRUPTED
        async with session_for(me["tenant"]["id"]) as db:
            statuses = dict((await db.execute(select(Job.type, Job.status).where(Job.ref_id == run["id"]))).all())
            assert statuses["cross_analyze"] == "queued"                 # a fresh job is left alone


async def test_registers_only_the_right_people_edit(assessment):
    from app.models import ActionItem

    admin, me = await signup()
    member, member_user = await add_member(admin)
    async with aclosing(admin), aclosing(member):
        async with session_for(me["tenant"]["id"]) as db:
            item = ActionItem(title="Turn on MFA", description="For admins", priority="high", status="open", origin="manual")
            db.add(item)
            await db.commit()
            item_id = str(item.id)
        edit = {"title": "Turn on MFA", "description": "For admins", "priority": "high", "status": "done", "owner_id": None, "due_date": None}
        assert (await member.put(f"/action-items/{item_id}", json=edit)).status_code == 403
        owned = await admin.put(f"/action-items/{item_id}", json={**edit, "status": "open", "owner_id": member_user["id"]})
        assert owned.status_code == 200
        assert (await member.put(f"/action-items/{item_id}", json={**edit, "owner_id": member_user["id"]})).status_code == 200  # now the owner
        hidden = await admin.put(f"/action-items/{item_id}", json={**edit, "status": "suggested"})
        assert hidden.status_code == 422  # can't be pushed back out of the register
