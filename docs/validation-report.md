# Error Dodge pre-Phase 5 validation

## Why the Phase 4 proposal passed only four tasks

The Phase 4 dashboard evaluated one control, `ground_answer`. It repaired invented deadlines, guaranteed refunds, and incomplete responses when valid evidence was already available. It did not change the route or the evidence supply. I reproduced the 4/10 result and inspected every remaining trace.

| Remaining case | Observed root cause |
|---|---|
| Wrong tool | The router requested shipping instead of refund policy. |
| Tool error | The first timeout stopped lookup before any evidence returned. |
| Repeated lookup | Both identical lookups succeeded. The task rubric requires one successful lookup. |
| Stale policy | The workflow accepted the archived 30-day source and extracted its obsolete deadline. |
| Missing lookup | The agent skipped the source lookup and could only refer the customer to support. |
| Untrusted output | An external note replaced the approved source. The agent abstained and lacked a trusted fallback route. |

The sandbox executor forces the refund route for an explicitly scoped refund-window task, accepts the active policy only when its content and version match, allows one timeout retry, and renders the answer from the verified policy. A content mismatch yields an abstention. The sandbox monitor separately checks the observed traces and answer claims. Neither candidate is activated in the running app. The original ten cases replayed at 4/10 versus 10/10 with the sandbox executor and a trusted simulated source, including one transient timeout.

## Method and leakage controls

- The 20-case held-out replay was frozen before candidate implementation. It was unavailable during the original detector and Gemini prompt development and does not overlap the ten Phase 4 fixtures. I had access to it while implementing the candidate, so its candidate score is a development check.
- The eight-case post-freeze set was written after the candidate code was frozen and was run without changing the candidate. Both sets were authored and scored in this project. No external annotator or live model participated.
- Detection compares both monitors on the same original answers and tool traces. Precision and recall classify each incident as flagged or clean. Raw results also report exact extra and missed labels. Agent metrics compare manually labeled baseline replays with executed guarded responses under the fixture's simulated service. Faithfulness credits a safe abstention. Task completion requires an answer. Tool accuracy means the trace used the approved operation and active source, with one bounded recovered timeout allowed.
- The scopes are synthetic refund-window tasks and the same policy corpus. No live Gemini calls, prompt changes, or provider-token measurements were made.

| Metric | 20-case replay before → after | 8-case post-freeze before → after |
|---|---:|---:|
| Detection precision | 84.6% → 100% | 80.0% → 80.0% |
| Detection recall | 68.8% → 100% | 66.7% → 66.7% |
| False positives | 2 → 0 | 1 → 1 |
| False negatives | 5 → 0 | 2 → 2 |
| Faithful responses, including safe abstentions | 9/20 → 20/20 | 5/8 → 8/8 |
| Correct tool traces | 10/20 → 19/20 | 6/8 → 8/8 |
| Task completion | 5/20 → 19/20 | 3/8 → 8/8 |

## Remaining failures and regression findings

- A permanent provider timeout remained incomplete after two attempts. The guard abstained and retained both timeout events. A separate persistent source-tampering check also produced a safe abstention, with no retry for invalid content.
- The post-freeze monitor regressed on “Approval is not guaranteed.” Its pattern sees the guarantee word and misses negation. It fixed the old false positive on “7 calendar days,” so the aggregate precision hid the case-level regression.
- Both monitors missed two post-freeze incidents. The candidate missed an approval promise phrased as “will be approved without review,” and it missed “from the date you paid” as an incorrect anchor. On “ten days,” it flagged an incomplete answer instead of a conflicting deadline because the parser recognizes only digits and a limited set of number words.
- No previously passing task, tool trace, or faithfulness label regressed in the two replay sets. The detection regression remains a blocker to promoting the candidate. Use independent annotation, wider policy topics, and real traces before considering deployment.

## Evidence and citation audit

All 107 excerpt occurrences across 39 reports matched the indexed source text and versioned chunk ID. All 40 emitted citations resolved to the approved refund document, and all checked trace references resolved within their run. The refund excerpt ranked first in all 39 reports. Of the 107 excerpts, 68 came from other policies and did not establish the refund deadline. Exact excerpt integrity is distinct from relevance.

On the 20-case replay, 7/9 baseline and 22/22 candidate citations were attached to a finding supported by the fixture labels. On the post-freeze set this was 2/4 and 3/5. The candidate's two unsupported cited findings were the negated guarantee and the incorrect label for the spelled-out “ten days.” The audit checked these fixture-supported claims and source bindings. It is not a general entailment test.

## Latency and token cost

| Measured stage | Before p50 / p95 | After p50 / p95 |
|---|---:|---:|
| Monitor, 20-case replay | 0.0261 / 0.0463 ms | 0.0321 / 0.0465 ms |
| Monitor, 8-case post-freeze | 0.0245 / 0.2094 ms | 0.0318 / 0.0500 ms |
| Agent execution, 10 original fixtures | 0.0088 / 0.0328 ms | 0.0046 / 0.0160 ms |

These are local function timings from one run. They exclude browser, HTTP, real tool network delays, model startup, and report retrieval. Before and after both made zero paid provider calls, used zero billable tokens, and incurred zero provider charges. Real Gemini latency, token usage, and cost remain unmeasured. Local embedding compute is separate from provider token billing.

## Reproduce

With the setup in the project README, set `ERROR_DODGE_EMBEDDING_PATH` to the local model folder and run from `backend`. Choose an existing output directory for each run so the JSON and local validation index stay together.

~~~powershell
$env:PYTHONPATH = (Get-Location).Path
..\.venv\Scripts\python.exe -B tests/run_heldout.py .\heldout-results.json
..\.venv\Scripts\python.exe -B tests/run_heldout.py .\post-freeze-results.json --post-freeze
..\.venv\Scripts\python.exe -B -m pytest -q
~~~

Both replay commands completed. The existing 22 backend tests passed with the real embedding model. The frontend built and the live dashboard, stored investigation, and benchmark history responded. LangSmith and Chroma emitted existing dependency deprecation warnings. The next implementation work is specified in [the Phase 5 plan](phase5-plan.md).
