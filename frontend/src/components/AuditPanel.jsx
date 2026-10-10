import { useEffect, useState } from 'react'
import { api } from '../api'

export default function AuditPanel({ rfqId, version, onClose }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.audit(rfqId).then(setData).catch((e) => setError(e.message))
  }, [rfqId, version])

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside onClick={(e) => e.stopPropagation()} className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-xl">
        <header className="sticky top-0 flex items-start justify-between border-b border-slate-200 bg-white px-5 py-4">
          <div>
            <h2 className="font-semibold text-slate-900">Audit trail</h2>
            <p className="text-xs text-slate-500">
              Every pipeline decision, hash-chained (SHA-256). Editing any entry breaks the chain.
            </p>
            {data && (
              <p className={`mt-1 text-sm font-medium ${data.verification.valid ? 'text-emerald-700' : 'text-rose-700'}`}>
                {data.verification.valid
                  ? `✓ Chain verified, ${data.verification.entries} entries`
                  : `✗ Chain broken at entry ${data.verification.broken_at_seq}`}
              </p>
            )}
          </div>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100">✕</button>
        </header>
        {error && <p className="p-5 text-sm text-rose-700">{error}</p>}
        <ol className="divide-y divide-slate-100">
          {data?.entries.map((e) => (
            <li key={e.seq} className="px-5 py-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-slate-400">#{e.seq}</span>
                <span className="font-semibold text-slate-800">{e.event}</span>
                {e.line_number != null && <span className="text-slate-500">line {e.line_number}</span>}
                <span className="text-slate-400">{e.actor}</span>
                <span className="ml-auto text-slate-400">{e.timestamp}</span>
              </div>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-slate-600">{JSON.stringify(e.details)}</pre>
              <div className="mt-0.5 font-mono text-[10px] text-slate-400">
                {e.hash.slice(0, 16)}… ← {e.prev_hash.slice(0, 16)}…
              </div>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  )
}
