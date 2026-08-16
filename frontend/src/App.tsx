import { useState } from 'react'
import { api } from './api'
import type { ChatMessage, EditProposal, Finding, Paper } from './types'
import ChatPanel from './components/ChatPanel'
import CitationModal from './components/CitationModal'
import CiteText from './components/CiteText'
import EditPanel from './components/EditPanel'
import ReferencesPanel from './components/ReferencesPanel'
import ReviewPanel from './components/ReviewPanel'
import UploadScreen from './components/UploadScreen'
import BrandMark from './components/BrandMark'
import './App.css'

type Tab = 'parse' | 'review' | 'edit' | 'ask'

function yearFromFilename(name: string): string {
  const m = name.match(/(?:^|[^\d])(\d{2})\d{2}\.\d{4,5}/)
  if (!m) return ''
  const yy = parseInt(m[1], 10)
  return String(yy >= 90 ? 1900 + yy : 2000 + yy)
}

const ICONS = {
  file: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  ),
  pages: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M2 6s1.5-2 5-2 5 2 5 2v14s-1.5-1-5-1-5 1-5 1V6z" />
      <path d="M12 6s1.5-2 5-2 5 2 5 2v14s-1.5-1-5-1-5 1-5 1V6z" />
    </svg>
  ),
  layout: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <line x1="9.5" y1="4" x2="9.5" y2="20" />
      <line x1="14.5" y1="4" x2="14.5" y2="20" />
    </svg>
  ),
  year: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  ),
} as const

function MetaChip({ icon, label }: { icon: keyof typeof ICONS; label: string }) {
  return (
    <span className="meta-chip">
      {ICONS[icon]}
      {label}
    </span>
  )
}

export default function App() {
  const [paper, setPaper] = useState<Paper | null>(null)
  const [tab, setTab] = useState<Tab>('parse')
  const [findings, setFindings] = useState<Finding[] | null>(null)
  const [proposals, setProposals] = useState<EditProposal[]>([])
  const [chat, setChat] = useState<ChatMessage[]>([])
  const [citeInfo, setCiteInfo] = useState<string[] | null>(null)
  const [busy, setBusy] = useState<'' | 'upload' | 'review' | 'edit' | 'decide' | 'chat' | 'verify'>('')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const setError = (key: string, message: string) =>
    setErrors((e) => ({ ...e, [key]: message }))

  const applyPaper = (p: Paper) => {
    setPaper(p)
    setFindings(p.findings ?? null)
    setProposals(p.proposals ?? [])
  }

  const upload = async (file: File) => {
    setBusy('upload'); setError('upload', '')
    try {
      const p = await api.upload(file)
      applyPaper(p); setChat([]); setTab('parse')
    } catch (e) {
      setError('upload', (e as Error).message)
    } finally { setBusy('') }
  }

  const runReview = async () => {
    if (!paper) return
    setBusy('review'); setError('review', '')
    try {
      const r = await api.runReview(paper.id)
      setFindings(r.findings)
      setPaper(await api.getPaper(paper.id))
    } catch (e) {
      setError('review', (e as Error).message)
    } finally { setBusy('') }
  }

  const proposeEdit = async (command: string) => {
    if (!paper) return
    setBusy('edit'); setError('edit', '')
    try {
      const p = await api.proposeEdit(paper.id, command)
      setProposals((ps) => [...ps, p])
    } catch (e) {
      setError('edit', (e as Error).message)
    } finally { setBusy('') }
  }

  const decide = async (proposalId: string, decision: 'approve' | 'reject' | 'undo') => {
    if (!paper) return
    setBusy('decide'); setError('edit', '')
    try {
      const updated = await api.decide(paper.id, proposalId, decision)
      setProposals((ps) => ps.map((p) => (p.id === proposalId ? updated : p)))
      if (decision !== 'reject') setPaper(await api.getPaper(paper.id))
    } catch (e) {
      setError('edit', (e as Error).message)
    } finally { setBusy('') }
  }

  const ask = async (question: string) => {
    if (!paper) return
    const history = chat.map((m) => ({ role: m.role, content: m.content }))
    setChat((c) => [...c, { role: 'user', content: question }])
    setBusy('chat'); setError('chat', '')
    try {
      const r = await api.chat(paper.id, question, history)
      setChat((c) => [...c, {
        role: 'assistant', content: r.answer, answered: r.answered,
        sources: r.sources, cited_refs: r.cited_refs, warning: r.warning,
      }])
    } catch (e) {
      setError('chat', (e as Error).message)
    } finally { setBusy('') }
  }

  const exportFile = async (format: 'latex' | 'bib') => {
    if (!paper) return
    setError('export', '')
    try {
      const content = await api.export(paper.id, format)
      const blob = new Blob([content], { type: 'text/plain' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      const base = paper.filename.replace(/\.pdf$/i, '')
      a.download = format === 'latex' ? `${base}-revised.tex` : `${base}.bib`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      setError('export', (e as Error).message)
    }
  }

  const retryVerify = async () => {
    if (!paper) return
    setBusy('verify'); setError('parse', '')
    try {
      applyPaper(await api.retryVerify(paper.id))
    } catch (e) {
      setError('parse', (e as Error).message)
    } finally { setBusy('') }
  }

  const setStyle = async (style: string) => {
    if (!paper) return
    setError('export', '')
    try {
      setPaper(await api.setStyle(paper.id, style))
    } catch (e) {
      setError('export', (e as Error).message)
    }
  }

  if (!paper) {
    return <UploadScreen onUpload={upload} busy={busy === 'upload'} error={errors.upload ?? ''} />
  }

  const problemCount = (findings ?? []).filter((f) => f.kind !== 'info').length
  const pendingCount = proposals.filter((p) => p.status === 'pending').length
  const year = paper.year || yearFromFilename(paper.filename)

  return (
    <div className="app">
      <header>
        <div className="header-identity">
          <BrandMark />
          <span className="header-divider" aria-hidden />
          <div className="paper-title-bar">{paper.title || paper.filename}</div>
        </div>
        <div className="header-actions">
          <label className="style-picker">
            Citation style{' '}
            <select value={paper.style} onChange={(e) => setStyle(e.target.value)}>
              <option value="ieee">IEEE</option>
              <option value="apa">APA</option>
            </select>
          </label>
          <button className="primary" onClick={() => exportFile('latex')}>Export LaTeX</button>
          <button onClick={() => exportFile('bib')}>.bib</button>
          <button className="ghost" onClick={() => setPaper(null)}>New paper</button>
        </div>
      </header>
      {errors.export && <div className="error-banner">{errors.export}</div>}

      <div className="columns">
        <main className="paper-pane">
          <div className="paper-header">
            <h1 className="paper-title">{paper.title || paper.filename}</h1>
            <div className="meta-chips">
              <MetaChip icon="file" label={paper.filename} />
              {paper.page_count ? (
                <MetaChip
                  icon="pages"
                  label={`${paper.page_count} ${paper.page_count === 1 ? 'page' : 'pages'}`}
                />
              ) : null}
              {paper.layout ? <MetaChip icon="layout" label={paper.layout} /> : null}
              {year ? <MetaChip icon="year" label={year} /> : null}
            </div>
          </div>
          {paper.abstract && (
            <section id="paper-abstract">
              <h2>Abstract</h2>
              <p><CiteText text={paper.abstract} bibliography={paper.rendered.bibliography} onCite={setCiteInfo} /></p>
            </section>
          )}
          {paper.sections.map((s) => (
            <section key={s.id} id={`paper-${s.id}`} className={s.level > 1 ? `level-${s.level}` : undefined}>
              <h2>{s.title}</h2>
              <p><CiteText text={s.text} bibliography={paper.rendered.bibliography} onCite={setCiteInfo} /></p>
            </section>
          ))}
        </main>

        <aside className="side-pane">
          <nav className="tabs">
            <button className={tab === 'parse' ? 'active' : ''} onClick={() => setTab('parse')}>
              Parse
            </button>
            <button className={tab === 'review' ? 'active' : ''} onClick={() => setTab('review')}>
              Review{problemCount > 0 && <span className="pill">{problemCount}</span>}
            </button>
            <button className={tab === 'edit' ? 'active' : ''} onClick={() => setTab('edit')}>
              Edit{pendingCount > 0 && <span className="pill">{pendingCount}</span>}
            </button>
            <button className={tab === 'ask' ? 'active' : ''} onClick={() => setTab('ask')}>
              Ask
            </button>
          </nav>
          {tab === 'parse' && (
            <>
              {errors.parse && <div className="error-banner">{errors.parse}</div>}
              <ReferencesPanel
                paper={paper}
                onRetryVerify={retryVerify}
                verifying={busy === 'verify'}
              />
            </>
          )}
          {tab === 'review' && (
            <ReviewPanel
              paper={paper}
              findings={findings}
              busy={busy === 'review'}
              error={errors.review ?? ''}
              onRun={runReview}
            />
          )}
          {tab === 'edit' && (
            <EditPanel
              paper={paper}
              proposals={proposals}
              busy={busy === 'edit' || busy === 'decide'}
              error={errors.edit ?? ''}
              onCommand={proposeEdit}
              onDecide={decide}
            />
          )}
          {tab === 'ask' && (
            <ChatPanel
              paper={paper}
              messages={chat}
              busy={busy === 'chat'}
              error={errors.chat ?? ''}
              onAsk={ask}
            />
          )}
        </aside>
      </div>
      {citeInfo && (
        <CitationModal
          paper={paper}
          refIds={citeInfo}
          findings={findings}
          onClose={() => setCiteInfo(null)}
        />
      )}
    </div>
  )
}
