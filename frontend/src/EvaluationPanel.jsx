import React, { useEffect, useState } from 'react'

function Scores({ title, rows }) {
  return <section>
    <h3>{title}</h3>
    <dl className="evaluation-metrics">
      {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
  </section>
}

const percent = value => (value * 100).toFixed(1) + '%'
const count = (passes, total) => passes + ' / ' + total
const describe = values => values.join(', ') || 'None observed'

export default function EvaluationPanel({ api, canRun, incidentId, incidentName }) {
  const [history, setHistory] = useState([])
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    api('/evaluations').then(rows => {
      if (active) {
        setHistory(rows)
        setResult(rows[0] ?? null)
      }
    }).catch(err => { if (active) setError(err.message) })
    return () => { active = false }
  }, [api])

  async function evaluate(runId) {
    setBusy(true)
    setError('')
    try {
      const query = runId ? '?run_id=' + encodeURIComponent(runId) : ''
      const run = await api('/evaluations' + query, { method: 'POST' })
      setResult(run)
      setHistory(previous => [run, ...previous].slice(0, 20))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const retrieval = result?.retrieval_metrics
  return <section className="panel benchmark" id="evaluations" aria-label="Evaluation suite">
    <div className="detail-heading">
      <div>
        <h2>Evaluation suite</h2>
        <p className="muted">Compare configurations on the synthetic benchmark.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="primary" disabled={busy || !canRun} onClick={() => evaluate()}>Run benchmark</button>
        {incidentId && <button type="button" className="secondary" disabled={busy || !canRun}
          onClick={() => evaluate(incidentId)}>Evaluate selected proposal</button>}
      </div>
    </div>
    {incidentId && <p className="muted">Selected incident · {incidentName}</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {busy && <p role="status">Running benchmark…</p>}
    {!!history.length && <div className="benchmark-history">
      <label htmlFor="evaluation-run">Evaluation history</label>
      <select id="evaluation-run" disabled={busy} value={result?.id ?? ''}
        onChange={event => setResult(history.find(row => row.id === event.target.value))}>
        {history.map(run => <option key={run.id} value={run.id}>
          {new Date(run.created_at).toLocaleString()} · {run.controls.join(', ')}
        </option>)}
      </select>
    </div>}
    {!result && !busy && <p className="muted">No benchmark results saved.</p>}
    {result && <div className="grid gap-4">
      <p className="muted">Synthetic fixtures · {result.dataset} · {result.elapsed_ms.toFixed(1)} ms</p>
      <div className="benchmark-grid">
        <Scores title="Task metrics · baseline / proposed" rows={[
          ['Task passes', count(result.baseline.task_passes, result.proposed.task_passes)],
          ['Grounded answers', count(result.baseline.grounded_answers, result.proposed.grounded_answers)],
          ['Correct tool traces', count(result.baseline.correct_tool_traces, result.proposed.correct_tool_traces)],
        ]} />
        <Scores title="Baseline detection" rows={[
          ['Precision', percent(result.detection.precision)],
          ['Recall', percent(result.detection.recall)],
          ['F1', percent(result.detection.f1)],
        ]} />
      </div>
      <p>Each configuration ran {result.cases.length} agent cases. Regressions · {describe(result.regressions)}</p>
      <Scores title={'Retrieval · keyword / ' + result.retrieval_mode} rows={[
        ['First result (' + retrieval.answerable + ' answerable)', count(retrieval.keyword_top1, retrieval.active_top1)],
        ['Top three (' + retrieval.answerable + ' answerable)', count(retrieval.keyword_top3, retrieval.active_top3)],
        ['Correct abstentions (' + retrieval.unrelated + ' unrelated)', count(retrieval.keyword_abstentions, retrieval.active_abstentions)],
      ]} />
      <details className="trace">
        <summary>Detection errors and case traces</summary>
        <p>False positives · {describe(result.detection.false_positives)}</p>
        <p>False negatives · {describe(result.detection.false_negatives)}</p>
        <p>Unexpected codes · {describe(result.detection.unexpected_codes)}</p>
        <p>Missed codes · {describe(result.detection.missed_codes)}</p>
        {result.cases.map(row => <details className="trace" key={row.case_id}>
          <summary>{row.case_id} · {row.baseline.task_pass ? 'Pass' : 'Fail'} to {row.proposed.task_pass ? 'pass' : 'fail'}</summary>
          <p>Expected codes · {describe(row.expected_codes)}</p>
          {[['Baseline', row.baseline], ['Proposed', row.proposed]].map(([label, variant]) => <div key={label} className="my-2">
            <h4>{label}</h4>
            <p>{variant.answer}</p>
            <p className="muted">{variant.elapsed_ms} ms · {describe(variant.detected_codes)}</p>
            <ul className="list-disc pl-5">
              {variant.calls.map(call => <li key={call.id}>
                {call.tool}({call.arguments.topic}) · {call.error ?? call.output?.id}
              </li>)}
            </ul>
          </div>)}
        </details>)}
      </details>
      <details className="trace">
        <summary>Retrieval results by query</summary>
        <ul className="list-disc pl-5">
          {result.retrieval.map(row => <li className="my-2" key={row.fixture_id}>
            <p>{row.query}</p>
            <small>Expected · {row.expected_chunk ?? 'No result'}</small>
            <small>Keyword · {row.keyword.join(', ') || 'No result'}</small>
            <small>Active · {row.active.join(', ') || 'No result'}</small>
          </li>)}
        </ul>
      </details>
    </div>}
  </section>
}
