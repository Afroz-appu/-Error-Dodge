"""PostgreSQL repositories used when ERROR_DODGE_DATABASE_URL is configured."""
import hashlib
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Column, MetaData, Table, Text, create_engine, insert, select, text
from sqlalchemy.engine import make_url

from .evaluation import EvaluationResult

metadata = MetaData()
evaluations = Table(
    "evaluation_runs", metadata,
    Column("id", Text, primary_key=True), Column("created_at", Text, nullable=False),
    Column("result", Text, nullable=False),
)


def engine_for(url):
    parsed = make_url(url)
    if parsed.drivername != "postgresql" or not parsed.database:
        raise ValueError("Use a postgresql:// URL with a database name")
    return create_engine(parsed.set(drivername="postgresql+psycopg"), pool_pre_ping=True)


class PostgresEvaluationStore:
    def __init__(self, engine):
        self.engine = engine

    def ready(self):
        with self.engine.connect() as database:
            database.execute(select(evaluations.c.id).limit(1)).close()

    def save(self, result: EvaluationResult) -> None:
        with self.engine.begin() as database:
            database.execute(insert(evaluations).values(
                id=str(result.id), created_at=result.created_at.isoformat(),
                result=result.model_dump_json(),
            ))

    def list(self) -> list[EvaluationResult]:
        statement = select(evaluations.c.result).order_by(
            evaluations.c.created_at.desc(), evaluations.c.id.desc()
        ).limit(20)
        with self.engine.connect() as database:
            return [EvaluationResult.model_validate_json(item) for item in database.scalars(statement)]

    def get(self, evaluation_id: UUID) -> EvaluationResult | None:
        statement = select(evaluations.c.result).where(evaluations.c.id == str(evaluation_id))
        with self.engine.connect() as database:
            result = database.scalar(statement)
        return EvaluationResult.model_validate_json(result) if result is not None else None



class ReviewBusy(RuntimeError):
    pass


@contextmanager
def postgres_review_lock(engine, run_id: UUID):
    # One database transaction holds the lock while the graph's separate
    # connection commits the decision. The same run ID locks across workers.
    key = int.from_bytes(hashlib.sha256(b"error-dodge/review/" + run_id.bytes).digest()[:8],
                         byteorder="big", signed=True)
    with engine.begin() as database:
        granted = database.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
        if not granted:
            raise ReviewBusy("A review is already being recorded for this run")
        yield