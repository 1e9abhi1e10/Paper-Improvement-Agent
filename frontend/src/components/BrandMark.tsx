export default function BrandMark({ withName = true }: { withName?: boolean }) {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          <path d="M9 8l2.5 2.5L16 6" />
        </svg>
      </span>
      {withName && <span className="brand-name">Paper Improvement Agent</span>}
    </span>
  )
}
