# Error Dodge release and portfolio report

## Outcome

The local portfolio build is complete. The app includes role-aware monitoring, incident filtering, a guided replay, evidence-backed investigations, synthetic benchmark history and human approvals. PostgreSQL, review concurrency, input limits, mounted secret configuration and audit events were exercised locally. This is a private staging build. Public production readiness remains unverified.

## Hardening decisions

- Protected writes are explicitly authorized per route. Viewers can read, evaluators can run cases and benchmarks, and reviewers can also record decisions. Unauthorized and malformed requests are rejected. API writes are limited to 16 KiB before schema validation.
- Database and API credentials are supplied at runtime. The browser keeps access tokens in memory; the client sends them in the Authorization header and disables HTTP caching. The Compose template grants individual services mounted secret files. Test logs confirmed the review event includes the run ID, outcome and role without the credential.
- SQLite reviews use an in-process lock. PostgreSQL reviews use a transaction-scoped advisory lock keyed by run ID across independent app instances. Two concurrent attempts produced one HTTP 200 and one HTTP 409, and the recorded decision matched the accepted request. The existing PostgreSQL checkpoint schema and evaluation-table migration were applied to a fresh server and verified across application restarts.

## Detector results and limitations

Contextual V3 treated delivery and familiar payment anchors differently but did not recognize billing-document events such as an invoice date. V4 extends the date-event vocabulary to billing, transaction, invoice and card events. It normalizes event references for analysis and keeps the original answer in the evidence trail. The seven-day delivery policy remains unchanged.

- The original invoice-date failure is now flagged. The first V4 test run exposed a direct card-event miss. I corrected that pattern and bounded a negated-billing pattern, then reran the tests.
- On the eight-case billing regression set, V3 correctly flagged 1/5 conflicts and V4 flagged 5/5. Neither detector flagged any of the three clean cases after the fix. This set informed the fix and is a regression check.
- On six cases written after the final V4 freeze, V3 flagged 0/3 conflicts and produced one false positive. V4 flagged 2/3 and produced two false positives. V4 precision was 50%, recall 66.7%, and F1 57.1% on this small slice.
- V4 still missed “after receiving your invoice.” It also treated a bank-processing sentence as a refund deadline. Both versions misread a delivered-order paraphrase as a purchase anchor. Keep V4 opt-in and expand policy and language coverage. This small set does not measure production behavior.

The screenshots display the Phase 4 synthetic benchmark. In the captured run the grounding proposal raised task passes from 1/10 to 4/10. Hybrid retrieval placed the expected excerpt first on 10/10 answerable retrieval cases, compared with 8/10 for keyword search. Both methods abstained on the three unrelated queries. The original ten cases were used to develop the baseline. Values from the independent V3 and targeted V4 checks are reported separately.

## Verification executed

| Check | Outcome |
|---|---|
| `python -B -m alembic upgrade head` and `python -B -m app.pg_setup` | Passed on a disposable password-protected PostgreSQL 17.12 server |
| `python -B -m pytest -q -p no:cacheprovider --basetemp ../../../work/release-rerun-tests` | **37 passed** with PostgreSQL and the real local embedding model. Existing LangSmith and Chroma deprecation warnings remain. |
| `npm test` | **2 passed** |
| `npm run build` | Passed |
| `python -B tests/compare_billing_anchors.py` and `--post-fix` | Both ran and produced per-case results including misses |
| Browser acceptance | Viewer write restriction, reviewer sign-in, synthetic refund run, quoted citation and approval, saved history after reload, guided demo, incident filter and 390px layout all verified against isolated staging |
| Compose | YAML parsed. Docker and Podman were unavailable, so image builds and Compose startup were not run. |

The browser walkthrough used an isolated authenticated SQLite instance. PostgreSQL persistence and concurrent decisions were verified separately via integration tests. No public deployment, live Gemini, OIDC, tenant scoping, individual audit identity, SQLite history import, or external TLS, rate limiting, backups and rollback were exercised. The staging deployment guide recommends loopback plus an SSH tunnel. No paid provider calls were made during portfolio execution.

## Resume bullets

- Built Error Dodge, a multi-agent AI reliability platform using Python, FastAPI, LangGraph and React, with execution traces, policy-backed investigations, sandbox evaluations and human approval checkpoints.
- Implemented hybrid RAG with Sentence Transformers, ChromaDB and BM25, and reproduced a rank-1 improvement from 8/10 to 10/10 on labeled synthetic retrieval queries.
- Verified PostgreSQL persistence and concurrent review safety across two API instances, and passed 37 backend tests and two frontend tests covering authentication, input validation, retrieval and review workflows.
