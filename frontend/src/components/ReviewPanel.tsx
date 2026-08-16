import type { Finding, Paper } from '../types'
import ReferenceLink, { sectionTitle } from './ReferenceLink'

const KIND_LABEL: Record<Finding['kind'], string> = {
  missing_citation: 'Missing work',
  citation_mismatch: 'Citation mismatch',
  unverifiable: 'Unverifiable',
  uncited_claim: 'Uncited claim',
  redundant_citation: 'Citation bundle',
  info: 'Note',
}

interface Props {
  paper: Paper
  findings: Finding[] | null
  busy: boolean
  error: string
  onRun: () => void
}

function FindingCard({ f, paper }: { f: Finding; paper: Paper }) {
  const cand = f.candidate_csl
  const prov = f.candidate_provenance
  const ref = paper.references.find((r) => r.id === f.ref_id)
  return (
    <div className="finding">
      <div className="finding-head">
        <span className={`badge badge-${f.kind}`}>{KIND_LABEL[f.kind]}</span>
        {f.verdict && <span className="badge badge-verdict">{f.verdict.replace(/_/g, ' ')}</span>}
        <span className={`badge badge-conf-${f.confidence}`}>{f.confidence} confidence</span>
        {f.section_id && <span className="finding-section">{sectionTitle(paper.sections, f.section_id)}</span>}
      </div>
      {f.claim && <blockquote className="finding-claim">“{f.claim}”</blockquote>}
      {f.rationale && <p className="finding-rationale">{f.rationale}</p>}
      {ref && (
        <p className="finding-source">
          Cited work: <ReferenceLink work={ref} />
        </p>
      )}
      {cand?.title && (
        <p className="finding-source">
          Suggested work: <ReferenceLink
            title={cand.title}
            year={cand.issued?.['date-parts']?.[0]?.[0]}
            href={prov?.url}
          />
        </p>
      )}
    </div>
  )
}

export default function ReviewPanel({ paper, findings, busy, error, onRun }: Props) {
  const problems = (findings ?? []).filter((f) => f.kind !== 'info')
  const notes = (findings ?? []).filter((f) => f.kind === 'info')
  return (
    <div>
      <div className="panel-head">
        <h3>Peer review</h3>
        <button onClick={onRun} disabled={busy}>
          {busy ? 'Reviewing… (searches both APIs, ~1–2 min)' : findings?.length ? 'Re-run review' : 'Run review'}
        </button>
      </div>
      <p className="hint">
        Missing-work suggestions and claim-citation checks, each grounded in a
        real Semantic Scholar or OpenAlex record. Empty searches and
        unverifiable claims are reported honestly.
      </p>
      {error && <div className="error-banner">{error}</div>}
      {findings === null && !busy && <p className="hint">No review yet.</p>}
      {findings !== null && (
        <>
          {problems.map((f) => <FindingCard key={f.id} f={f} paper={paper} />)}
          {notes.length > 0 && <h4>Verified / informational</h4>}
          {notes.map((f) => <FindingCard key={f.id} f={f} paper={paper} />)}
        </>
      )}
    </div>
  )
}
