from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app


def test_benchmark_computes_and_persists_results(tmp_path):
    checkpoint = tmp_path / "checkpoints.sqlite3"
    with TestClient(create_app(checkpoint)) as client:
        assert client.get("/api/evaluations").json() == []
        response = client.post("/api/evaluations")
        assert response.status_code == 201
        result = response.json()
        assert result["controls"] == ["ground_answer"]
        assert len(result["dataset_sha256"]) == 64
        assert len(result["cases"]) == 10
        assert len(result["retrieval"]) == 13
        assert result["baseline"]["task_passes"] == 1
        assert result["proposed"]["task_passes"] == 4
        assert result["baseline"]["grounded_answers"] == 2
        assert result["proposed"]["grounded_answers"] == 5
        assert result["baseline"]["correct_tool_traces"] == result["proposed"]["correct_tool_traces"] == 4
        assert result["detection"]["precision"] == result["detection"]["recall"] == 1
        assert result["detection"]["false_positives"] == []
        assert result["detection"]["false_negatives"] == []
        wrong = next(case for case in result["cases"] if case["case_id"] == "hallucinated")
        assert wrong["baseline"]["calls"][0]["output"]["id"] == "refund-v2"
        assert wrong["baseline"]["detected_codes"] == wrong["expected_codes"]
        assert wrong["proposed"]["task_pass"] and not wrong["baseline"]["task_pass"]
        assert result["regressions"] == []
        metrics = result["retrieval_metrics"]
        assert metrics["answerable"] == 10 and metrics["unrelated"] == 3
        assert metrics["keyword_top1"] == metrics["active_top1"]
        assert metrics["keyword_abstentions"] == metrics["active_abstentions"]
        assert client.get("/api/runs").json() == []

    with TestClient(create_app(checkpoint)) as restarted:
        assert restarted.get("/api/evaluations").json() == [result]
        assert restarted.get(f'/api/evaluations/{result["id"]}').json() == result
        assert restarted.get(f"/api/evaluations/{uuid4()}").status_code == 404


def test_benchmark_uses_incident_controls_without_recording_a_decision():
    with TestClient(create_app()) as client:
        incident = client.post("/api/runs", json={"case_id": "tool-error"}).json()
        review_path = f'/api/runs/{incident["id"]}/review'
        controls = client.get(review_path).json()["proposal"]["controls"]
        response = client.post("/api/evaluations", params={"run_id": incident["id"]})
        assert response.status_code == 201
        result = response.json()
        assert result["controls"] == controls
        timeout = next(case for case in result["cases"] if case["case_id"] == "tool-error")
        assert len(timeout["proposed"]["calls"]) == 2
        assert timeout["proposed"]["task_pass"]
        assert client.get(review_path).json()["decision"] is None
        assert client.post("/api/evaluations", params={"run_id": "invalid"}).status_code == 422
        assert client.post("/api/evaluations", params={"run_id": str(uuid4())}).status_code == 404
