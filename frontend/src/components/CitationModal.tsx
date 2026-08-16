import { PARSE_STATUS_LABEL, RESOLUTION_LABEL, type Finding, type Paper } from '../types'
import ReferenceLink from './ReferenceLink'

interface Props {
  paper: Paper
  refIds: string[]
  findings: Finding[] | null
  onClose: () => void
}

/** "Explain this citation": everything the app knows about the cited
 *  work(s) — the CSL-rendered entry, parse status, real source links,
 *  the fetched abstract, and any claim-check verdicts from review. */
export default function CitationModal({ paper, refIds, findings, onClose }: Props) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Citation details</h3>
          <button className="ghost" onClick={onClose}>Close</button>
        </div>
        {refIds.map((rid) => {
          const ref = paper.references.find((r) => r.id === rid)
          if (!ref) return null
          const entry = paper.rendered.bibliography.find((b) => b.ref_id === rid)
          const verdicts = (findings ?? []).filter((f) => f.ref_id === rid && f.verdict)
          return (
            <div key={rid} className="modal-ref">
              <div className="ref-entry">{entry?.entry || ref.raw}</div>
              <div className="ref-meta">
                <span className={`badge badge-${ref.parse_status}`}>
                  {PARSE_STATUS_LABEL[ref.parse_status]}
                </span>
                {ref.parse_status !== 'failed' && ref.resolution_status && (
                  <span className={`badge badge-res-${ref.resolution_status}`}>
                    {RESOLUTION_LABEL[ref.resolution_status]}
                  </span>
                )}
                {ref.added_by_edit && <span className="badge badge-new">added by edit</span>}
                <ReferenceLink work={ref} linkOnly />
              </div>
              {ref.provenance?.abstract ? (
                <p className="modal-abstract">
                  <span className="diff-label">abstract</span>
                  {ref.provenance.abstract.slice(0, 700)}
                  {ref.provenance.abstract.length > 700 && '…'}
                </p>
              ) : (
                <p className="hint">No abstract fetched yet — run a review to resolve this work.</p>
              )}
              {verdicts.length > 0 ? (
                verdicts.map((f) => (
                  <div key={f.id} className="modal-verdict">
                    <span className="badge badge-verdict">{f.verdict.replace(/_/g, ' ')}</span>
                    <span className={`badge badge-conf-${f.confidence}`}>{f.confidence} confidence</span>
                    {f.claim && <blockquote className="finding-claim">“{f.claim}”</blockquote>}
                    {f.rationale && <p className="finding-rationale">{f.rationale}</p>}
                  </div>
                ))
              ) : (
                <p className="hint">Claim-support not checked yet for this citation.</p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
