from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import gemini
from app.graph import config
from app.main import create_app
from app.workflow import CASES, candidate_result, score


def test_graph_routes_and_resumes_review_after_restart(tmp_path):
    database = tmp_path / "checkpoints.sqlite3"
    app = create_app(database)
    with TestClient(app) as client:
        clean = client.post("/api/runs", json={"case_id": "successful"}).json()
        assert app.state.graph.get_state(config(clean["id"])).next == ()
        assert client.get(f'/api/runs/{clean["id"]}/review').status_code == 404

        flagged = client.post("/api/runs", json={"case_id": "hallucinated"}).json()
        path = f'/api/runs/{flagged["id"]}'
        assert app.state.graph.get_state(config(flagged["id"])).next == ("review",)
        review = client.get(f"{path}/review").json()
        assert review["proposal"]["controls"] == ["ground_answer"]
        assert review["evaluation"] == {
            "dataset": "synthetic-refund-v1", "cases": 10, "baseline_passes": 1,
            "proposed_passes": 4, "regressions": [],
        }
        assert review["decision"] is None

    restarted = create_app(database)
    with TestClient(restarted) as client:
        assert client.get("/api/runs").json() == [flagged, clean]
        assert client.get(f"{path}/investigation").json()["evidence"][0]["id"] == "refund-v2"
        decision = client.post(f"{path}/review", json={"outcome": "approved"})
        assert decision.status_code == 200
        assert decision.json()["decision"]["outcome"] == "approved"
        assert client.post(f"{path}/review", json={"outcome": "rejected"}).status_code == 409
        assert restarted.state.graph.get_state(config(flagged["id"])).next == ()
        again = client.post("/api/runs", json={"case_id": "hallucinated"}).json()
        assert "30 days" in again["answer"]

    with TestClient(create_app(database)) as client:
        assert client.get(f"{path}/review").json()["decision"] == decision.json()["decision"]


def test_timeout_candidate_retries_once():
    answer, calls = candidate_result(CASES["tool-error"], {"retry_lookup"})
    assert len(calls) == 2
    assert calls[0].error
    assert calls[1].error is None
    assert score(answer, calls)


def test_gemini_requires_configuration(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/api/capabilities").json() == {"gemini_configured": False}
        response = client.post("/api/runs", json={"case_id": "successful", "provider": "gemini"})
        assert response.status_code == 503


@pytest.mark.parametrize("topic", ["refund", "shell"])
def test_gemini_tool_contract_with_mocked_provider(monkeypatch, topic):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = SimpleNamespace(
                get=lambda **kwargs: SimpleNamespace(supported_actions=["generateContent"])
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeModel:
        def __init__(self, **kwargs):
            pass

        def bind_tools(self, tools, tool_choice):
            assert tool_choice == tools[0].name == "lookup_policy"
            return SimpleNamespace(invoke=lambda messages: AIMessage(content="", tool_calls=[
                {"name": "lookup_policy", "id": "test-call", "args": {"topic": topic}}
            ]))

        def with_structured_output(self, schema, method):
            assert topic == "refund"
            assert method == "json_schema"

            def respond(messages):
                assert messages[-1].tool_call_id == "test-call"
                assert "refund-v2" in messages[-1].content
                return schema(answer="You have 7 days to request a refund.")

            return SimpleNamespace(invoke=respond)

    monkeypatch.setattr(gemini.genai, "Client", FakeClient)
    monkeypatch.setattr(gemini, "ChatGoogleGenerativeAI", FakeModel)
    with TestClient(create_app()) as client:
        response = client.post("/api/runs", json={"case_id": "successful", "provider": "gemini"})
        if topic == "refund":
            assert response.status_code == 201
            assert response.json()["provider"] == "gemini"
            assert response.json()["calls"][0]["output"]["id"] == "refund-v2"
        else:
            assert response.status_code == 502
            assert client.get("/api/runs").json() == []
