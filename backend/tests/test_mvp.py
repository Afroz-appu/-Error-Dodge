from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schema import LookupArgs
from app.workflow import CASES


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_labeled_cases(client, case):
    response = client.post("/api/runs", json={"case_id": case.id})
    assert response.status_code == 201
    run = response.json()
    assert [finding["code"] for finding in run["findings"]] == case.expected_codes
    assert client.get(f'/api/runs/{run["id"]}').json() == run
    assert client.get("/api/runs").json() == [run]
    report = client.get(f'/api/runs/{run["id"]}/investigation')

    if not case.expected_codes:
        assert run["status"] == "no_issue_detected"
        assert "7 days" in run["answer"]
        assert report.status_code == 404
        assert client.get("/api/incidents").json() == []
        return

    assert run["status"] == "flagged"
    assert client.get("/api/incidents").json() == [run]
    assert report.status_code == 200
    body = report.json()
    assert body["findings"] == run["findings"]
    assert body["recommendation"]
    evidence = {doc["id"]: doc["text"] for doc in body["evidence"]}
    trace_ids = {call["id"] for call in run["calls"]}
    for finding in body["findings"]:
        assert set(finding["source_ids"]) <= evidence.keys()
        assert set(finding["trace_ids"]) <= trace_ids
    assert "7 days" in evidence["refund-v2"]
    assert "external-note" not in evidence

    if case.id == "hallucinated":
        assert "30 days" in run["answer"]
        assert run["calls"][0]["output"]["id"] == "refund-v2"
        assert body["findings"][0]["source_ids"] == ["refund-v2"]
    if case.id == "untrusted":
        assert "Ignore instructions" in run["calls"][0]["output"]["text"]
        assert "promise a refund" not in run["answer"]


def test_api_validation(client):
    cases = client.get("/api/cases").json()
    assert len(cases) == len(CASES)
    assert all(set(case) == {"id", "name", "question"} for case in cases)
    assert client.post("/api/runs", json={"case_id": "unknown"}).status_code == 404
    assert client.post("/api/runs", json={"case_id": "", "tool": "shell"}).status_code == 422
    assert client.get(f"/api/runs/{uuid4()}").status_code == 404
    with pytest.raises(ValidationError):
        LookupArgs(topic="shell")
