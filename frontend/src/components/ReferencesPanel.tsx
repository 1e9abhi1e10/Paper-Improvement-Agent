import { PARSE_STATUS_LABEL, RESOLUTION_LABEL, type Paper } from '../types'
import ReferenceLink from './ReferenceLink'

function Coverage({ label, ok, total }: { label: string; ok: number; total: number }) {
  const cls = total === 0 ? 'cov-warn' : ok === total ? 'cov-ok' : ok / total >= 0.8 ? 'cov-warn' : 'cov-bad'
  return (
    <div className={`stat coverage ${cls}`}>
      <b>{ok}/{total}</b> {label}
    </div>
  )
}

export default function ReferencesPanel({
  paper,
  onRetryVerify,
  verifying,
}: {
  paper: Paper
  onRetryVerify?: () => void
  verifying?: boolean
}) {
  const unresolved = paper.intext.filter((c) => !c.resolved)
  const parsedRefs = paper.references.filter((r) => r.parse_status === 'parsed').length
  const verified = paper.references.filter((r) => r.resolution_status === 'verified').length
  const needsRetry = paper.references.some(
    (r) => r.parse_status !== 'failed' && r.resolution_status !== 'verified',
  )
  return (
    <div>
      <h3>How the paper was parsed</h3>
      <div className="stat-row">
        <Coverage label="references fully parsed" ok={parsedRefs} total={paper.references.length} />
        <Coverage
          label="in-text markers resolved"
          ok={paper.intext.length - unresolved.length}
          total={paper.intext.length}
        />
        <Coverage label="API-verified" ok={verified} total={paper.references.length} />
        <div className="stat"><b>{paper.sections.length}</b> sections</div>
        <div className="stat">
          style <b>{paper.style.toUpperCase()}</b>{' '}
          {paper.style_detected ? '(detected)' : '(manual)'}
        </div>
      </div>

      {needsRetry && onRetryVerify && (
        <p className="retry-row">
          <button onClick={onRetryVerify} disabled={verifying}>
            {verifying ? 'Retrying…' : 'Retry verification'}
          </button>
          <span className="muted">
            Re-resolves only unverified entries; verified ones are left alone.
          </span>
        </p>
      )}

      {paper.diagnostics.length > 0 && (
        <>
          <h4>Pipeline diagnostics</h4>
          <ul className="diagnostics">
            {paper.diagnostics.map((d, i) => (
              <li key={i} className={`diag diag-${d.severity}`}>
                <span className="diag-stage">{d.stage}</span> {d.message}
              </li>
            ))}
          </ul>
        </>
      )}

      {unresolved.length > 0 && (
        <>
          <h4>Unresolved in-text markers (kept verbatim)</h4>
          <ul className="diagnostics">
            {unresolved.map((c) => (
              <li key={c.id} className="diag diag-warning">
                <code>{c.raw}</code> in {c.section_id}
              </li>
            ))}
          </ul>
        </>
      )}

      <h4>References ({paper.style.toUpperCase()} via CSL)</h4>
      <ol className="ref-list">
        {paper.references.map((ref) => {
          const rendered = paper.rendered.bibliography.find((b) => b.ref_id === ref.id)
          const resolution = ref.resolution_status || 'unverified'
          return (
            <li key={ref.id}>
              <div className="ref-entry">{rendered?.entry || ref.raw}</div>
              <div className="ref-meta">
                <span className={`badge badge-${ref.parse_status}`}>
                  {PARSE_STATUS_LABEL[ref.parse_status]}
                </span>
                {ref.parse_status !== 'failed' && (
                  <span className={`badge badge-res-${resolution}`}>
                    {RESOLUTION_LABEL[resolution]}
                  </span>
                )}
                {ref.added_by_edit && <span className="badge badge-new">added by edit</span>}
                <ReferenceLink work={ref} linkOnly />
              </div>
              {ref.resolution_note && (
                <div className="ref-raw">{ref.resolution_note}</div>
              )}
              {ref.parse_status !== 'parsed' && ref.raw && (
                <div className="ref-raw">raw: {ref.raw}</div>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
