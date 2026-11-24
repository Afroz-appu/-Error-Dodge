from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.reliability import VERSION, detect_contextual, review_evidence
from app.schema import EvidenceMatch, Finding, Investigation, LookupArgs, ToolCall
from app.workflow import CASES, POLICIES, REFUND, make_run


def call(policy=REFUND):
    return ToolCall(id="lookup-1", tool="lookup_policy", arguments=LookupArgs(topic="refund"), output=policy)


def test_clauses_distinguish_uncertain_negated_and_affirmative_claims():
    assert detect_contextual("You have a seven day refund window.", [call()]) == []
    assert detect_contextual("You have 7 days from delivery. Approval is not guaranteed.", [call()]) == []
    findings = detect_contextual("If you file within 7 days from delivery, it will be approved.", [call()])
    assert [finding.code for finding in findings] == ["unsupported_claim"]
    findings = detect_contextual("You have ten days counted from payment.", [call()])
    assert [finding.code for finding in findings] == ["policy_conflict"]
    findings = detect_contextual("Tracking takes 12 days. I cannot confirm the refund deadline.", [call()])
    assert [finding.code for finding in findings] == ["incomplete_answer"]


def test_evidence_integrity_and_exact_finding_binding():
    archived = REFUND.model_copy(update={"id": "refund-v1", "version": "1.0"})
    spoof = REFUND.model_copy(update={"text": "Refund requests remain open indefinitely."})
    foreign = REFUND.model_copy(update={"id": "outside-document"})
    for policy, code in [(archived, "stale_evidence"), (spoof, "untrusted_evidence"), (foreign, "untrusted_evidence")]:
        calls = [call(policy)]
        answer = "Refund requests must be made within 4 weeks of delivery."
        findings = detect_contextual(answer, calls)
        assert code in {item.code for item in findings}
        run = make_run(CASES["hallucinated"], answer, calls, uuid4(), "deterministic")
        bogus = Finding(code="policy_conflict", detail="A $20 credit is available.", source_ids=[REFUND.id])
        report = Investigation(
            findings=[*findings, bogus], evidence=[*POLICIES, archived, spoof, foreign],
            matches=[EvidenceMatch(chunk_id="refund-v2#1", policy_id=REFUND.id, excerpt=spoof.text,
                                   keyword=True, semantic=True)],
            hypothesis="Unknown", recommendation="Verify sources",
        )
        checked = review_evidence(run, report)
        assert checked.evidence == POLICIES
        assert checked.matches == []
        assert checked.evidence_warning
        assert checked.support[-1].status == "insufficient"
        assert not checked.findings[-1].source_ids
        supported = next(item for item in checked.support if item.status == "policy_supported")
        assert supported.quote in REFUND.text


def test_contextual_detector_is_independently_selectable():
    with TestClient(create_app(detector=VERSION)) as client:
        response = client.post("/api/runs", json={"case_id": "hallucinated"})
        assert response.status_code == 201
        run = response.json()
        assert run["detector"] == VERSION
        report = client.get(f'/api/runs/{run["id"]}/investigation').json()
        assert report["support"][0]["status"] == "policy_supported"
        assert report["support"][0]["quote"].startswith("Customers have 7 days")
