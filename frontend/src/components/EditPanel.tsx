import { useState } from 'react'
import type { EditProposal, Paper } from '../types'
import CiteText from './CiteText'
import ReferenceLink, { sectionTitle } from './ReferenceLink'

interface Props {
  paper: Paper
  proposals: EditProposal[]
  busy: boolean
  error: string
  onCommand: (command: string) => void
  onDecide: (proposalId: string, decision: 'approve' | 'reject' | 'undo') => void
}

function fmtTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const EXAMPLES = [
  'Add more citations to the introduction',
  'Make the introduction shorter',
  'Find citations that support the methodology',
]

function ProposalCard({ p, paper, undoable, onDecide }: {
  p: EditProposal
  paper: Paper
  undoable: boolean
  onDecide: Props['onDecide']
}) {
  const bib = paper.rendered.bibliography
  return (
    <div className="proposal">
      <div className="proposal-head">
        <code className="proposal-cmd">“{p.command}”</code>
        <span className="proposal-time">
          {p.status === 'applied' && p.applied_at ? `applied ${fmtTime(p.applied_at)}` : fmtTime(p.created_at)}
        </span>
        <span className={`badge badge-${p.status}`}>{p.status}</span>
      </div>
      {p.summary && <p className="hint">{p.summary}</p>}
      {p.warnings.map((w, i) => (
        <div key={i} className="warning-banner">{w}</div>
      ))}
      {p.diffs.map((d) => {
        return (
          <div key={d.section_id} className="diff">
            <div className="diff-title">{sectionTitle(paper.sections, d.section_id)}</div>
            <div className="diff-old">
              <div className="diff-label">before</div>
              <CiteText text={d.old_text} bibliography={bib} />
            </div>
            <div className="diff-new">
              <div className="diff-label">after</div>
              <CiteText text={d.new_text} bibliography={bib} />
            </div>
            {d.notes.length > 0 && (
              <div className="diff-notes">
                <div className="diff-label">what changed and why</div>
                <ul>
                  {d.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              </div>
            )}
          </div>
        )
      })}
      {p.new_references.length > 0 && (
        <div className="new-refs">
          <div className="diff-label">new references (all from real sources)</div>
          <ul>
            {p.new_references.map((r) => (
              <li key={r.id}>
                <ReferenceLink work={r} />
              </li>
            ))}
          </ul>
        </div>
      )}
      {p.status === 'pending' && (
        <div className="proposal-actions">
          <button className="approve" onClick={() => onDecide(p.id, 'approve')}>
            Approve &amp; apply
          </button>
          <button className="reject" onClick={() => onDecide(p.id, 'reject')}>
            Reject
          </button>
        </div>
      )}
      {p.status === 'applied' && undoable && (
        <div className="proposal-actions">
          <button className="reject" onClick={() => onDecide(p.id, 'undo')}>
            Undo this edit
          </button>
        </div>
      )}
    </div>
  )
}

export default function EditPanel({ paper, proposals, busy, error, onCommand, onDecide }: Props) {
  const [command, setCommand] = useState('')
  const submit = () => {
    if (command.trim() && !busy) {
      onCommand(command.trim())
      setCommand('')
    }
  }
  return (
    <div>
      <h3>Edit by instruction</h3>
      <p className="hint">
        Changes are proposed as diffs for your approval — nothing is applied
        silently, and no edit may drop an existing citation.
      </p>
      <div className="command-row">
        <input
          value={command}
          placeholder="e.g. add more citations to the introduction"
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          disabled={busy}
        />
        <button onClick={submit} disabled={busy || !command.trim()}>
          {busy ? 'Working…' : 'Propose edit'}
        </button>
      </div>
      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} className="example" onClick={() => setCommand(ex)} disabled={busy}>
            {ex}
          </button>
        ))}
      </div>
      {error && <div className="error-banner">{error}</div>}
      {(() => {
        const applied = proposals.filter((p) => p.status === 'applied')
        const lastAppliedId = applied.length ? applied[applied.length - 1].id : ''
        return [...proposals].reverse().map((p) => (
          <ProposalCard
            key={p.id} p={p} paper={paper}
            undoable={p.id === lastAppliedId}
            onDecide={onDecide}
          />
        ))
      })()}
    </div>
  )
}
