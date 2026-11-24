from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Policy(BaseModel):
    id: str
    title: str
    version: str
    topic: str
    text: str


class Case(BaseModel):
    id: str
    name: str
    question: str
    fault: str
    expected_codes: list[str]


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1, max_length=64)
    provider: Literal["deterministic", "gemini"] = "deterministic"


class LookupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Literal["refund", "shipping", "returns"]


class ToolCall(BaseModel):
    id: str
    tool: str
    arguments: LookupArgs
    output: Policy | None = None
    error: str | None = None


class Finding(BaseModel):
    code: str
    detail: str
    trace_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class EvidenceMatch(BaseModel):
    chunk_id: str
    policy_id: str
    excerpt: str
    keyword: bool
    semantic: bool


class RelatedRun(BaseModel):
    id: UUID
    status: Literal["no_issue_detected", "flagged"]


class FindingSupport(BaseModel):
    finding_index: int
    status: Literal["policy_supported", "trace_supported", "insufficient"]
    quote: str | None = None
    rationale: str


class Investigation(BaseModel):
    support: list[FindingSupport] = Field(default_factory=list)
    evidence_warning: str | None = None
    retrieval_mode: Literal["keyword", "hybrid"] | None = None
    matches: list[EvidenceMatch] = Field(default_factory=list)
    related_runs: list[RelatedRun] = Field(default_factory=list)
    findings: list[Finding]
    evidence: list[Policy]
    hypothesis: str
    recommendation: str


class Run(BaseModel):
    id: UUID
    detector: str = "phase4"
    provider: Literal["deterministic", "gemini"] = "deterministic"
    created_at: datetime
    case_id: str
    question: str
    answer: str
    calls: list[ToolCall]
    status: Literal["no_issue_detected", "flagged"]
    findings: list[Finding]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["approved", "rejected"]


class RecordedDecision(Decision):
    recorded_at: datetime
    actor_role: Literal["reviewer"] | None = None


class Proposal(BaseModel):
    recommendation: str
    controls: list[str]


class Evaluation(BaseModel):
    dataset: str
    cases: int
    baseline_passes: int
    proposed_passes: int
    regressions: list[str]


class Review(BaseModel):
    proposal: Proposal
    evaluation: Evaluation
    decision: RecordedDecision | None = None
