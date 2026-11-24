# Error Dodge demo script

**Run time** 2 minutes 40 seconds. Use the synthetic demo and have Contextual V3 and hybrid retrieval enabled. To show role enforcement, sign in with a local staging reviewer token before recording. Keep credentials and the sign-in form out of the recording.

| Time | On screen | Narration |
|---|---|---|
| 0:00–0:20 | Dashboard and Guided demo | “Error Dodge monitors an AI support agent, investigates failures, and tests a proposed fix before a human reviews it. This demonstration uses synthetic cases and local embeddings.” |
| 0:20–0:50 | Run **Incorrect refund window** and expand the tool call | “The agent says the customer has 30 days to request a refund. Its trace shows the agent already retrieved the seven-day policy. The monitor flags the contradiction.” |
| 0:50–1:25 | Open the investigation and follow the citation | “The report links the finding to the exact refund-policy quote and the original lookup. Hybrid search surfaces candidates. The report tells you which policy actually supports this finding. The explanation for why the agent made the error is a hypothesis.” |
| 1:25–1:55 | Open **Evaluations**, run the benchmark, and expand one case | “The dashboard runs both configurations against the same synthetic cases and shows the per-case trace behind each count. In the verified grounding benchmark, task passes went from one to four out of ten. That test is a regression check on scripted cases.” |
| 1:55–2:20 | Return to the investigation and approve the disposable proposal | “A reviewer can record a decision. The decision persists, and the agent configuration remains separate. In the PostgreSQL integration test, two API instances raced to decide and only one was accepted.” |
| 2:20–2:40 | Show the architecture diagram | “FastAPI connects React to the LangGraph monitor, investigator, improvement and evaluation nodes. Sentence Transformers and Chroma provide semantic retrieval alongside BM25. PostgreSQL holds checkpoints and benchmark history. The next validation step is an independent dataset across broader policy topics and real model traces.” |

## Interview follow-ups

- **Why keep retrieval and investigation separate?** A high-ranked passage can be irrelevant. A finding cites a verified quote or the actual tool trace.
- **Why use a human checkpoint?** A decision is recorded and durable. Benchmark execution and review are separate from applying a change.
- **What would you improve next?** Broaden policy and language coverage, measure live Gemini behavior, and replace shared staging roles with individual identity before public use.
