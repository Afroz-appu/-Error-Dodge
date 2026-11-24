"""Normalize billing-event date anchors when evaluating a refund deadline."""
import re

from .reliability import detect_contextual, review_evidence

VERSION = "refund-context-v4"
# Billing documents are different from delivery or receipt of the goods.
# Normalize the event phrase only when it appears as a deadline anchor.
BILLING_ANCHOR = re.compile(
    r"\b(?P<relation>from|after|since|starting (?:on|at)|count(?:ed|ing)? from)"
    r"\s+(?:(?:the|your)\s+)?(?:"
    r"(?:card|account)\s+(?:is|was)\s+charged|you\s+(?:receive|received|get|got)\s+(?:the|your)\s+invoice|"
    r"(?:invoice|billing|transaction|card charge|authorization|order confirmation)(?: date| timestamp| time)?"
    r"|(?:date|day|time|moment)\s+(?:that\s+)?(?:the\s+|your\s+)?"
    r"(?:invoice (?:was|is) issued|(?:card|account) (?:was|is) charged|payment (?:cleared|posted))"
    r")\b", re.I,
)


NEGATED_ANCHOR = re.compile(r"\b(?:not|never|rather than|instead of)\s+(?:(?:be\s+)?counted\s+|count\s+)?$", re.I)


def normalized_answer(answer):
    def normalize(match):
        prefix = answer[max(0, match.start() - 32):match.start()]
        if NEGATED_ANCHOR.search(prefix):
            return match.group()
        return f"{match['relation']} the order date"

    return BILLING_ANCHOR.sub(normalize, answer)


def detect_v4(answer, calls):
    return detect_contextual(normalized_answer(answer), calls)


def review_v4(run, report):
    # The graph retains and displays the original answer. Revalidation uses
    # the same event normalization as detection and quotes the original policy.
    return review_evidence(run.model_copy(update={"answer": normalized_answer(run.answer)}), report)

