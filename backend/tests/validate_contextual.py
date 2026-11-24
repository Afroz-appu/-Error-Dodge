"""Evaluate the frozen candidate on new and historical traces without retuning."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from app.guarded import ABSTAIN, guarded_refund, monitor_refund
from app.reliability import detect_contextual, review_evidence
from app.retrieval import PolicyRetriever, model_identity, sentence_encoder
from app.schema import Case
from app.workflow import POLICIES, REFUND, detect, investigate, make_run, score
from run_heldout import detector_scores, fixture_calls, latency, service, timed

ROOT = Path(__file__).parent
DETECTOR_HASH = "e248f9e18b8931d4cbe01ee1657f3d41ab79171f2dd65725ed0d7a89c6692052"
SUITES = {
    "new": ("contextual_freeze_v1.json", "3100485fa1aed103d309538fd86c4b464e2f702d5bd71830be9916661dbce980"),
    "prior_20": ("heldout_refund_v1.json", "dfcf6bb6807fdfed440bb46cbca2a24ffae3da44e6103501153136bc3d87b2ec"),
    "prior_8": ("post_freeze_refund_v1.json", "17eccaec03b1b66f47495ab090b9b99adcd95bc235cd4ec6b30177595d44f79a"),
}
DETECTORS = {"phase4": detect, "guarded_v2": monitor_refund, "context_v3": detect_contextual}


def checked_bytes(path, digest):
    raw = path.read_bytes()
    if digest not in {hashlib.sha256(raw).hexdigest(),
                      hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()}:
        raise ValueError(f"Unexpected SHA-256 for {path}")
    return raw


def run_suite(fixtures, retriever):
    rows = []
    for fixture in fixtures:
        trace = fixture_calls(fixture["trace"])
        row = dict(fixture, audit={}, timings_ms={})
        (answer, calls), elapsed = timed(lambda: guarded_refund(service(fixture["service"])))
        row["guarded_execution_ms"] = elapsed
        row["guarded_completed"] = score(answer, calls)
        row["guarded_tool_correct"] = score(answer, calls)
        row["guarded_faithful"] = row["guarded_completed"] or (
            answer == ABSTAIN and bool(calls) and all(call.error for call in calls)
        )
        row["guarded_answer"] = answer
        row["guarded_calls"] = [call.model_dump(mode="json") for call in calls]
        for label, detector in DETECTORS.items():
            findings, duration = timed(lambda: detector(fixture["answer"], trace))
            row[label] = sorted({finding.code for finding in findings})
            row["timings_ms"][label] = duration
            if not findings:
                continue
            case = Case(id=fixture["id"], name=fixture["id"], question=fixture["question"],
                        fault="none", expected_codes=[])
            run = make_run(case, fixture["answer"], trace, uuid4(), "deterministic").model_copy(
                update={"findings": findings, "status": "flagged"}
            )
            report = investigate(run, retriever, [])
            if label == "context_v3":
                report = review_evidence(run, report)
            source_docs = {policy.id: policy for policy in POLICIES}
            assert all(source_docs[policy.id] == policy for policy in report.evidence)
            assert all(hit.excerpt in source_docs[hit.policy_id].text for hit in report.matches)
            for support in report.support:
                if support.quote:
                    assert support.quote in REFUND.text
            citations = [finding for finding in report.findings if finding.source_ids]
            source_ids = {source.id for source in report.evidence}
            assert all(set(finding.source_ids) <= source_ids for finding in citations)
            assert all(set(finding.trace_ids) <= {call.id for call in trace}
                       for finding in report.findings)
            row["audit"][label] = {
                "excerpt_occurrences": len(report.matches),
                "refund_first": bool(report.matches and report.matches[0].policy_id == REFUND.id),
                "other_excerpt_occurrences": sum(hit.policy_id != REFUND.id for hit in report.matches),
                "citations_resolved": len(citations),
                "citations_label_supported": sum(finding.code in fixture["expected_codes"] for finding in citations),
                "unsupported_citation_codes": [
                    finding.code for finding in citations if finding.code not in fixture["expected_codes"]
                ],
                "evidence_warning": report.evidence_warning,
                "statuses": [item.status for item in report.support],
            }
        rows.append(row)
    audit = {}
    for label in DETECTORS:
        reports = [row["audit"][label] for row in rows if label in row["audit"]]
        audit[label] = {
            "reports": len(reports),
            **{key: sum(item[key] for item in reports)
               for key in ("excerpt_occurrences", "refund_first", "other_excerpt_occurrences",
                           "citations_resolved", "citations_label_supported")},
        }
    return {
        "count": len(rows),
        "detection": {label: detector_scores(rows, label) for label in DETECTORS},
        "detection_latency": {label: latency([row["timings_ms"][label] for row in rows]) for label in DETECTORS},
        "guarded_latency": latency([row["guarded_execution_ms"] for row in rows]),
        "citation_audit": audit,
        "task": {metric: {
            "before": sum(row[metric] for row in rows),
            "after": sum(row[f"guarded_{metric}"] for row in rows),
            "regressions": [row["id"] for row in rows if row[metric] and not row[f"guarded_{metric}"]],
        } for metric in ("completed", "tool_correct", "faithful")},
        "exact_label_regressions_vs_v2": [
            row["id"] for row in rows
            if sorted(row["expected_codes"]) == row["guarded_v2"] != row["context_v3"]
        ],
        "rows": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output.resolve()
    checked_bytes(ROOT.parent / "app" / "reliability.py", DETECTOR_HASH)
    model = Path(os.environ["ERROR_DODGE_EMBEDDING_PATH"])
    retriever = PolicyRetriever(POLICIES, path=output.parent / "semantic-index",
                                embed=sentence_encoder(str(model)), embedding_id=model_identity(model))
    result = {"detector_sha256": DETECTOR_HASH, "embedding_collection": retriever.collection.name,
              "provider_calls": 0, "billable_tokens": 0, "provider_cost": 0, "suites": {}}
    for label, (name, digest) in SUITES.items():
        fixtures = json.loads(checked_bytes(ROOT / "data" / name, digest).decode("utf-8-sig"))
        result["suites"][label] = {"dataset_sha256": digest, **run_suite(fixtures, retriever)}
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
