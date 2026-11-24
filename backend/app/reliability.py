"""Versioned refund-window detector. It reasons about explicit claims and trace provenance."""
import re
from collections import Counter

from .retrieval import policy_chunks
from .schema import Finding, FindingSupport, Investigation, LookupArgs, Run, ToolCall
from .workflow import POLICIES, REFUND

VERSION = "refund-context-v3"
ARGS = LookupArgs(topic="refund")
NUMBERS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20), strict=True,
))
TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10), strict=True))
NUMBER = rf"(?:\d+|a|an|{'|'.join(NUMBERS)}|(?:{'|'.join(TENS)})(?:[ -](?:{'|'.join(list(NUMBERS)[1:10])}))?)"
WINDOW = re.compile(rf"\b(?P<number>{NUMBER})[\s-]+(?P<unit>calendar |business |working )?(?P<period>days?|weeks?)\b", re.I)
CLAUSE = re.compile(r"(?<=[.!?;])\s+|\s+(?:but|however|whereas|although|yet)\s+", re.I)
APPROVAL = re.compile(
    r"guarantee\w*|automat\w*[^.!?;]{0,35}approv|approv\w*[^.!?;]{0,35}automat|"
    r"(?:will|shall)\s+(?:always\s+|definitely\s+)?(?:be\s+)?approv|"
    r"approv\w*\s+without\s+(?:a\s+)?review|(?:certain|assured)\s+approval|"
    r"approval\s+(?:is|will be)\s+(?:certain|assured)|(?:will|shall)\s+"
    r"(?:always\s+)?(?:get|receive)\s+(?:a\s+|your\s+)?(?:refund|money back)", re.I,
)
DENIAL = re.compile(
    r"\b(?:not|never|cannot|can't|isn't|aren't|won't|doesn't|no)\b[^.!?;]{0,40}"
    r"\b(?:guarantee\w*|approv\w*|assured|certain|refund)\b|"
    r"\b(?:may|might|could)\b[^.!?;]{0,30}\b(?:approv\w*|refund)\b", re.I,
)
ANCHOR = re.compile(
    r"\b(?:from|after|of|since|starting (?:on|at)|count(?:ed|ing)? from)\s+"
    r"(?P<event>(?:(?:the|your)\s+)?(?:purchase|order(?: date)?|payment|checkout|(?:date|time) of (?:your )?(?:payment|purchase)|"
    r"(?:day|date|moment|time)\s+(?:that\s+)?you\s+(?:paid|ordered|checked out)))\b", re.I,
)
DELIVERY = re.compile(r"\b(?:deliver\w*|receiv\w*|receipt|arriv\w*)\b", re.I)
FEE = re.compile(r"\b(?:fee|charge)\b|\$\s*\d+", re.I)
NO_FEE = re.compile(r"\b(?:no|without|never|not charged)\b[^.!?;]{0,30}\b(?:fee|charge)\b", re.I)
HYPOTHETICAL = re.compile(r"^\s*(?:if|suppose|imagine|for example|for instance)\b", re.I)
ATTRIBUTED = re.compile(r"\b(?:old|archived|outdated|previous)\s+(?:policy|guidance|document)\b", re.I)
REJECTED = re.compile(r"\b(?:wrong|incorrect|obsolete|expired|no longer|does not apply)\b", re.I)
UNCERTAIN = re.compile(r"\b(?:cannot|can't|could not|unable to|not sure)\b[^.!?;]{0,35}\b(?:verify|confirm|say|determine|know)\b", re.I)
REFUND_CONTEXT = re.compile(r"\b(?:refund|reimburs\w*|money back|window|deadline|eligib\w*)\b", re.I)
OTHER_CONTEXT = re.compile(r"\b(?:tracking|shipping|processing|refund status|transit|bank)\b", re.I)


def days_in(match: re.Match) -> int:
    number = match["number"].lower()
    if number in {"a", "an"}:
        value = 1
    elif number.isdigit():
        value = int(number)
    else:
        value = sum(NUMBERS.get(part, TENS.get(part, 0)) for part in re.split(r"[- ]", number))
    return value * (7 if match["period"].lower().startswith("week") else 1)


def detect_contextual(answer: str, calls: list[ToolCall]) -> list[Finding]:
    """Extract policy claims in their clause and distinguish missing context from conflict."""
    findings = []
    known = {policy.id: policy for policy in POLICIES}
    trusted, errors = [], []

    def flag(code, detail, trace=(), *, policy=False):
        findings.append(Finding(
            code=code, detail=detail, trace_ids=[event.id for event in trace],
            source_ids=[REFUND.id] if policy else [],
        ))

    for call in calls:
        if call.tool != "lookup_policy" or call.arguments != ARGS:
            flag("wrong_tool", "The trace shows a different operation or policy topic.", [call])
        elif call.error:
            errors.append(call)
        elif call.output == REFUND:
            trusted.append(call)
        elif call.output and call.output.id == "refund-v1":
            flag("stale_evidence", "The trace used an archived refund source.", [call])
        elif call.output:
            code = "untrusted_evidence"
            text = ("A source claimed the active policy identifier but its contents or version differed."
                    if call.output.id == REFUND.id else "The lookup did not return a trusted refund policy.")
            if known.get(call.output.id) != call.output or call.output.topic != ARGS.topic:
                flag(code, text, [call])
    recovered = len(calls) == 2 and bool(errors and trusted) and calls == [errors[0], trusted[0]]
    if errors and not recovered:
        flag("tool_error", "The lookup trace contains an unrecovered error.", errors)
    successes = Counter((call.tool, call.arguments.topic) for call in trusted)
    if any(count > 1 for count in successes.values()):
        flag("repeated_tool", "The active refund policy was retrieved repeatedly.", trusted)
    if not trusted:
        flag("missing_evidence", "The run lacks a verified active refund lookup.", calls)

    expected = days_in(WINDOW.search(REFUND.text))
    asserted, conflict, unsupported = False, False, False
    for clause in CLAUSE.split(answer):
        conditional = clause.lstrip().lower().startswith("if ") and "," in clause
        conclusion = clause.split(",", 1)[1].lstrip() if conditional else clause
        if clause.rstrip().endswith("?") or (not conditional and HYPOTHETICAL.search(clause)) or UNCERTAIN.search(conclusion):
            continue
        if ATTRIBUTED.search(clause) and REJECTED.search(clause):
            continue
        # Time spans for a bank, shipping or tracking update are separate
        # claims. Do not infer that these spans describe the refund deadline.
        scoped = bool(REFUND_CONTEXT.search(clause) or DELIVERY.search(clause)
                      or ANCHOR.search(clause) or not OTHER_CONTEXT.search(clause))
        windows = list(WINDOW.finditer(clause)) if scoped else []
        if windows:
            asserted = True
        conflict |= scoped and (
            bool(ANCHOR.search(clause))
            or any(days_in(match) != expected or (match["unit"] or "").lower() in {"business ", "working "}
                   for match in windows)
        )
        # Evaluate the polarity of each approval phrase, not the whole answer.
        for promise in APPROVAL.finditer(conclusion):
            preceding = conclusion[max(0, promise.start() - 42):promise.end()]
            if not DENIAL.search(preceding):
                unsupported = True
        if FEE.search(clause) and not NO_FEE.search(clause) and re.search(r"\b(?:appl(?:y|ies)|charg\w*|is|must|pay|deduct\w*)\b|\$", clause, re.I):
            unsupported = True

    if conflict:
        flag("policy_conflict", "The asserted refund deadline or date anchor differs from the active policy.",
             trusted, policy=True)
    if unsupported:
        flag("unsupported_claim", "The approved refund policy supplies no basis for the asserted guarantee or fee.",
             trusted, policy=True)
    if trusted and not asserted and not conflict:
        flag("incomplete_answer", "The response leaves the refund deadline unanswered.", trusted)
    return findings



def review_evidence(run: Run, report: Investigation) -> Investigation:
    """Resolve exact quotes separately from contextual retrieval candidates."""
    approved = {policy.id: policy for policy in POLICIES}
    chunk_index = {chunk.id: chunk for chunk in policy_chunks(POLICIES)}
    evidence = {doc.id: doc for doc in report.evidence if approved.get(doc.id) == doc}
    matches = [
        hit for hit in report.matches
        if (chunk := chunk_index.get(hit.chunk_id)) is not None
        and hit.policy_id == chunk.policy.id and hit.excerpt == chunk.text
        and hit.policy_id in evidence
    ]
    trace_ids = {call.id for call in run.calls}
    # Revalidate the exact assertion against the detected condition. A link
    # that resolves to a real document is insufficient on its own.
    rechecked = detect_contextual(run.answer, run.calls)
    support = []
    clean_findings = []
    for index, finding in enumerate(report.findings):
        proof = next((item for item in rechecked if item == finding), None)
        quote = None
        if (proof is not None and finding.code in {"policy_conflict", "unsupported_claim"}
                and finding.source_ids == [REFUND.id] and evidence.get(REFUND.id) == REFUND):
            quote = REFUND.text.split(". ", 1)[0] + "."
            status = "policy_supported"
            rationale = (
                "The quoted policy sets the refund window and delivery anchor."
                if finding.code == "policy_conflict"
                else "The approved refund policy states eligibility only. It supplies no basis for this guarantee or fee."
            )
        elif (proof is not None and finding.code not in {"policy_conflict", "unsupported_claim"}
              and finding.trace_ids and set(finding.trace_ids) <= trace_ids):
            status = "trace_supported"
            rationale = "The cited execution events establish this observation."
        elif proof is not None and finding.code == "missing_evidence" and not run.calls:
            status = "trace_supported"
            rationale = "The supplied execution trace contains no policy lookup."
        else:
            status = "insufficient"
            rationale = "The available trace and approved policy do not establish this assertion."
        support.append(FindingSupport(finding_index=index, status=status, quote=quote, rationale=rationale))
        clean_findings.append(finding if quote else finding.model_copy(update={"source_ids": []}))

    has_active_lookup = any(call.tool == "lookup_policy" and call.arguments == ARGS
                            and call.output == REFUND and not call.error for call in run.calls)
    warning = None if has_active_lookup else (
        "The execution has no verified active refund policy. Investigator retrieval does not prove the agent used it."
    )
    return report.model_copy(update={"support": support, "findings": clean_findings,
                                    "matches": matches, "evidence": list(evidence.values()),
                                    "evidence_warning": warning})
