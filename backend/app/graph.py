"""Coordinate four specialist nodes and persist state under the run ID."""
from datetime import UTC, datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .context_v4 import VERSION as V4, detect_v4, review_v4
from .reliability import VERSION, detect_contextual, review_evidence
from .retrieval import PolicyRetriever
from .schema import Decision, Investigation, RelatedRun, Run
from .workflow import CASES, candidate_result, execute, investigate, make_run, score


class State(TypedDict, total=False):
    case_id: str
    run_id: str
    provider: str
    detector: str
    related_runs: list[dict]
    observation: dict
    run: dict
    report: dict
    proposal: dict
    evaluation: dict
    decision: dict


def demonstration(state: State) -> dict:
    case = CASES[state["case_id"]]
    if state["provider"] == "gemini":
        from .gemini import execute_live
        answer, calls = execute_live(case.question)
    else:
        answer, calls = execute(case)
    # Store JSON-ready values so checkpoint state is portable and inspectable.
    return {"observation": {"answer": answer, "calls": [call.model_dump(mode="json") for call in calls]}}


def monitor(state: State) -> dict:
    from .schema import ToolCall
    observation = state["observation"]
    calls = [ToolCall.model_validate(call) for call in observation["calls"]]
    run = make_run(CASES[state["case_id"]], observation["answer"], calls,
                   state["run_id"], state["provider"])
    detector = state.get("detector")
    if detector in {VERSION, V4}:
        detector_fn = detect_v4 if detector == V4 else detect_contextual
        findings = detector_fn(run.answer, calls)
        run = run.model_copy(update={"detector": detector, "findings": findings,
                                     "status": "flagged" if findings else "no_issue_detected"})
    return {"run": run.model_dump(mode="json")}


def route(state: State) -> str:
    return "investigation" if state["run"]["findings"] else END


def improvement(state: State) -> dict:
    from .workflow import MITIGATIONS
    report = Investigation.model_validate(state["report"])
    controls = sorted({MITIGATIONS[f.code] for f in report.findings})
    return {"proposal": {"recommendation": report.recommendation, "controls": controls}}


def evaluation(state: State) -> dict:
    # Run the same fixtures twice. Neither variant mutates the baseline, and
    # the live provider never participates in this synthetic comparison.
    baseline, proposed, regressions = [], [], []
    for case in CASES.values():
        before = score(*execute(case))
        after = score(*candidate_result(case, set(state["proposal"]["controls"])))
        baseline.append(before)
        proposed.append(after)
        if before and not after:
            regressions.append(case.id)
    return {"evaluation": {
        "dataset": "synthetic-refund-v1",
        "cases": len(baseline),
        "baseline_passes": sum(baseline),
        "proposed_passes": sum(proposed),
        "regressions": regressions,
    }}


def review(state: State) -> dict:
    # LangGraph suspends here. The reviewer can record a decision later using
    # the same thread ID, including after a restart. This node changes no config.
    resumed = interrupt({
        "proposal": state["proposal"], "evaluation": state["evaluation"],
    })
    decision = Decision(outcome=resumed["outcome"])
    return {"decision": {**decision.model_dump(), "actor_role": resumed.get("actor_role"),
                         "recorded_at": datetime.now(UTC).isoformat()}}


def build_graph(checkpointer, retriever: PolicyRetriever):
    def investigation(state: State) -> dict:
        related = [RelatedRun.model_validate(item) for item in state.get("related_runs", [])]
        run = Run.model_validate(state["run"])
        report = investigate(run, retriever, related)
        if run.detector == V4:
            report = review_v4(run, report)
        elif run.detector == VERSION:
            report = review_evidence(run, report)
        return {"report": report.model_dump(mode="json")}

    return (
        StateGraph(State)
        .add_node("demonstration", demonstration)
        .add_node("monitor", monitor)
        .add_node("investigation", investigation)
        .add_node("improvement", improvement)
        .add_node("evaluation", evaluation)
        .add_node("review", review)
        .add_edge(START, "demonstration")
        .add_edge("demonstration", "monitor")
        .add_conditional_edges("monitor", route, ["investigation", END])
        .add_edge("investigation", "improvement")
        .add_edge("improvement", "evaluation")
        .add_edge("evaluation", "review")
        .add_edge("review", END)
        .compile(checkpointer=checkpointer)
    )


def config(run_id) -> dict:
    # The graph is acyclic. This budget also stops accidental future cycles.
    return {"configurable": {"thread_id": str(run_id)}, "recursion_limit": 12}
