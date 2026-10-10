import { useRef, useState } from 'react'
import { api } from '../api'

const ACCEPT = '.txt,.eml,.pdf,.csv,.xlsx,.xls,.png,.jpg,.jpeg,.webp'

export default function InputPanel({ onResult, busy, setBusy, setError }) {
  const [text, setText] = useState('')
  const [useLlm, setUseLlm] = useState(true)
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef(null)

  const run = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      onResult(await fn())
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const loadSample = async () => setText((await api.sample()).text)
  const submitText = () => text.trim() && run(() => api.submitText(text, useLlm))
  const submitFile = (file) => file && run(() => api.upload(file, useLlm))

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-slate-900">1. Paste or upload an RFQ</h2>
        <button onClick={loadSample} className="text-sm font-medium text-indigo-600 hover:text-indigo-500">
          Load sample RFQ
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            placeholder={'Paste an email body or RFQ text, e.g.\n304 SS sheet 16ga 4x8, qty 10, MTRs required\nStainless 304, 0.060 in, 48 x 96 - 25 pcs'}
            className="w-full rounded-lg border border-slate-300 p-3 font-mono text-sm text-slate-800 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            submitFile(e.dataTransfer.files[0])
          }}
          onClick={() => fileRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 text-center transition ${
            dragging ? 'border-indigo-500 bg-indigo-50' : 'border-slate-300 hover:border-slate-400'
          }`}
        >
          <p className="text-sm font-medium text-slate-700">Drop a file or click to upload</p>
          <p className="mt-1 text-xs text-slate-500">PDF, XLSX, CSV, EML, TXT, or image</p>
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              submitFile(e.target.files[0])
              e.target.value = ''
            }}
          />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4">
        <button
          onClick={submitText}
          disabled={busy || !text.trim()}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? 'Processing…' : 'Build draft quote'}
        </button>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          Use LLM gap-filler (NicrronNinoo) for fields rules can't read
        </label>
      </div>
    </section>
  )
}
