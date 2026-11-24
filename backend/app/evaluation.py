"""Run and persist a versioned, deterministic benchmark without applying proposals."""
import hashlib
import json
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from time import perf_counter
from uuid import UUID, uuid4

from pydantic import BaseModel
from sklearn.metrics import precision_recall_fscore_support

from .retrieval import PolicyRetriever
from .schema import ToolCall
from .workflow import CASES, DATA, DAYS, POLICIES, REFUND, candidate_result, detect, execute, score

CORPUS = "error-dodge-synthetic-v1"
RETRIEVAL_FILE = DATA / "retrieval_eval_v1.json"


class RetrievalFixture(BaseModel):
    id: str
    query: str
    expected_chunk: str | None


class Variant(BaseModel):
    answer: str
    task_pass: bool
    grounded_answer: bool
    tool_correct: bool
    detected_codes: list[str]
    calls: list[ToolCall]
    elapsed_ms: float


class CaseResult(BaseModel):
    case_id: str
    expected_codes: list[str]
    baseline: Variant
    proposed: Variant


class VariantMetrics(BaseModel):
    task_passes: int
    grounded_answers: int
    correct_tool_traces: int


class DetectionMetrics(BaseModel):
    precision: float
    recall: float
    f1: float
    false_positives: list[str]
    false_negatives: list[str]
    unexpected_codes: list[str]
    missed_codes: list[str]


class RetrievalResult(BaseModel):
    fixture_id: str
    query: str
    expected_chunk: str | None
    keyword: list[str]
    active: list[str]


class RetrievalMetrics(BaseModel):
    answerable: int
    unrelated: int
    keyword_top1: int
    active_top1: int
    keyword_top3: int
    active_top3: int
    keyword_abstentions: int
    active_abstentions: int


class EvaluationResult(BaseModel):
    retrieval_metrics: RetrievalMetrics
    id: UUID
    created_at: datetime
    dataset: str
    dataset_sha256: str
    controls: list[str]
    retrieval_mode: str
    retrieval_index: str | None
    elapsed_ms: float
    baseline: VariantMetrics
    proposed: VariantMetrics
    detection: DetectionMetrics
    regressions: list[str]
    cases: list[CaseResult]
    retrieval: list[RetrievalResult]


def measured_variant(execute_variant: Callable[[], tuple[str, list[ToolCall]]]) -> Variant:
    start = perf_counter()
    answer, calls = execute_variant()
    found = detect(answer, calls)
    # This is an explicit refund-task rubric. Abstentions do not count as a
    # supported answer, and matching the number requires retrieved evidence.
    canonical_days = DAYS.findall(REFUND.text)
    grounded = (
        bool(canonical_days)
        and DAYS.findall(answer) == canonical_days
        and "refunds are guaranteed" not in answer.lower()
        and any(call.output == REFUND and not call.error for call in calls)
    )
    relevant = [call for call in calls if call.output == REFUND and not call.error]
    correct_tool = (
        len(relevant) == 1
        and all(call.tool == "lookup_policy" and call.arguments.topic == "refund"
                and (call.output == REFUND or call.error is not None) for call in calls)
    )
    return Variant(
        answer=answer, task_pass=score(answer, calls), grounded_answer=grounded,
        tool_correct=correct_tool, detected_codes=[finding.code for finding in found],
        calls=calls, elapsed_ms=round((perf_counter() - start) * 1000, 3),
    )


def aggregate(variants: list[Variant]) -> VariantMetrics:
    return VariantMetrics(
        task_passes=sum(row.task_pass for row in variants),
        grounded_answers=sum(row.grounded_answer for row in variants),
        correct_tool_traces=sum(row.tool_correct for row in variants),
    )


def evaluate_suite(retriever: PolicyRetriever, controls: list[str]) -> EvaluationResult:
    start = perf_counter()
    cases = []
    config = set(controls)
    for case in CASES.values():
        before = measured_variant(lambda: execute(case))
        after = measured_variant(lambda: candidate_result(case, config))
        cases.append(CaseResult(case_id=case.id, expected_codes=case.expected_codes,
                                baseline=before, proposed=after))

    # Detection labels describe baseline faults. Reusing them as labels for
    # a patched variant would count repaired failures as missed detections.
    expected = [bool(row.expected_codes) for row in cases]
    detected = [bool(row.baseline.detected_codes) for row in cases]
    precision, recall, f1, _ = precision_recall_fscore_support(
        expected, detected, average="binary", zero_division=0,
    )
    false_positives, false_negatives, unexpected_codes, missed_codes = [], [], [], []
    for row, target, observation in zip(cases, expected, detected, strict=True):
        if observation and not target:
            false_positives.append(row.case_id)
        if target and not observation:
            false_negatives.append(row.case_id)
        wanted, observed = set(row.expected_codes), set(row.baseline.detected_codes)
        unexpected_codes.extend(f"{row.case_id}/{code}" for code in sorted(observed - wanted))
        missed_codes.extend(f"{row.case_id}/{code}" for code in sorted(wanted - observed))

    fixtures = [RetrievalFixture.model_validate(item) for item in json.loads(
        RETRIEVAL_FILE.read_text(encoding="utf-8-sig")
    )]
    keyword_retriever = PolicyRetriever(POLICIES)
    retrieval_rows = [
        RetrievalResult(
            fixture_id=item.id, query=item.query, expected_chunk=item.expected_chunk,
            keyword=[match.chunk_id for match in keyword_retriever.search(item.query)],
            active=[match.chunk_id for match in retriever.search(item.query)],
        )
        for item in fixtures
    ]
    # Hash the actual fixtures so a saved run identifies both datasets and the corpus.
    digest = hashlib.sha256(b"\0".join(
        (DATA / name).read_bytes() for name in ("cases.json", "policies.json", RETRIEVAL_FILE.name)
    )).hexdigest()
    return EvaluationResult(
        id=uuid4(), created_at=datetime.now(UTC), dataset=CORPUS, dataset_sha256=digest,
        controls=controls, retrieval_mode=retriever.mode,
        retrieval_index=retriever.collection.name if retriever.collection is not None else None,
        elapsed_ms=round((perf_counter() - start) * 1000, 3),
        baseline=aggregate([row.baseline for row in cases]),
        proposed=aggregate([row.proposed for row in cases]),
        detection=DetectionMetrics(
            precision=precision, recall=recall, f1=f1,
            false_positives=false_positives, false_negatives=false_negatives,
            unexpected_codes=unexpected_codes, missed_codes=missed_codes,
        ),
        regressions=[row.case_id for row in cases if row.baseline.task_pass and not row.proposed.task_pass],
        cases=cases, retrieval=retrieval_rows,
        retrieval_metrics=RetrievalMetrics(
            answerable=sum(row.expected_chunk is not None for row in retrieval_rows),
            unrelated=sum(row.expected_chunk is None for row in retrieval_rows),
            keyword_top1=sum(row.expected_chunk in row.keyword[:1] for row in retrieval_rows),
            active_top1=sum(row.expected_chunk in row.active[:1] for row in retrieval_rows),
            keyword_top3=sum(row.expected_chunk in row.keyword for row in retrieval_rows),
            active_top3=sum(row.expected_chunk in row.active for row in retrieval_rows),
            keyword_abstentions=sum(row.expected_chunk is None and not row.keyword for row in retrieval_rows),
            active_abstentions=sum(row.expected_chunk is None and not row.active for row in retrieval_rows),
        ),
    )


class EvaluationStore:
    def __init__(self, database: Connection):
        self.database = database
        with database:
            database.execute("""
                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, result TEXT NOT NULL
                )
            """)

    def save(self, result: EvaluationResult) -> None:
        with self.database:
            self.database.execute(
                "INSERT INTO evaluation_runs VALUES (?, ?, ?)",
                (str(result.id), result.created_at.isoformat(), result.model_dump_json()),
            )

    def list(self) -> list[EvaluationResult]:
        with closing(self.database.execute(
            "SELECT result FROM evaluation_runs ORDER BY created_at DESC, id DESC LIMIT 20"
        )) as cursor:
            return [EvaluationResult.model_validate_json(row[0]) for row in cursor]

    def get(self, evaluation_id: UUID) -> EvaluationResult | None:
        with closing(self.database.execute(
            "SELECT result FROM evaluation_runs WHERE id = ?", (str(evaluation_id),)
        )) as cursor:
            row = cursor.fetchone()
        return EvaluationResult.model_validate_json(row[0]) if row else None
