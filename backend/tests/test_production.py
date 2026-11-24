import os

import pytest
from fastapi.testclient import TestClient

from app.access import AccessConfig
from app.main import create_app


def test_access_enforces_roles_and_audits_review():
    # Fixture credentials exist only in this in-process server.
    headers = {role: {"Authorization": f"Bearer {role}-test-fixture-token"}
               for role in ("viewer", "evaluator", "reviewer")}
    config = AccessConfig({role: value["Authorization"].split()[1] for role, value in headers.items()})
    with TestClient(create_app(access=config)) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/api/access").json() == {"authentication_required": True}
        assert client.get("/api/runs").status_code == 401
        assert client.get("/api/runs", headers={"Authorization": "Bearer bogus"}).status_code == 401
        read = client.get("/api/runs", headers=headers["viewer"])
        assert read.status_code == 200 and read.headers["Cache-Control"] == "no-store"
        assert client.get("/api/session", headers=headers["viewer"]).json() == {"role": "viewer"}
        body = {"case_id": "hallucinated"}
        assert client.post("/api/runs", json=body, headers=headers["viewer"]).status_code == 403
        assert client.post("/api/evaluations", headers=headers["viewer"]).status_code == 403
        run = client.post("/api/runs", json=body, headers=headers["evaluator"]).json()
        path = f'/api/runs/{run["id"]}/review'
        decision = {"outcome": "approved"}
        assert client.post(path, json=decision, headers=headers["evaluator"]).status_code == 403
        assert client.post(path, json={**decision, "actor_role": "reviewer"},
                           headers=headers["reviewer"]).status_code == 422
        assert client.post(path, json=decision, headers=headers["reviewer"]).json()["decision"][
            "actor_role"
        ] == "reviewer"


def test_token_mode_fails_closed_on_missing_secrets(monkeypatch):
    monkeypatch.setenv("ERROR_DODGE_ACCESS_MODE", "token")
    monkeypatch.delenv("ERROR_DODGE_REVIEWER_TOKEN", raising=False)
    with pytest.raises(ValueError, match="three distinct"):
        AccessConfig.from_env()


@pytest.mark.skipif(not os.getenv("ERROR_DODGE_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL not configured")
def test_postgres_persists_run_evaluation_and_review_across_app_restart():
    url = os.environ["ERROR_DODGE_TEST_POSTGRES_URL"]
    with TestClient(create_app(database_url=url)) as client:
        assert client.get("/health/ready").status_code == 200
        run_response = client.post("/api/runs", json={"case_id": "hallucinated"})
        assert run_response.status_code == 201
        run = run_response.json()
        run_path = f'/api/runs/{run["id"]}'
        benchmark = client.post("/api/evaluations", params={"run_id": run["id"]})
        assert benchmark.status_code == 201
        benchmark_id = benchmark.json()["id"]
    with TestClient(create_app(database_url=url)) as restarted:
        assert restarted.get(run_path).json() == run
        assert restarted.get(f"/api/evaluations/{benchmark_id}").status_code == 200
        assert restarted.get(run_path + "/review").json()["decision"] is None
        decision = restarted.post(run_path + "/review", json={"outcome": "rejected"})
        assert decision.status_code == 200
    with TestClient(create_app(database_url=url)) as restarted:
        assert restarted.get(run_path + "/review").json()["decision"]["outcome"] == "rejected"
