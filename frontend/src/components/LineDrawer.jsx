import { useEffect, useState } from 'react'
import { api } from '../api'
import { StatusBadge, money } from '../status'

const FIELDS = [
  ['material', 'Material'],
  ['grade', 'Grade'],
  ['form', 'Form'],
  ['thickness_in', 'Thickness (in)'],
  ['gauge', 'Gauge'],
  ['width_in', 'Width (in)'],
  ['length_in', 'Length (in)'],
  ['quantity', 'Quantity'],
  ['unit', 'Unit'],
  ['standard', 'Standard'],
  ['finish', 'Finish'],
]

const COMPLIANCE_STYLE = {
  PRESENT: 'bg-emerald-100 text-emerald-800',
  MISSING: 'bg-rose-100 text-rose-800',
  UNKNOWN: 'bg-amber-100 text-amber-800',
}

function Section({ title, children }) {
  return (
    <section className="border-t border-slate-200 px-5 py-4">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </section>
  )
}

function List({ items, className = 'text-slate-700' }) {
  if (!items?.length) return null
  return (
    <ul className={`list-disc space-y-1 pl-5 text-sm ${className}`}>
      {items.map((t, i) => (
        <li key={i}>{t}</li>
      ))}
    </ul>
  )
}

export default function LineDrawer({ rfqId, line, onClose, onClarify, onApprove, busy }) {
  const [answer, setAnswer] = useState('')
  const [reviewer, setReviewer] = useState('reviewer')
  useEffect(() => setAnswer(''), [line?.line_number])

  if (!line) return null
  const n = line.normalized
  const v = line.validation
  const m = line.match
  const p = line.pricing
  const c = line.compliance
  const canAnswer = ['NEEDS_CLARIFICATION', 'NO_COMPATIBLE_MATCH', 'PARSER_REVIEW'].includes(line.status)

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside
        onClick={(e) => e.stopPropagation()}
        className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-xl"
      >
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-slate-200 bg-white px-5 py-4">
          <div>
            <div className="text-xs text-slate-500">Line {line.line_number}</div>
            <div className="mt-1">
              <StatusBadge status={line.status} />
            </div>
            <p className="mt-2 text-sm text-slate-700">{line.status_reason}</p>
          </div>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            ✕
          </button>
        </header>

        {n?.guardrail_flags?.length > 0 && (
          <Section title="Input guardrail">
            <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
              <p className="font-semibold">This line was not sent to the LLM and will not be auto-quoted.</p>
              <List items={n.guardrail_flags} className="mt-1 text-rose-800" />
            </div>
          </Section>
        )}

        <Section title="Buyer's original wording (never modified)">
          <p className="rounded bg-slate-100 p-3 font-mono text-sm text-slate-900">{line.original_text}</p>
          {n?.notes && <p className="mt-2 text-sm text-indigo-700">{n.notes}</p>}
        </Section>

        {line.clarification_question && (
          <Section title="Question for the buyer">
            <pre className="whitespace-pre-wrap rounded border border-amber-200 bg-amber-50 p-3 font-sans text-sm text-amber-900">
              {line.clarification_question}
            </pre>
          </Section>
        )}

        {canAnswer && (
          <Section title="Enter the buyer's answer and reprocess">
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              rows={2}
              placeholder='e.g. "Sheet, 2B finish" or "316L, 0.060 in"'
              className="w-full rounded-lg border border-slate-300 p-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <p className="mt-1 text-xs text-slate-500">
              Fields stated in the answer override the original; everything else is kept. The original wording stays as it was.
            </p>
            <button
              disabled={busy || !answer.trim()}
              onClick={() => onClarify(line.line_number, answer)}
              className="mt-2 rounded-lg bg-amber-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-amber-400 disabled:opacity-50"
            >
              Apply answer & reprocess
            </button>
          </Section>
        )}

        {line.clarification_history?.length > 0 && (
          <Section title="Clarification history">
            {line.clarification_history.map((h, i) => (
              <div key={i} className="mb-2 text-sm">
                <span className="text-slate-500">{h.timestamp}</span> — answer: <b>{h.answer}</b>
                {Object.keys(h.fields_changed || {}).length > 0 && (
                  <span className="text-slate-600">
                    {' '}
                    (changed: {Object.entries(h.fields_changed).map(([k, d]) => `${k} ${d.from ?? '∅'} → ${d.to}`).join(', ')})
                  </span>
                )}
              </div>
            ))}
          </Section>
        )}

        {n && (
          <Section title="Normalized fields">
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
              {FIELDS.map(([k, label]) => (
                <div key={k} className="flex justify-between gap-2 border-b border-slate-100 py-1">
                  <span className="text-slate-500">{label}</span>
                  {n[k] != null ? (
                    <span className="font-medium text-slate-900">{String(n[k])}</span>
                  ) : (
                    <span className="italic text-slate-400">unknown</span>
                  )}
                </div>
              ))}
            </div>
            <List items={n.extraction_warnings} className="mt-3 text-amber-700" />
          </Section>
        )}

        {v && (v.missing_required_fields.length > 0 || v.contradictions.length > 0 || v.dimension_warnings.length > 0) && (
          <Section title="Validation">
            {v.missing_required_fields.length > 0 && (
              <p className="text-sm text-rose-700">Missing required: {v.missing_required_fields.join(', ')}</p>
            )}
            <List items={v.contradictions} className="text-rose-700" />
            <List items={v.dimension_warnings} className="text-amber-700" />
          </Section>
        )}

        {m && (
          <Section title="Catalog match: hard filters first, then fuzzy ranking">
            <p className="text-sm text-slate-700">{m.hard_filter_reason}</p>
            {m.matched_item && (
              <div className="mt-2 rounded border border-emerald-200 bg-emerald-50 p-3 text-sm">
                <div className="font-mono font-semibold text-emerald-900">{m.matched_sku}</div>
                <div className="text-emerald-800">
                  {m.matched_item.material} {m.matched_item.grade} {m.matched_item.form} · {m.matched_item.thickness_in}" ·{' '}
                  {m.matched_item.width_in}" × {m.matched_item.length_in}" · {m.matched_item.finish} · {m.matched_item.supplier} ·{' '}
                  {m.matched_item.stock_status}
                </div>
                <div className="mt-1 text-xs text-emerald-700">
                  Confidence {m.match_confidence} · text similarity {m.fuzzy_score} (used for ranking only)
                </div>
              </div>
            )}
            <List items={m.match_notes} className="mt-2 text-slate-700" />
            {m.alternatives?.length > 0 && (
              <p className="mt-2 text-xs text-slate-500">Also passed hard filters: {m.alternatives.join(', ')}</p>
            )}
            {m.rejection_reasons?.length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer text-sm font-medium text-rose-700">
                  Rejected by hard filters ({m.rejected_skus.length} similar SKUs)
                </summary>
                <List items={m.rejection_reasons} className="mt-1 font-mono text-xs text-rose-800" />
              </details>
            )}
          </Section>
        )}

        {p && (p.priced || p.price_unverified) && (
          <Section title="Price and calculation">
            {p.priced && (
              <div className="mb-2 grid grid-cols-3 gap-2 text-center">
                <div className="rounded bg-slate-100 p-2">
                  <div className="text-xs text-slate-500">Unit price</div>
                  <div className="font-semibold">{money(p.unit_price)}</div>
                </div>
                <div className="rounded bg-slate-100 p-2">
                  <div className="text-xs text-slate-500">Line total</div>
                  <div className="font-semibold">{money(p.total_price)}</div>
                </div>
                <div className="rounded bg-slate-100 p-2">
                  <div className="text-xs text-slate-500">Margin</div>
                  <div className="font-semibold">{p.margin_pct}%</div>
                </div>
              </div>
            )}
            {p.benchmark_price != null && p.price_per_lb != null && (
              <BenchmarkBar low={p.benchmark_low} mid={p.benchmark_price} high={p.benchmark_high} ours={p.price_per_lb} cost={p.cost_per_lb} />
            )}
            <p className="mt-2 text-sm text-slate-700">{p.price_rationale}</p>
            {p.calculation_steps?.length > 0 && (
              <ol className="mt-2 list-decimal space-y-0.5 pl-5 font-mono text-xs text-slate-600">
                {p.calculation_steps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            )}
            <List items={p.price_warnings} className="mt-2 text-amber-700" />
          </Section>
        )}

        {c && c.requirements.length > 0 && (
          <Section title="Compliance: never claimed without evidence">
            <div className="space-y-2">
              {c.requirements.map((r, i) => (
                <div key={i} className="rounded border border-slate-200 p-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-900">{r.requirement}</span>
                    <span className="flex items-center gap-2">
                      <span className="text-xs text-slate-500">{r.required ? 'required' : 'informational'}</span>
                      <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${COMPLIANCE_STYLE[r.status]}`}>{r.status}</span>
                    </span>
                  </div>
                  {r.evidence && <div className="mt-1 text-xs text-slate-700">Evidence: {r.evidence}</div>}
                  {r.notes && <div className="mt-0.5 text-xs text-slate-500">{r.notes}</div>}
                </div>
              ))}
            </div>
          </Section>
        )}

        <PrismEvaluation rfqId={rfqId} line={line} />

        {line.status === 'READY_FOR_REVIEW' && (
          <Section title="Human approval">
            {line.approved ? (
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-emerald-700">✓ Approved by {line.approved_by}</span>
                <button
                  disabled={busy}
                  onClick={() => onApprove(line.line_number, false, reviewer)}
                  className="text-sm text-slate-500 underline hover:text-slate-700"
                >
                  Revoke
                </button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                  className="rounded border border-slate-300 px-2 py-1.5 text-sm"
                  placeholder="Reviewer name"
                />
                <button
                  disabled={busy || !reviewer.trim()}
                  onClick={() => onApprove(line.line_number, true, reviewer)}
                  className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
                >
                  I reviewed this line, approve it
                </button>
              </div>
            )}
          </Section>
        )}
      </aside>
    </div>
  )
}

function PrismEvaluation({ rfqId, line }) {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => setResult(null), [line.line_number, line.prism_trajectory_id])

  const load = async () => {
    setLoading(true)
    try {
      setResult(await api.evaluation(rfqId, line.line_number))
    } catch (e) {
      setResult({ available: false, message: e.message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <Section title="PRISM evaluator (Block Convey)">
      <p className="text-xs text-slate-500">
        This line's full run (extract, LLM fill, validate, match, price, compliance, status) is sent to PRISM as a
        trajectory. The Evaluator re-checks the status decision independently.
      </p>
      <button
        onClick={load}
        disabled={loading}
        className="mt-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
      >
        {loading ? 'Checking…' : 'Get evaluator verdict'}
      </button>
      {result && (
        <div className="mt-2 text-sm">
          {result.available ? (
            <pre className="max-h-64 overflow-auto rounded bg-slate-100 p-2 text-xs text-slate-800">
              {JSON.stringify(result.evaluation, null, 2)}
            </pre>
          ) : (
            <p className="text-slate-600">{result.message}</p>
          )}
          {result.trajectory_id && <p className="mt-1 font-mono text-xs text-slate-400">trajectory {result.trajectory_id}</p>}
        </div>
      )}
    </Section>
  )
}

function BenchmarkBar({ low, mid, high, ours, cost }) {
  const min = Math.min(low, cost ?? low, ours) * 0.95
  const max = Math.max(high, ours) * 1.05
  const pct = (v) => `${((v - min) / (max - min)) * 100}%`
  return (
    <div className="mt-1">
      <div className="relative h-8">
        <div className="absolute top-3 h-2 rounded bg-sky-200" style={{ left: pct(low), width: `calc(${pct(high)} - ${pct(low)})` }} />
        <div className="absolute top-2 h-4 w-0.5 bg-sky-600" style={{ left: pct(mid) }} title="Market midpoint" />
        {cost != null && <div className="absolute top-2 h-4 w-0.5 bg-slate-400" style={{ left: pct(cost) }} title="Cost" />}
        <div className="absolute top-1 h-6 w-1 rounded bg-indigo-600" style={{ left: pct(ours) }} title="Our price" />
      </div>
      <div className="flex flex-wrap gap-x-4 text-xs text-slate-600">
        <span><span className="mr-1 inline-block h-2 w-3 rounded bg-sky-200" />market ${low}–${high}/lb</span>
        <span><span className="mr-1 inline-block h-3 w-0.5 bg-sky-600" />midpoint ${mid}/lb</span>
        {cost != null && <span><span className="mr-1 inline-block h-3 w-0.5 bg-slate-400" />cost ${cost}/lb</span>}
        <span className="font-semibold text-indigo-700"><span className="mr-1 inline-block h-3 w-1 bg-indigo-600" />ours ${ours}/lb</span>
      </div>
    </div>
  )
}
