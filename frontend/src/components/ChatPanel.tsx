import { useRef, useState } from 'react'
import type { ChatMessage, Paper } from '../types'
import ReferenceLink from './ReferenceLink'

interface Props {
  paper: Paper
  messages: ChatMessage[]
  busy: boolean
  error: string
  onAsk: (question: string) => void
}

const EXAMPLES = [
  'What is the main contribution of this paper?',
  'What datasets and baselines are used?',
  'What limitations do the authors acknowledge?',
]

function scrollToSection(sectionId: string) {
  document.getElementById(`paper-${sectionId}`)?.scrollIntoView({
    behavior: 'smooth', block: 'start',
  })
}

function AnswerCard({ m, paper }: { m: ChatMessage; paper: Paper }) {
  if (m.role === 'user') {
    return <div className="chat-q">{m.content}</div>
  }
  return (
    <div className="chat-a">
      {m.answered === false && <span className="badge badge-unverifiable">not in the paper</span>}
      <p>{m.content}</p>
      {m.warning && <div className="warning-banner">{m.warning}</div>}
      {m.sources && m.sources.length > 0 && (
        <div className="chat-sources">
          <div className="diff-label">sources in the paper</div>
          {m.sources.map((s, i) => (
            <button key={i} className="chat-source" onClick={() => scrollToSection(s.section_id)}>
              <span className="chat-source-sec">{s.section_title}</span>
              <span className="chat-source-quote">“{s.quote}”</span>
            </button>
          ))}
        </div>
      )}
      {m.cited_refs && m.cited_refs.length > 0 && (
        <div className="chat-refs">
          <div className="diff-label">references involved</div>
          <ul>
            {m.cited_refs.map((rid) => {
              const ref = paper.references.find((r) => r.id === rid)
              if (!ref) return null
              return (
                <li key={rid}>
                  <ReferenceLink work={ref} />
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function ChatPanel({ paper, messages, busy, error, onAsk }: Props) {
  const [question, setQuestion] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  const submit = () => {
    if (question.trim() && !busy) {
      onAsk(question.trim())
      setQuestion('')
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
    }
  }

  return (
    <div>
      <h3>Ask the paper</h3>
      <p className="hint">
        Answers come only from the paper's own text. Every claim carries a
        verified quote you can click to jump to; if the paper doesn't answer,
        it says so.
      </p>
      <div className="chat-thread">
        {messages.map((m, i) => <AnswerCard key={i} m={m} paper={paper} />)}
        {busy && <div className="chat-a hint">Reading the paper…</div>}
        <div ref={bottomRef} />
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="command-row">
        <input
          value={question}
          placeholder="e.g. what optimizer do they use?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          disabled={busy}
        />
        <button onClick={submit} disabled={busy || !question.trim()}>Ask</button>
      </div>
      {messages.length === 0 && (
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="example" onClick={() => setQuestion(ex)} disabled={busy}>
              {ex}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
