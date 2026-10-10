import { useEffect, useState } from 'react'
import { api } from './api'
import { money } from './status'
import InputPanel from './components/InputPanel'
import QuoteTable, { SummaryBar } from './components/QuoteTable'
import LineDrawer from './components/LineDrawer'
import AuditPanel from './components/AuditPanel'

export default function App() {
  const [health, setHealth] = useState(null)
  const [rfq, setRfq] = useState(null)
  const [selected, setSelected] = useState(null)
  const [filter, setFilter] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [showAudit, setShowAudit] = useState(false)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setError('Backend not reachable. Start it with: uvicorn main:app --port 8000'))
  }, [])

  const update = (next) => {
    setRfq(next)
    setVersion((v) => v + 1)
  }

  const act = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      update(await fn())
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const line = rfq?.lines.find((l) => l.line_number === selected)
  const lines = rfq ? rfq.lines.filter((l) => !filter || l.status === filter) : []

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-4">
          <div>
            <h1 className="text-xl font-bold text-slate-900">
              QuoteWise <span className="text-indigo-600">AI</span>
            </h1>
            <p className="text-sm text-slate-500">Messy RFQ → traceable draft quote. Stops and asks when it isn't sure.</p>
          </div>
          {health && (
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded bg-slate-100 px-2 py-1 text-slate-600">LLM: {health.llm_gap_fill}</span>
              <span className="rounded bg-slate-100 px-2 py-1 text-slate-600">PRISM: {health.prism}</span>
            </div>
          )}
        </div>
        <div className="bg-amber-50 px-4 py-1.5 text-center text-xs font-medium text-amber-800">
          DEMO DATA: all catalog items, prices and benchmarks are synthetic. Every quote is a DRAFT and needs human approval.
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-5 px-4 py-6">
        <InputPanel onResult={(r) => { update(r); setSelected(null); setFilter(null) }} busy={busy} setBusy={setBusy} setError={setError} />

        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>
        )}

        {rfq && (
          <section className="space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-slate-900">2. Review the draft quote</h2>
                <p className="text-sm text-slate-500">
                  RFQ {rfq.rfq_id} · {rfq.filename || rfq.input_type} · LLM {rfq.llm_used ? 'used' : 'not used'} · click a line to
                  see evidence, answer questions, and approve.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => setShowAudit(true)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                  Audit trail
                </button>
                <button onClick={() => api.exportFile(rfq.rfq_id, 'json').catch((e) => setError(e.message))} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                  Export JSON
                </button>
                <button onClick={() => api.exportFile(rfq.rfq_id, 'pdf').catch((e) => setError(e.message))} className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-700">
                  Export DRAFT PDF
                </button>
              </div>
            </div>

            {rfq.pipeline_warnings?.map((w, i) => (
              <div key={i} className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-2 text-sm text-sky-800">{w}</div>
            ))}

            <SummaryBar rfq={rfq} filter={filter} setFilter={setFilter} />
            <QuoteTable lines={lines} onSelect={setSelected} selected={selected} />

            <div className="flex flex-wrap justify-end gap-6 rounded-xl border border-slate-200 bg-white px-5 py-3 text-sm">
              <span className="text-slate-600">
                Ready lines total: <b className="text-slate-900">{money(rfq.summary.quotable_total)}</b> ({rfq.summary.ready_lines} lines)
              </span>
              <span className="text-slate-600">
                Human-approved total: <b className="text-emerald-700">{money(rfq.summary.approved_total)}</b> ({rfq.summary.approved_lines} lines)
              </span>
            </div>
          </section>
        )}
      </main>

      <LineDrawer
        rfqId={rfq?.rfq_id}
        line={line}
        busy={busy}
        onClose={() => setSelected(null)}
        onClarify={(n, answer) => act(() => api.clarify(rfq.rfq_id, n, answer))}
        onApprove={(n, approved, reviewer) => act(() => api.approve(rfq.rfq_id, n, approved, reviewer))}
      />
      {showAudit && rfq && <AuditPanel rfqId={rfq.rfq_id} version={version} onClose={() => setShowAudit(false)} />}
    </div>
  )
}
