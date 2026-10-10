import { STATUS, StatusBadge, money } from '../status'

function spec(n) {
  if (!n) return null
  const parts = [n.material, n.grade, n.form]
  if (n.thickness_in) parts.push(`${n.thickness_in}"${n.gauge ? ` (${n.gauge})` : ''}`)
  if (n.width_in && n.length_in) parts.push(`${n.width_in}" × ${n.length_in}"`)
  if (n.finish) parts.push(n.finish)
  if (n.standard) parts.push(n.standard)
  return parts.filter(Boolean).join(' · ')
}

export function SummaryBar({ rfq, filter, setFilter }) {
  const counts = rfq.summary.counts
  return (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={() => setFilter(null)}
        className={`rounded-lg border px-3 py-2 text-left text-sm ${
          !filter ? 'border-indigo-500 bg-indigo-50' : 'border-slate-200 bg-white hover:border-slate-300'
        }`}
      >
        <div className="text-xs text-slate-500">All lines</div>
        <div className="text-lg font-semibold text-slate-900">{rfq.total_lines}</div>
      </button>
      {Object.keys(STATUS).map((s) => (
        <button
          key={s}
          onClick={() => setFilter(filter === s ? null : s)}
          disabled={!counts[s]}
          className={`rounded-lg border px-3 py-2 text-left text-sm disabled:opacity-40 ${
            filter === s ? 'border-indigo-500 bg-indigo-50' : 'border-slate-200 bg-white hover:border-slate-300'
          }`}
        >
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <span className={`h-1.5 w-1.5 rounded-full ${STATUS[s].dot}`} />
            {STATUS[s].label}
          </div>
          <div className="text-lg font-semibold text-slate-900">{counts[s]}</div>
        </button>
      ))}
    </div>
  )
}

export default function QuoteTable({ lines, onSelect, selected }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">Buyer's wording</th>
            <th className="px-3 py-2">Normalized spec</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">SKU</th>
            <th className="px-3 py-2 text-right">Qty</th>
            <th className="px-3 py-2 text-right">Unit price</th>
            <th className="px-3 py-2 text-right">Total</th>
            <th className="px-3 py-2">Approved</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lines.map((l) => {
            const priced = l.status === 'READY_FOR_REVIEW' && l.pricing?.priced
            return (
              <tr
                key={l.line_number}
                onClick={() => onSelect(l.line_number)}
                className={`cursor-pointer align-top hover:bg-indigo-50/50 ${
                  selected === l.line_number ? 'bg-indigo-50' : ''
                }`}
              >
                <td className="px-3 py-2 text-slate-400">{l.line_number}</td>
                <td className="max-w-xs px-3 py-2 font-mono text-xs text-slate-800">{l.original_text}</td>
                <td className="max-w-xs px-3 py-2 text-xs text-slate-600">{spec(l.normalized) || '—'}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={l.status} />
                </td>
                <td className="px-3 py-2 font-mono text-xs text-slate-600">{l.match?.matched_sku || '—'}</td>
                <td className="px-3 py-2 text-right text-slate-700">
                  {l.normalized?.quantity != null ? `${l.normalized.quantity} ${l.pricing?.unit || l.normalized.unit || ''}` : '—'}
                </td>
                <td className="px-3 py-2 text-right text-slate-700">{priced ? money(l.pricing.unit_price) : '—'}</td>
                <td className="px-3 py-2 text-right font-medium text-slate-900">
                  {priced ? money(l.pricing.total_price) : '—'}
                </td>
                <td className="px-3 py-2">
                  {l.approved ? (
                    <span className="text-xs font-semibold text-emerald-700">✓ {l.approved_by}</span>
                  ) : (
                    <span className="text-xs text-slate-400">—</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
