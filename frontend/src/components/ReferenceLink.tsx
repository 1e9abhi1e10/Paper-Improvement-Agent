import type { Reference } from '../types'
import { referenceLinkLabel, referenceUrl } from '../refUrl'

/** Title + year + real-source link. Never renders a search-results URL. */
export default function ReferenceLink({
  work,
  title,
  year,
  href,
  linkOnly = false,
}: {
  work?: Reference | null
  title?: string
  year?: string | number | null
  href?: string | null
  linkOnly?: boolean
}) {
  const label = title ?? work?.csl.title ?? work?.raw.slice(0, 120) ?? ''
  const issued = year ?? work?.csl.issued?.['date-parts']?.[0]?.[0]
  const link = href ?? (work ? referenceUrl(work) : null)
  const safe = link && !link.includes('/search') ? link : null
  return (
    <>
      {!linkOnly && (
        <>
          <i>{label}</i>
          {issued != null && issued !== '' && ` (${issued})`}
        </>
      )}
      {safe && (
        <>
          {!linkOnly && ' '}
          <a href={safe} target="_blank" rel="noreferrer" className="ref-link">
            {referenceLinkLabel(safe)} ↗
          </a>
        </>
      )}
    </>
  )
}

export function sectionTitle(sections: { id: string; title: string }[], id: string): string {
  return sections.find((s) => s.id === id)?.title ?? id
}
