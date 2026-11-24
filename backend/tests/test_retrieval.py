import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.retrieval import PolicyRetriever, model_identity, sentence_encoder
from app.workflow import POLICIES


def test_keyword_retrieval_uses_versioned_chunks():
    retriever = PolicyRetriever(POLICIES)
    matches = retriever.search("refund deadline delivery")
    assert matches[0].chunk_id == "refund-v2#1"
    assert matches[0].keyword and not matches[0].semantic
    assert "7 days" in matches[0].excerpt
    assert retriever.search("original payment")[0].chunk_id == "payment-v1#1"
    assert retriever.search("ticket reference")[0].chunk_id == "payment-v1#2"
    assert retriever.search("zzzzzzzzzzz") == []


def test_chroma_rank_fusion_and_index_reuse(tmp_path):
    # Test the real Chroma index with small controlled vectors to isolate
    # storage and ranking behavior from model quality.
    embedded_batches = []

    def embed(texts):
        embedded_batches.append(texts)
        return [
            [1.0, 0.0] if "Refund eligibility" in text or text == "reimbursement deadline"
            else [0.0, 1.0] for text in texts
        ]

    kwargs = {"path": tmp_path / "index", "embed": embed, "embedding_id": "fixture-v1"}
    retriever = PolicyRetriever(POLICIES, **kwargs)
    matches = retriever.search("reimbursement deadline")
    assert {match.policy_id for match in matches} == {"refund-v2"}
    assert all(match.semantic and not match.keyword for match in matches)
    rebuilt = PolicyRetriever(POLICIES, **kwargs)
    assert rebuilt.search("reimbursement deadline") == matches
    assert sum(len(batch) > 1 for batch in embedded_batches) == 1


def test_report_retains_citations_and_three_related_runs():
    with TestClient(create_app()) as client:
        runs = [
            client.post("/api/runs", json={"case_id": "hallucinated"}).json()["id"]
            for _ in range(5)
        ]
        report = client.get(f"/api/runs/{runs[-1]}/investigation").json()
        assert report["retrieval_mode"] == "keyword"
        assert report["matches"][0]["chunk_id"] == "refund-v2#1"
        assert report["findings"][0]["source_ids"] == ["refund-v2"]
        assert [item["id"] for item in report["related_runs"]] == runs[-4:-1][::-1]
        assert client.get("/api/policies/search", params={"q": "tracking shipment"}).json()[0][
            "policy_id"
        ] == "shipping-v1"
        assert client.get("/api/policies/search", params={"q": "z" * 301}).status_code == 422


@pytest.mark.skipif(not os.getenv("ERROR_DODGE_EMBEDDING_PATH"), reason="Local embedding model not configured")
def test_real_model_retrieves_paraphrases(tmp_path):
    model = Path(os.environ["ERROR_DODGE_EMBEDDING_PATH"])
    retriever = PolicyRetriever(
        POLICIES, path=tmp_path / "real", embed=sentence_encoder(str(model)), embedding_id=model_identity(model),
    )
    # Verify that a refund paraphrase with no shared terms is a genuine
    # semantic gain in this corpus, not a hit produced by the keyword branch.
    refund_query = "How long until I can no longer get my money back?"
    assert PolicyRetriever(POLICIES).search(refund_query) == []
    for query, policy_id in [
        (refund_query, "refund-v2"),
        ("How do I find where my package is?", "shipping-v1"),
        ("Which mailing sticker should I put on the box?", "returns-v1"),
    ]:
        matches = retriever.search(query)
        assert matches and matches[0].policy_id == policy_id, (query, matches)
        assert matches[0].semantic

    assert retriever.search("What is the orbital period of Neptune?") == []
    assert retriever.search("How do I make blueberry muffins?") == []
