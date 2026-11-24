# Error Dodge Phase 5 staging implementation

## Access and persistence

The local demo continues to support SQLite and loopback use. Token mode provides three shared, separate roles for single-workspace staging. A viewer reads data, an evaluator also runs agent and benchmark jobs, and a reviewer can record decisions. The browser keeps the token in memory. Authentication is checked by the API for every protected call, and protected responses use no-store. Review records capture the server-authorized role. These are shared role credentials and provide no individual reviewer identity.

For PostgreSQL, configure `ERROR_DODGE_DATABASE_URL` as a `postgresql://` connection string. SQLAlchemy and Alembic own evaluation persistence; the official LangGraph PostgreSQL checkpointer stores runs and review state. The API checks the schema at startup. Run with one API worker until review synchronization is moved to the database. Existing SQLite history is not imported automatically.

From `backend`, after configuring an empty or staging PostgreSQL database:

~~~powershell
..\.venv\Scripts\python.exe -B -m alembic upgrade head
..\.venv\Scripts\python.exe -B -m app.pg_setup
~~~

Run these once as a release step. Set `ERROR_DODGE_TEST_POSTGRES_URL` to a migrated disposable database to enable the PostgreSQL integration test. That test writes synthetic records.

## Container staging

The newer [private deployment guide](deployment.md) documents file-mounted secrets and loopback access.

## Verified locally

- Installed and tested against a disposable password-protected PostgreSQL 17.12 cluster. Ran the Alembic migration and LangGraph schema setup. The integration test created an incident and evaluation, restarted the app twice, and recovered the run, persisted benchmark, and saved review.
- **28 backend tests passed** with PostgreSQL and the real local embedding model enabled. The frontend production build and installed dependency check passed. LangSmith and Chroma emitted existing deprecation warnings.
- Browser acceptance used the built dashboard and a separate authenticated SQLite staging instance. The viewer could read but had disabled run controls. The reviewer signed in, ran the refund failure using v3, opened the policy-supported citation, and rejected the test proposal. The local demo's saved benchmark history also loaded after refresh.
- Parsed the Compose YAML. Docker Engine was unavailable, so image builds, Compose startup, container networking, and remote hosting were not exercised.

Phase 5 remains in progress. Production OIDC, per-user and tenant isolation, migration of existing SQLite records, database-level review serialization, external TLS and rate limits, and staging deployment acceptance remain open. See [the Phase 5 plan](phase5-plan.md) for exit criteria.

Implementation references. [Docker startup ordering](https://docs.docker.com/compose/how-tos/startup-order/) · [SQLAlchemy PostgreSQL dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html) · [LangGraph checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
