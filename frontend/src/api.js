async function request(path, options = {}) {
  const res = await fetch(path, options)
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch {}
    throw new Error(detail)
  }
  return res
}

const json = (path, body) =>
  request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json())

export const api = {
  health: () => request('/api/health').then((r) => r.json()),
  sample: () => request('/api/sample').then((r) => r.json()),
  submitText: (text, useLlm) => json('/api/rfq/text', { text, use_llm: useLlm }),
  upload: (file, useLlm) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('use_llm', useLlm ? 'true' : 'false')
    return request('/api/rfq/upload', { method: 'POST', body: fd }).then((r) => r.json())
  },
  clarify: (id, line, answer) => json(`/api/rfq/${id}/lines/${line}/clarify`, { answer }),
  approve: (id, line, approved, reviewer) =>
    json(`/api/rfq/${id}/lines/${line}/approve`, { approved, reviewer }),
  audit: (id) => request(`/api/rfq/${id}/audit`).then((r) => r.json()),
  evaluation: (id, line) => request(`/api/rfq/${id}/lines/${line}/evaluation`).then((r) => r.json()),
  exportFile: async (id, format) => {
    const res = await request(`/api/rfq/${id}/export?format=${format}`)
    const blob =
      format === 'pdf'
        ? await res.blob()
        : new Blob([JSON.stringify(await res.json(), null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `DRAFT_quote_${id}.${format}`
    a.click()
    URL.revokeObjectURL(url)
  },
}
