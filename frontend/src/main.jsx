import React, { useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import EvaluationPanel from './EvaluationPanel'
import './styles.css'

import { requestApi } from './apiClient.js'

function App({ api, role, signOut }) {
  const canRun = role !== "viewer"
  const [cases, setCases] = useState([])
  const [caseId, setCaseId] = useState('')
  const [runs, setRuns] = useState([])
  const [incidentsOnly, setIncidentsOnly] = useState(false)
  const [selected, setSelected] = useState(null)
  const [report, setReport] = useState(null)
  const [review, setReview] = useState(null)
  const [geminiConfigured, setGeminiConfigured] = useState(false)
  const [provider, setProvider] = useState('deterministic')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const flagged = runs.filter(run => run.status === 'flagged').length
  const visibleRuns = incidentsOnly ? runs.filter(run => run.status === "flagged") : runs

  useEffect(() => {
    Promise.all([api('/cases'), api('/runs'), api('/capabilities')]).then(([available, history, capabilities]) => {
      setGeminiConfigured(capabilities.gemini_configured)
      setCases(available)
      setCaseId(available.find(item => item.id === 'hallucinated')?.id ?? available[0]?.id ?? '')
      setRuns(history)
      setSelected(history[0] ?? null)
    }).catch(err => setError(err.message))
  }, [api])

  function inspect(run) {
    setSelected(run)
    setReport(null)
    setReview(null)
    setError('')
  }

  async function runSample(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const run = await api('/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_id: provider === 'gemini' ? 'successful' : caseId, provider }),
      })
      setRuns(previous => [run, ...previous])
      inspect(run)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function openReport() {
    setBusy(true)
    setError('')
    try {
      const path = '/runs/' + selected.id
      const [investigation, proposal] = await Promise.all([
        api(path + '/investigation'), api(path + '/review'),
      ])
      setReport(investigation)
      setReview(proposal)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function recordDecision(outcome) {
    setBusy(true)
    setError('')
    try {
      setReview(await api('/runs/' + selected.id + '/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome }),
      }))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return <>
    <header className="masthead">
      <div className="shell masthead-inner">
        <a className="brand" href="#dashboard">
          <span className="brand-mark" aria-hidden="true">✳</span>
          Reliability dashboard
        </a>

        <div className="flex items-center gap-3">
          <a className="section-link" href="#evaluations">Evaluations</a>
          {signOut && <button className="secondary" type="button" onClick={signOut}>Sign out</button>}
        </div>
      </div>
    </header>
    <main id="dashboard" className="shell dashboard">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Agent reliability lab</p>
          <h1>Error Dodge</h1>
          <p>Run a support case, trace what went wrong, and test a proposed fix.</p>
        </div>
        <div className="radar" aria-hidden="true"><span></span></div>
      </section>
      <section aria-label="Run statistics" className="metric-grid">
        {[
          ['Total runs', runs.length, 'total', '≡'],
          ['No issues detected', runs.length - flagged, 'clean', '✓'],
          ['Flagged runs', flagged, 'flagged', '!'],
        ].map(([label, value, tone, symbol]) =>
          <div className={`metric ${tone}`} key={label}>
            <span className="metric-symbol" aria-hidden="true">{symbol}</span>
            <p>{label}</p><strong>{value}</strong>
          </div>)}
      </section>
      <details className="panel demo-guide">
        <summary>Guided demo</summary>
        <ol className="list-decimal pl-5">
          <li>Run <strong>Incorrect refund window</strong> and expand the lookup trace.</li>
          <li>Open the investigation and follow the citation to the seven-day policy.</li>
          <li>Run the benchmark to compare the proposal against the synthetic cases.</li>
          <li>Review the proposal. The decision is saved with the run.</li>
        </ol>
      </details>
      <div className="workspace">
        <aside className="grid min-w-0 gap-5">
        <form className="panel run-form grid gap-3" onSubmit={runSample}>
          <h2>Run a case</h2>
          {geminiConfigured && <div>
            <label htmlFor="provider">Agent provider</label>
            <select id="provider" value={provider} disabled={busy} onChange={event => setProvider(event.target.value)}>
              <option value="deterministic">Deterministic demo</option>
              <option value="gemini">Gemini</option>
            </select>
          </div>}
          <label htmlFor="sample">Sample case</label>
          <select id="sample" value={provider === 'gemini' ? 'successful' : caseId} disabled={busy || !cases.length || provider === 'gemini'} onChange={event => setCaseId(event.target.value)}>
            {!cases.length && <option value="">No cases loaded</option>}
            {cases.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}
          </select>
          <button className="primary" disabled={busy || !caseId || !canRun}>Run sample</button>
        </form>
        <section className="panel">
          <div className="history-heading">
            <h2>Execution history</h2>
            <button type="button" className="secondary" aria-pressed={incidentsOnly}
              onClick={() => setIncidentsOnly(value => !value)}>Incidents only</button>
          </div>
          {!visibleRuns.length && <p className="muted">{incidentsOnly ? "No flagged runs." : "No runs recorded."}</p>}
          <ul className="history-list grid gap-2">
            {visibleRuns.map(run => <li key={run.id}>
              <button className="history" disabled={busy} aria-pressed={selected?.id === run.id} onClick={() => inspect(run)}>
                {cases.find(item => item.id === run.case_id)?.name ?? run.case_id}
                <small>{run.status === 'flagged' ? 'Flagged' : 'No issues detected'} · {new Date(run.created_at).toLocaleTimeString()}</small>
              </button>
            </li>)}
          </ul>
        </section>
      </aside>
      <div className="grid min-w-0 gap-5" aria-busy={busy}>
        {error && <p className="error" role="alert">{error}</p>}
        {busy && <p role="status">Request in progress…</p>}
        {!selected && <section className="panel"><h2>Execution detail</h2><p className="muted">Run a sample to see its answer and tool trace.</p></section>}
        {selected && <section className="panel grid gap-4">
          <div className="detail-heading">
            <div><h2>Execution detail</h2><p className="muted run-id">{selected.id} · {selected.provider} · {selected.detector ?? "phase4"}</p></div>
            <span className={`status ${selected.status === 'flagged' ? 'flagged' : 'clean'}`}>
              {selected.status === 'flagged' ? 'Flagged' : 'No issues detected'}
            </span>
          </div>
          <div><h3>Customer question</h3><p>{selected.question}</p></div>
          <div className="answer"><h3>Agent answer</h3><p>{selected.answer}</p></div>
          <div><h3>Tool-call trace</h3>
            {!selected.calls.length && <p className="muted">No tool calls recorded.</p>}
            {selected.calls.map(call => <details className="trace" key={call.id}>
              <summary>{call.id} · {call.tool}({call.arguments.topic}) · {call.error ? 'Error' : 'Returned'}</summary>
              {call.error ? <p className="error">{call.error}</p> : <p>{call.output?.title} [{call.output?.id}] — {call.output?.text}</p>}
            </details>)}
          </div>
          <div className={selected.findings.length ? "finding" : ""}><h3>Detected issues</h3>
            {selected.findings.length ? <ul className="list-disc pl-5">{selected.findings.map((finding, index) =>
              <li key={index}>{finding.detail}</li>)}</ul> : <p className="muted">No issues detected by the current checks.</p>}
          </div>
          {!!selected.findings.length && !report && <button className="primary justify-self-start" disabled={busy} onClick={openReport}>Open investigation</button>}
        </section>}
        {report && <section className="panel grid gap-4" aria-label="Investigation report">
          <h2>Investigation report</h2>
          <div><h3>{report.support?.length ? "Findings and support" : "Verified findings"}</h3><ul className="list-disc pl-5">
            {report.findings.map((finding, index) => <li key={index}>
              {finding.detail} {finding.source_ids.map(id => <a className="citation" key={id} href={'#source-' + id}>[{id}]</a>)}
              {report.support?.[index] && <div className="trace">
                <small>{report.support[index].status === 'insufficient' ? 'Unverified' :
                  report.support[index].status === 'policy_supported' ? 'Policy-supported' : 'Trace-supported'}</small>
                <p>{report.support[index].rationale}</p>
                {report.support[index].quote && <blockquote>{report.support[index].quote}</blockquote>}
              </div>}
              {finding.trace_ids.length > 0 && <small>Trace evidence · {finding.trace_ids.join(', ')}</small>}
            </li>)}
          </ul></div>
          {report.evidence_warning && <p className="finding">{report.evidence_warning}</p>}
          <div><h3>{report.support?.length ? "Approved policy documents" : "Policy evidence"}</h3>{report.evidence.map(source =>
            <article className="trace" key={source.id} id={'source-' + source.id}>
              <h4>{source.title} · v{source.version} [{source.id}]</h4>
              <blockquote>{source.text}</blockquote>
            </article>)}</div>
          {!!report.matches?.length && <div>
            <h3>Retrieved policy excerpts</h3>
            <p className="muted">{report.retrieval_mode === 'hybrid' ? 'Hybrid keyword and semantic search' : 'Keyword search'}</p>
            {report.matches.map(match => <article className="trace" key={match.chunk_id}>
              <h4><a className="citation" href={'#source-' + match.policy_id}>{match.chunk_id}</a></h4>
              <p>{match.excerpt}</p>
              <small>{[match.keyword && 'Keyword match', match.semantic && 'Semantic match'].filter(Boolean).join(' · ')}</small>
            </article>)}
          </div>}
          {!!report.related_runs?.length && <div>
            <h3>Related runs</h3>
            <ul className="grid gap-2">
              {report.related_runs.map(previous => <li key={previous.id}>
                <button className="history" disabled={busy || !runs.some(run => run.id === previous.id)}
                  onClick={() => inspect(runs.find(run => run.id === previous.id))}>
                  {previous.status === 'flagged' ? 'Flagged run' : 'Run with no detected issues'}
                  <small className="run-id">{previous.id}</small>
                </button>
              </li>)}
            </ul>
          </div>}
          <div><h3>Root-cause hypothesis</h3><p>{report.hypothesis}</p></div>
          <div><h3>Recommended improvement</h3><p>{report.recommendation}</p></div>
          {review && <div className="evaluation">
            <h3>Synthetic evaluation</h3>
            <dl className="evaluation-metrics">
              <div><dt>Baseline task passes</dt><dd>{review.evaluation.baseline_passes} of {review.evaluation.cases}</dd></div>
              <div><dt>Proposed task passes</dt><dd>{review.evaluation.proposed_passes} of {review.evaluation.cases}</dd></div>
            </dl>
            <p>Regressions · {review.evaluation.regressions.join(', ') || 'None observed'}</p>
            <h3 className="mt-4">Proposal review</h3>
            <p className="muted">A decision is saved to this run. The demo configuration stays separate.</p>
            {review.decision
              ? <p role="status" className="mt-2 capitalize">{review.decision.outcome} · {new Date(review.decision.recorded_at).toLocaleString()}</p>
              : role !== "reviewer" ? <p className="muted">A reviewer can record a decision.</p> : <div className="mt-2 flex flex-wrap gap-2">
                <button className="primary" disabled={busy} onClick={() => recordDecision('approved')}>Approve proposal</button>
                <button className="secondary" disabled={busy} onClick={() => recordDecision('rejected')}>Reject proposal</button>
              </div>}
          </div>}
        </section>}
      </div>
    </div>
    <EvaluationPanel api={api} canRun={canRun} incidentId={selected?.status === 'flagged' ? selected.id : null}
      incidentName={cases.find(item => item.id === selected?.case_id)?.name} />
  </main>
  </>
}

function AccessGate() {
  const [authRequired, setAuthRequired] = useState(null)
  const [draft, setDraft] = useState('')
  const [token, setToken] = useState('')
  const [role, setRole] = useState('reviewer')
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const api = useCallback((path, options) => requestApi(path, options, token), [token])

  useEffect(() => {
    requestApi('/access').then(info => setAuthRequired(info.authentication_required))
      .catch(err => setError(err.message))
  }, [])

  async function signIn(event) {
    event.preventDefault()
    setChecking(true)
    setError('')
    try {
      const session = await requestApi('/session', {}, draft.trim())
      setRole(session.role)
      setToken(draft.trim())
      setDraft('')
    } catch (err) {
      setError(err.message)
    } finally {
      setChecking(false)
    }
  }

  if (authRequired === false || token) {
    return <App api={api} role={role} signOut={authRequired ? () => setToken('') : null} />
  }
  return <main className="shell dashboard">
    <section className="panel max-w-md">
      <h1 className="text-4xl">Error Dodge</h1>
      {error && <p role="alert" className="error">{error}</p>}
      {authRequired === null && !error && <p role="status">Checking access…</p>}
      {authRequired && <form className="grid gap-3" onSubmit={signIn}>
        <label htmlFor="access-token">Workspace access token</label>
        <input className="access-token" id="access-token" type="password" autoComplete="off"
          required maxLength={2048} value={draft} onChange={event => setDraft(event.target.value)} />
        <button className="primary" disabled={checking}>Sign in</button>
      </form>}
    </section>
  </main>
}

createRoot(document.getElementById('root')).render(<AccessGate />)
