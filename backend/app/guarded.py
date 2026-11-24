"""Sandbox-only execution and monitoring for explicit refund-window tasks."""
import re
from collections.abc import Callable

from .schema import Finding, LookupArgs, Policy, ToolCall
from .workflow import POLICIES

ABSTAIN = "I could not verify the refund window."
ARGS = LookupArgs(topic="refund")
DURATION = re.compile(r"\b(\d+|seven|thirty)\s+(?:(business|working|calendar)\s+)?days?\b", re.I)
PROMISE = re.compile(r"\bguarantee\w*|\bautomat\w*.{0,24}\bapprov|\$\s*\d+|\bprocessing fee\b", re.I)
WRONG_ANCHOR = re.compile(r"\b(?:from|after|of)\s+(?:the\s+)?(?:purchase|order date|payment)\b", re.I)


def guarded_refund(lookup_policy: Callable[[LookupArgs], Policy]) -> tuple[str, list[ToolCall]]:
    """Require the active source, retry a timeout once, and answer extractively."""
    active = next(policy for policy in POLICIES if policy.topic == ARGS.topic)
    calls = []
    for attempt in range(2):
        call_id = f"tool-{attempt + 1}"
        try:
            output = lookup_policy(ARGS)
        except TimeoutError as error:
            calls.append(ToolCall(id=call_id, tool="lookup_policy", arguments=ARGS, error=str(error)))
            continue
        calls.append(ToolCall(id=call_id, tool="lookup_policy", arguments=ARGS, output=output))
        # The identifier alone cannot attest to policy content or freshness.
        if output == active:
            return output.text.split(". ", 1)[0].rstrip(".") + ".", calls
        break  # A content mismatch is not a retryable transport error.
    return ABSTAIN, calls


def monitor_refund(answer: str, calls: list[ToolCall]) -> list[Finding]:
    """Check supported refund facts and the provenance of the observed trace."""
    active = next(policy for policy in POLICIES if policy.topic == ARGS.topic)
    known = {policy.id: policy for policy in POLICIES}
    findings = []

    def flag(code, detail, events, *, cite=False):
        findings.append(Finding(code=code, detail=detail, trace_ids=[event.id for event in events],
                                source_ids=[active.id] if cite else []))

    valid, errors = [], []
    for call in calls:
        if call.tool != "lookup_policy" or call.arguments != ARGS:
            flag("wrong_tool", "The call did not use the refund policy lookup.", [call], cite=True)
        elif call.error:
            errors.append(call)
        elif call.output == active:
            valid.append(call)
        elif call.output and call.output.id == "refund-v1":
            flag("stale_evidence", "The source was an archived policy.", [call], cite=True)
        elif call.output and known.get(call.output.id) != call.output:
            flag("untrusted_evidence", "Source identifier, version, or content could not be verified.", [call])

    # One timeout followed by one successful lookup is a recovered attempt.
    recovered = len(calls) == 2 and bool(errors and valid) and calls == [errors[0], valid[0]]
    if errors and not recovered:
        flag("tool_error", "Lookup error exceeded the allowed recovery pattern.", errors)
    if len(valid) > 1:
        flag("repeated_tool", "The active policy was looked up successfully more than once.", valid)
    if not valid:
        flag("missing_evidence", "No authenticated active refund policy was retrieved.", calls, cite=True)

    durations = DURATION.findall(answer)
    allowed = DURATION.findall(active.text)[0][0]
    words = {"seven": "7", "thirty": "30"}
    if (
        any(words.get(number.lower(), number) != allowed or modifier.lower() in {"business", "working"}
            for number, modifier in durations)
        or WRONG_ANCHOR.search(answer)
    ):
        flag("policy_conflict", "The stated refund deadline conflicts with the active policy.", calls, cite=True)
    if PROMISE.search(answer):
        flag("unsupported_claim", "The policy does not support the approval guarantee or fee.", calls, cite=True)
    if valid and not durations:
        flag("incomplete_answer", "The response does not state the refund window.", valid, cite=True)
    return findings
