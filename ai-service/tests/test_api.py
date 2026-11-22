"""The HTTP API with the model provider replaced: auth, responses, error mapping, the guide stream."""

import json

from ai_contracts import DomainQuestion, ErrorEvent, FinalEvent, TextEvent, Usage
from fastapi.testclient import TestClient
import pytest

from app import guide, main, provider, tasks

AUTH = {"Authorization": "Bearer test-token"}
USAGE = Usage(model="claude-sonnet-5-5", input_tokens=10, output_tokens=5, cost_usd=0.001)
DOMAIN = {"name": "Identity", "controls": [{"context": {"label": "IAM02"}, "requirements": [{"key": "R1", "statement": "Reviewed."}]}]}


@pytest.fixture
def client():
    return TestClient(main.app)


def test_health_needs_no_token_and_reports_a_missing_key(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    response = client.get("/health")
    assert response.status_code == 503 and response.json()["checks"]["provider_key"] == "missing"


def test_tasks_need_the_service_token(client):
    assert client.post("/v1/questions/generate", json={"domain": DOMAIN}).status_code == 401
    wrong = client.post("/v1/questions/generate", json={"domain": DOMAIN}, headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "unauthorized"


def test_a_task_returns_the_output_and_what_it_used(client, monkeypatch):
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return DomainQuestion(text="How do you manage access?", help_text="- Access"), USAGE

    monkeypatch.setattr(provider, "structured", fake)
    response = client.post("/v1/questions/generate", json={"domain": DOMAIN}, headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"output": {"text": "How do you manage access?", "help_text": "- Access"}, "usage": USAGE.model_dump()}
    assert seen["system"] == tasks.GEN_SYSTEM and "Domain: Identity" in seen["content"] and "- R1: Reviewed." in seen["content"]
    assert response.headers["x-request-id"]


def test_a_refusal_is_reported_with_its_usage(client, monkeypatch):
    async def refuse(**kwargs):
        raise provider.AIFailure("refusal", "The AI declined to process this request", 422, USAGE)

    monkeypatch.setattr(provider, "structured", refuse)
    response = client.post("/v1/questions/generate", json={"domain": DOMAIN}, headers=AUTH)
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "refusal", "message": "The AI declined to process this request"}, "usage": USAGE.model_dump()}


def test_without_a_provider_key_tasks_answer_503(client):
    response = client.post("/v1/questions/generate", json={"domain": DOMAIN}, headers=AUTH)
    assert response.status_code == 503 and response.json()["error"]["code"] == "unavailable"


def test_invalid_input_is_a_422_with_a_readable_message(client):
    response = client.post("/v1/questions/generate", json={"domain": {"name": "x"}}, headers=AUTH)
    assert response.status_code == 422 and response.json()["error"]["code"] == "bad_request"
    assert "controls" in response.json()["error"]["message"]


def test_guide_system_is_built_without_a_model_call(client):
    response = client.post("/v1/guide/system", headers=AUTH, json={
        "company": {"name": "Acme"}, "domain_name": "Identity", "domains": [DOMAIN]})
    assert response.status_code == 200 and "Company: Acme" in response.json()["system"]


def test_guide_step_streams_events(client, monkeypatch):
    async def fake_step(body):
        yield TextEvent(delta="Thanks. ")
        yield FinalEvent(messages=[{"role": "user", "content": []}, {"role": "assistant", "content": []}], text=["Thanks."],
                         stop_reason="end_turn", tool_calls=[], usage=USAGE)

    monkeypatch.setattr(guide, "step", fake_step)
    response = client.post("/v1/guide/step", headers=AUTH, json={
        "system": "s", "transcript": [], "user_turn": {"context": {"question": None}, "text": "hi"}})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [e["type"] for e in events] == ["text", "final"] and events[1]["usage"]["cost_usd"] == 0.001


async def test_guide_step_without_input_is_an_error_event():
    from ai_contracts import GuideStepIn

    events = [e async for e in guide.step(GuideStepIn(system="s", transcript=[]))]
    assert len(events) == 1 and isinstance(events[0], ErrorEvent) and events[0].code == "bad_request"


def test_cost_is_estimated_from_list_prices():
    class Raw:
        input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 1_000_000, 100_000, 0, 0

    usage = provider.usage_of("claude-sonnet-5-5", Raw)
    assert usage.cost_usd == 3.0 and usage.model == "claude-sonnet-5-5"
