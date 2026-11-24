import logging
import os
from contextlib import asynccontextmanager, closing
from pathlib import Path
from sqlite3 import connect
from threading import Lock
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .access import AccessConfig, install_access
from .context_v4 import VERSION as V4
from .request_limits import RequestBodyLimit
from .runtime_config import secret_setting
from .evaluation import EvaluationResult, EvaluationStore, evaluate_suite
from .gemini import GeminiUnavailable, live_configured
from .graph import build_graph, config
from .reliability import VERSION
from .retrieval import PolicyRetriever, model_identity, sentence_encoder
from .schema import Decision, EvidenceMatch, Investigation, Review, Run, Submission
from .workflow import CASES, POLICIES

logger = logging.getLogger(__name__)


def create_app(
    checkpoint_path: Path | None = None, *, model_path: Path | None = None,
    detector: str = "phase4", access: AccessConfig | None = None,
    database_url: str | None = None, static_dir: Path | None = None,
) -> FastAPI:
    if detector not in {"phase4", VERSION, V4}:
        raise ValueError("Unsupported detector configuration")

    @asynccontextmanager
    async def lifespan(app):
        if model_path is not None:
            if checkpoint_path is None or not model_path.is_dir():
                raise ValueError("Hybrid retrieval requires a local model folder and persistent data directory")
            # Phase 3's index is separate from the LangGraph checkpoint file.
            embedding_id = model_identity(model_path)
            retriever = PolicyRetriever(
                POLICIES, path=checkpoint_path.parent / "chroma",
                embed=sentence_encoder(str(model_path)), embedding_id=embedding_id,
            )
        else:
            retriever = PolicyRetriever(POLICIES)
        app.state.retriever = retriever
        if database_url:
            from langgraph.checkpoint.postgres import PostgresSaver
            from .postgres_store import PostgresEvaluationStore, engine_for

            engine = engine_for(database_url)
            try:
                app.state.pg_engine = engine
                store = PostgresEvaluationStore(engine)
                store.ready()
                app.state.evaluations = store
                with PostgresSaver.from_conn_string(database_url) as saver:
                    # A release migration must initialize the checkpoint schema.
                    next(saver.list(None, limit=1), None)
                    app.state.graph = build_graph(saver, retriever)
                    yield
            finally:
                engine.dispose()
            return

        database_path = ":memory:"
        if checkpoint_path is not None:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            database_path = str(checkpoint_path.with_name(checkpoint_path.stem + "-evaluations.sqlite3"))
        with closing(connect(database_path, check_same_thread=False)) as database:
            app.state.evaluations = EvaluationStore(database)
            if checkpoint_path is None:
                app.state.graph = build_graph(InMemorySaver(), retriever)
                yield
            else:
                with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                    app.state.graph = build_graph(saver, retriever)
                    yield

    app = FastAPI(title="Error Dodge", version="0.5.0", lifespan=lifespan)
    app.add_middleware(RequestBodyLimit)
    install_access(app, access or AccessConfig({}))
    # Serialize reviews in the single local API process to prevent two
    # simultaneous decisions from resuming the same checkpoint.
    review_lock = Lock()
    evaluation_lock = Lock()

    def get_state(run_id: UUID) -> dict:
        state = app.state.graph.get_state(config(run_id)).values
        if "run" not in state:
            raise HTTPException(404, "Run not found")
        return state

    def review_view(state: dict) -> Review:
        if "evaluation" not in state:
            raise HTTPException(404, "No proposal to review")
        return Review(proposal=state["proposal"], evaluation=state["evaluation"],
                      decision=state.get("decision"))

    @app.get("/api/cases")
    def cases() -> list[dict[str, str]]:
        return [dict(id=c.id, name=c.name, question=c.question) for c in CASES.values()]

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, bool]:
        return {"gemini_configured": live_configured()}

    @app.get("/api/policies/search")
    def search_policies(q: str = Query(min_length=1, max_length=300)) -> list[EvidenceMatch]:
        return app.state.retriever.search(q)

    @app.post("/api/runs", status_code=status.HTTP_201_CREATED)
    def submit(body: Submission) -> Run:
        if body.case_id not in CASES:
            raise HTTPException(404, "Unknown sample case")
        if body.provider == "gemini" and body.case_id != "successful":
            raise HTTPException(400, "Gemini is available for the standard refund case only")
        if body.provider == "gemini" and not live_configured():
            raise HTTPException(503, "Gemini requires GEMINI_API_KEY and GEMINI_MODEL")
        run_id = uuid4()
        # Prior runs provide navigation context only. Their answers and tool
        # outputs never enter the current policy evidence or model prompts.
        related = []
        for previous in list_runs():
            if previous.case_id == body.case_id:
                related.append({"id": str(previous.id), "status": previous.status})
                if len(related) == 3:
                    break
        try:
            state = app.state.graph.invoke(
                {"case_id": body.case_id, "run_id": str(run_id), "provider": body.provider,
                 "related_runs": related, "detector": detector},
                config(run_id),
            )
        except GeminiUnavailable as error:
            logger.warning("gemini_run_failed run_id=%s type=%s", run_id, error.__cause__.__class__.__name__)
            raise HTTPException(502, str(error)) from None
        run = Run.model_validate(state["run"])
        logger.info("run_id=%s case_id=%s status=%s", run.id, run.case_id, run.status)
        return run

    @app.get("/api/runs")
    def list_runs() -> list[Run]:
        # Checkpoints are the source of truth for both run history and reviews.
        # This local demo is small enough to scan snapshots for the latest run.
        runs = {}
        for item in app.state.graph.checkpointer.list(None):
            raw = item.checkpoint["channel_values"].get("run")
            if raw is not None and raw["id"] not in runs:
                runs[raw["id"]] = Run.model_validate(raw)
        return sorted(runs.values(), key=lambda run: run.created_at, reverse=True)

    @app.get("/api/incidents")
    def incidents() -> list[Run]:
        return [run for run in list_runs() if run.status == "flagged"]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: UUID) -> Run:
        return Run.model_validate(get_state(run_id)["run"])

    @app.get("/api/runs/{run_id}/investigation")
    def investigation(run_id: UUID) -> Investigation:
        state = get_state(run_id)
        if "report" not in state:
            raise HTTPException(404, "No findings to investigate")
        return Investigation.model_validate(state["report"])

    @app.get("/api/runs/{run_id}/review")
    def read_review(run_id: UUID) -> Review:
        return review_view(get_state(run_id))

    @app.post("/api/runs/{run_id}/review")
    def record_review(run_id: UUID, body: Decision, request: Request) -> Review:
        def record():
            current = review_view(get_state(run_id))
            if current.decision is not None:
                raise HTTPException(409, "Decision already recorded")
            value = {**body.model_dump(), "actor_role": request.state.role}
            state = app.state.graph.invoke(Command(resume=value), config(run_id))
            result = review_view(state)
            logger.info("review_recorded run_id=%s actor_role=%s outcome=%s",
                        run_id, request.state.role, body.outcome)
            return result

        if database_url:
            from .postgres_store import ReviewBusy, postgres_review_lock

            try:
                with postgres_review_lock(app.state.pg_engine, run_id):
                    return record()
            except ReviewBusy as error:
                raise HTTPException(409, str(error)) from None
        with review_lock:
            return record()

    @app.post("/api/evaluations", status_code=status.HTTP_201_CREATED)
    def create_evaluation(run_id: UUID | None = None) -> EvaluationResult:
        # This is a sandbox evaluation. Selecting an incident uses its exact
        # proposed controls without approving or deploying them.
        controls = ["ground_answer"]
        if run_id is not None:
            controls = review_view(get_state(run_id)).proposal.controls
        if not evaluation_lock.acquire(blocking=False):
            raise HTTPException(409, "An evaluation is already running")
        try:
            result = evaluate_suite(app.state.retriever, controls)
            app.state.evaluations.save(result)
        finally:
            evaluation_lock.release()
        logger.info("evaluation_id=%s dataset=%s cases=%s duration_ms=%s",
                    result.id, result.dataset, len(result.cases), result.elapsed_ms)
        return result

    @app.get("/api/evaluations")
    def list_evaluations() -> list[EvaluationResult]:
        with evaluation_lock:
            return app.state.evaluations.list()

    @app.get("/api/evaluations/{evaluation_id}")
    def get_evaluation(evaluation_id: UUID) -> EvaluationResult:
        with evaluation_lock:
            result = app.state.evaluations.get(evaluation_id)
        if result is None:
            raise HTTPException(404, "Evaluation not found")
        return result

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"status": "live"}

    @app.get("/health/ready", include_in_schema=False)
    def ready():
        if database_url:
            try:
                app.state.evaluations.ready()
            except Exception:
                logger.exception("readiness storage query failed")
                raise HTTPException(503, "Storage unavailable") from None
        return {"status": "ready"}

    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")

    return app


model_setting = os.getenv("ERROR_DODGE_EMBEDDING_PATH", "").strip()
app = create_app(
    Path(os.getenv("AGENTPROOF_DB") or
         Path(__file__).resolve().parents[2] / ".data" / "checkpoints.sqlite3"),
    model_path=Path(model_setting) if model_setting else None,
    detector=os.getenv("ERROR_DODGE_DETECTOR", "phase4"),
    access=AccessConfig.from_env(),
    database_url=secret_setting("ERROR_DODGE_DATABASE_URL") or None,
    static_dir=Path(setting) if (setting := os.getenv("ERROR_DODGE_STATIC_DIR")) else None,
)