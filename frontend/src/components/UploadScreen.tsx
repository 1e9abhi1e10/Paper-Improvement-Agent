import { useCallback, useState } from 'react'

interface Props {
  onUpload: (file: File) => void
  busy: boolean
  error: string
}

const FEATURES = [
  {
    title: 'Parse',
    desc: 'Structure, references and in-text citations extracted into clean CSL.',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="8" y1="13" x2="16" y2="13" />
        <line x1="8" y1="17" x2="13" y2="17" />
      </svg>
    ),
  },
  {
    title: 'Review',
    desc: 'Peer review grounded in real Semantic Scholar and OpenAlex records.',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <circle cx="11" cy="11" r="7" />
        <line x1="21" y1="21" x2="16.5" y2="16.5" />
      </svg>
    ),
  },
  {
    title: 'Edit',
    desc: 'Improve by instruction — every change is a diff you approve first.',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z" />
      </svg>
    ),
  },
  {
    title: 'Ask',
    desc: 'Chat grounded only in the paper, with quotes you can click to verify.',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    ),
  },
]

export default function UploadScreen({ onUpload, busy, error }: Props) {
  const [dragging, setDragging] = useState(false)

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      const file = e.dataTransfer.files[0]
      if (file) onUpload(file)
    },
    [onUpload],
  )

  return (
    <div className="upload-screen">
      <div className="upload-badge">
        <span className="dot" />
        Grounded in Semantic Scholar &amp; OpenAlex
      </div>
      <h1>
        Your paper, <em>peer-reviewed</em> and improved in minutes
      </h1>
      <p className="tagline">
        Upload a research PDF to parse its citations, get a source-backed
        review, edit by instruction, and ask questions — with every citation
        kept intact.
      </p>
      <label
        className={`dropzone ${dragging ? 'dragging' : ''} ${busy ? 'busy' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          type="file"
          accept="application/pdf"
          disabled={busy}
          onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
        />
        {busy ? (
          <>
            <span className="dz-spinner" aria-hidden />
            <span className="dz-big">Parsing your paper…</span>
            <span className="dz-small">extracting structure, references and citations</span>
          </>
        ) : (
          <>
            <span className="dz-icon" aria-hidden>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </span>
            <span className="dz-big">Drop your paper PDF here</span>
            <span className="dz-small">or click to browse — arXiv PDFs work great</span>
          </>
        )}
      </label>
      {error && <div className="error-banner">{error}</div>}
      <div className="features">
        {FEATURES.map((f) => (
          <div key={f.title} className="feature">
            <div className="feature-icon">{f.icon}</div>
            <h3>{f.title}</h3>
            <p>{f.desc}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
