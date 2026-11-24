# Error Dodge reliability checkpoint

## Implementation

The versioned candidate uses clause-level claim extraction and policy comparison. It parses English number words and day or week units, associates a duration with a refund context, separates uncertainty from assertion, and evaluates approval polarity independently from deadlines. Trace checks validate the operation, topic, source contents and version, and distinguish a recovered timeout from repeated successful calls.

An investigation checks source and chunk integrity, reruns the frozen detector to bind each finding to the observed answer and trace, and keeps quotes only for a policy-supported finding. Missing trace evidence is explicit. The policy retrieved by the investigation remains distinct from the policy the monitored agent actually used. Invalid documents and excerpts are excluded, and unsupported findings have their citation stripped and are labeled unverified. These checks verify the rules and approved corpus, not general natural-language entailment.

An LLM judge was deferred. The current task is a narrow refund policy with an explicit contract, and these tests do not have independent human entailment labels or an authenticated Gemini provider. The Phase 4 and guarded-v2 implementations are preserved. Select the candidate with `ERROR_DODGE_DETECTOR=refund-context-v3`; the standard configuration remains `phase4`.

## Frozen evaluation

I recorded the candidate SHA-256 before authoring the new 17-case synthetic set. The runner verifies the hashes of detector and data before replaying. Both historical sets are separate regression measurements. Labels are project-authored. No external evaluator, live model, or production traces were used.

| Detector | Precision | Recall | F1 | False positives | False negatives |
|---|---:|---:|---:|---:|---:|
| Phase 4 | 75.0% | 92.3% | 82.8% | 4 | 1 |
| Guarded v2 | 78.6% | 84.6% | 81.5% | 3 | 2 |
| Contextual v3 | 100% | 92.3% | 96.0% | 0 | 1 |

The candidate missed an incorrect deadline anchored to the **invoice date**. There were no exact-label regressions versus v2 on the 20- and 8-case historical suites. V3 matched all expected labels in both, including the earlier negated approval, implied approval, payment anchor, and spelled-number examples. On the new suite, guarded execution improved task completion from 5/17 to 16/17, tool correctness from 13/17 to 16/17, and faithfulness from 8/17 to 17/17, counting the safe abstention. The permanent outage remained incomplete. These agent comparisons reuse the existing guarded executor. The detector does not make the agent complete a task.

All 26 retrieved excerpt occurrences in v3's twelve reports matched approved source content. The refund policy ranked first eleven times; fifteen lower-ranked excerpts came from other policies and did not support a refund finding. All seven emitted policy citations resolved and accompanied a finding supported by the fixture labels. Operational findings rely on the trace. Citation correctness applies to emitted claims, and it does not cover the missed invoice-anchor case.

V3 local detector latency was 0.0977 ms p50 and 0.3795 ms p95 on the new set. These function timings exclude retrieval, HTTP, network delays and model startup. The replay used zero paid API calls, zero billable tokens, and zero provider charges.

## Reproduce

From the backend directory with the local model path configured:

~~~powershell
$env:PYTHONPATH = (Get-Location).Path
..\.venv\Scripts\python.exe -B tests/validate_contextual.py .\contextual-results.json
..\.venv\Scripts\python.exe -B -m pytest -q
~~~

The measured JSON includes per-case traces, detector timing, exact label differences, citation counts, task outcomes, and both fixture provenance hashes. The new cases are synthetic and narrow. Further work should cover unfamiliar date anchors, independent policy topics, broader negation syntax, and independent annotations before a default switch.
