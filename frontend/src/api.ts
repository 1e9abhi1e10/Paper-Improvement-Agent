import type { ChatSource, EditProposal, Finding, Paper } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init)
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = await resp.json()
      detail = body.detail ?? detail
    } catch { /* non-JSON error body */ }
    throw new Error(detail)
  }
  return resp.json() as Promise<T>
}

export const api = {
  upload(file: File): Promise<Paper> {
    const form = new FormData()
    form.append('file', file)
    return request('/api/papers', { method: 'POST', body: form })
  },
  getPaper(id: string): Promise<Paper> {
    return request(`/api/papers/${id}`)
  },
  setStyle(id: string, style: string): Promise<Paper> {
    return request(`/api/papers/${id}/style`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ style }),
    })
  },
  retryVerify(id: string): Promise<Paper> {
    return request(`/api/papers/${id}/verify`, { method: 'POST' })
  },
  runReview(id: string): Promise<{ findings: Finding[] }> {
    return request(`/api/papers/${id}/review`, { method: 'POST' })
  },
  proposeEdit(id: string, command: string): Promise<EditProposal> {
    return request(`/api/papers/${id}/edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    })
  },
  decide(id: string, proposalId: string, decision: 'approve' | 'reject' | 'undo'): Promise<EditProposal> {
    return request(`/api/papers/${id}/proposals/${proposalId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    })
  },
  chat(id: string, question: string, history: { role: string; content: string }[]): Promise<{
    answer: string
    answered: boolean
    sources: ChatSource[]
    cited_refs: string[]
    warning: string
  }> {
    return request(`/api/papers/${id}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history }),
    })
  },
  async export(id: string, format: 'latex' | 'bib'): Promise<string> {
    const resp = await fetch(`/api/papers/${id}/export?format=${format}`)
    if (!resp.ok) throw new Error('Export failed')
    return resp.text()
  },
}
