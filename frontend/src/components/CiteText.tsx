import type { BibEntry } from '../types'

const TOKEN = /\[\[cite:([A-Za-z0-9_,-]+)\]\]/g

interface Props {
  text: string
  bibliography: BibEntry[]
  onCite?: (refIds: string[]) => void
}

/** Renders tokenized paper text, turning [[cite:...]] tokens into
 *  styled citation chips with the CSL-rendered inline label. */
export default function CiteText({ text, bibliography, onCite }: Props) {
  const byId = new Map(bibliography.map((b) => [b.ref_id, b]))
  const parts: React.ReactNode[] = []
  let last = 0
  let key = 0
  for (const m of text.matchAll(TOKEN)) {
    parts.push(text.slice(last, m.index))
    const refIds = m[1].split(',')
    const labels = refIds.map((r) => byId.get(r)?.inline ?? `[${r}]`)
    const numeric = labels.every((l) => l.startsWith('['))
    const label = numeric
      ? labels.join('')
      : `(${labels.map((l) => l.replace(/^\(|\)$/g, '')).join('; ')})`
    const tooltip = onCite
      ? 'Click for details'
      : refIds.map((r) => byId.get(r)?.entry ?? r).join('\n')
    parts.push(
      <span
        className={`cite-chip ${onCite ? 'clickable' : ''}`}
        title={tooltip}
        key={`c${key++}`}
        onClick={onCite ? () => onCite(refIds) : undefined}
      >
        {label}
      </span>,
    )
    last = (m.index ?? 0) + m[0].length
  }
  parts.push(text.slice(last))
  return <span className="cite-text">{parts}</span>
}
