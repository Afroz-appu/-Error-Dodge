import logging
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.access import AccessConfig
from app.context_v4 import VERSION, detect_v4
from app.main import create_app
from app.runtime_config import secret_setting
from app.schema import LookupArgs, ToolCall
from app.workflow import REFUND


def test_file_settings_are_bounded_and_exclusive(tmp_path, monkeypatch):
    secret = tmp_path / "test-token"
    secret.write_text("fixture-value\n", encoding="utf-8")
    monkeypatch.setenv("TEST_SETTING_FILE", str(secret))
    assert secret_setting("TEST_SETTING") == "fixture-value"
    monkeypatch.setenv("TEST_SETTING", "other")
    with pytest.raises(ValueError, match="either"):
        secret_setting("TEST_SETTING")
    monkeypatch.delenv("TEST_SETTING")
    secret.write_text("x" * 4097, encoding="utf-8")
    with pytest.raises(ValueError, match="size"):
        secret_setting("TEST_SETTING")


def test_protected_routes_reject_invalid_and_oversized_requests():
    config = AccessConfig({"reviewer": "fixture-only-reviewer"})
    headers = {"Authorization": "Bearer fixture-only-reviewer"}
    assert "fixture-only-reviewer" not in repr(config)
    with TestClient(create_app(access=config)) as client:
        assert client.get("/api/runs").status_code == 401
        assert client.post("/api/new-write", headers=headers).status_code == 403
        assert client.post("/api/runs", headers=headers, json={"case_id": "x" * 20_000}).status_code == 413
        assert client.post("/api/runs", headers=headers, json={"case_id": "x" * 100}).status_code == 422
        malformed = {**headers, "Content-Type": "application/json"}
        assert client.post("/api/runs", headers=malformed, content=b"{").status_code == 422
        assert client.post("/api/runs", headers=headers, json={"case_id": "successful"}).status_code == 201


def test_review_audit_contains_role_and_outcome_without_credentials(caplog):
    headers = {"Authorization": "Bearer fixture-only-review-secret"}
    app = create_app(access=AccessConfig({"reviewer": headers["Authorization"].split()[1]}))
    with TestClient(app) as client, caplog.at_level(logging.INFO, logger="app.main"):
        run = client.post("/api/runs", headers=headers, json={"case_id": "hallucinated"}).json()
        path = f'/api/runs/{run["id"]}/review'
        response = client.post(path, headers=headers, json={"outcome": "approved"})
        assert response.status_code == 200
        assert response.json()["decision"]["actor_role"] == "reviewer"
        assert f"review_recorded run_id={run['id']} actor_role=reviewer outcome=approved" in caplog.text
        assert "fixture-only-review-secret" not in caplog.text


@pytest.mark.parametrize("answer, expected", [
    ("The window is seven days from the invoice date.", True),
    ("Ask for a refund one week after your card was charged.", True),
    ("Request it within a week from when your item arrived. Keep your invoice.", False),
    ("You have 7 days from delivery to request a refund. Keep the invoice.", False),
])
def test_v4_treats_billing_and_delivery_as_different_events(answer, expected):
    calls = [ToolCall(id="lookup", tool="lookup_policy", arguments=LookupArgs(topic="refund"), output=REFUND)]
    assert ("policy_conflict" in {finding.code for finding in detect_v4(answer, calls)}) == expected


def concurrent_decisions(clients, run_path):
    barrier = Barrier(2, timeout=5)

    def decide(client, outcome):
        barrier.wait()
        return client.post(run_path, json={"outcome": outcome})

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(decide, client, outcome)
                    for client, outcome in zip(clients, ("approved", "rejected"), strict=True)]
        responses = [attempt.result(timeout=15) for attempt in attempts]
    assert sorted(response.status_code for response in responses) == [200, 409]
    accepted = next(response for response in responses if response.status_code == 200).json()["decision"]
    assert clients[0].get(run_path).json()["decision"] == accepted


def test_concurrent_local_reviews_accept_one_decision():
    with TestClient(create_app(detector=VERSION)) as client:
        run = client.post("/api/runs", json={"case_id": "hallucinated"}).json()
        assert run["detector"] == VERSION
        concurrent_decisions([client, client], f'/api/runs/{run["id"]}/review')


@pytest.mark.skipif(not os.getenv("ERROR_DODGE_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL not configured")
def test_concurrent_postgres_reviews_accept_one_across_app_instances():
    url = os.environ["ERROR_DODGE_TEST_POSTGRES_URL"]
    with TestClient(create_app(database_url=url)) as first, TestClient(create_app(database_url=url)) as second:
        run = first.post("/api/runs", json={"case_id": "hallucinated"}).json()
        path = f'/api/runs/{run["id"]}/review'
        concurrent_decisions([first, second], path)
        assert second.get(f"/api/evaluations/{uuid4()}").status_code == 404
