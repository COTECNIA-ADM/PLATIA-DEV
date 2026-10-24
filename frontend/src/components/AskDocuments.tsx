// Preguntas sobre los documentos con citas (RAG, Capítulo 12).
// Solo se usan fragmentos que la persona puede ver; cada [n] enlaza con su fuente.
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useMutation } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { RagAnswer, Source } from '../lib/types'
import { Markdown } from './text'
import { Badge, errorMessage } from './ui'

export function Sources({ sources, focus }: { sources: Source[]; focus?: number | null }) {
  if (!sources.length) return null
  return (
    <ol className="sources">
      {sources.map((s) => (
        <li key={s.n} id={`source-${s.n}`} className={focus === s.n ? 'source-focus' : undefined}>
          <div className="row-between">
            <Link to={`/documents/${s.document_id}`}>
              [{s.n}] {s.title}
            </Link>
            <span className="muted">
              {s.page ? `pág. ${s.page} · ` : ''}
              {Math.round(s.score * 100)} %{s.cited && <Badge tone="accent">citada</Badge>}
            </span>
          </div>
          <blockquote>{s.excerpt}</blockquote>
        </li>
      ))}
    </ol>
  )
}

export function RagView({ answer }: { answer: RagAnswer }) {
  const [focus, setFocus] = useState<number | null>(null)
  const [rated, setRated] = useState<number | null>(null)
  function cite(n: number) {
    setFocus(n)
    document.getElementById(`source-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
  async function rate(rating: number) {
    if (!answer.usage_log_id) return
    setRated(rating)
    await api('/api/ai/feedback', { body: { usage_log_id: answer.usage_log_id, rating } }).catch(() => setRated(null))
  }
  return (
    <div className="rag">
      {!answer.sufficient_context && (
        <p className="notice notice-warning">Los documentos no bastan para responder del todo. Revisa las fuentes.</p>
      )}
      <Markdown text={answer.answer} onCite={cite} />
      <Sources sources={answer.sources} focus={focus} />
      {answer.usage_log_id && (
        <div className="rating">
          <span className="muted">¿Te ha servido?</span>
          <button className={`btn btn-small${rated === 5 ? ' btn-primary' : ''}`} onClick={() => void rate(5)} disabled={rated !== null}>
            Sí
          </button>
          <button className={`btn btn-small${rated === 1 ? ' btn-primary' : ''}`} onClick={() => void rate(1)} disabled={rated !== null}>
            No
          </button>
        </div>
      )}
    </div>
  )
}

export default function AskDocuments({ documentIds, placeholder }: { documentIds?: number[]; placeholder?: string }) {
  const [question, setQuestion] = useState('')
  const ask = useMutation({
    mutationFn: (q: string) => api<RagAnswer>('/api/ai/ask', { body: { question: q, document_ids: documentIds } }),
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    if (question.trim()) ask.mutate(question.trim())
  }
  return (
    <div className="stack">
      <form className="ask" onSubmit={submit}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={placeholder ?? '¿Qué certificaciones se exigen? ¿Cuál es el plazo?'}
          maxLength={2000}
        />
        <button className="btn btn-primary" disabled={ask.isPending || !question.trim()}>
          {ask.isPending ? 'Pensando…' : 'Preguntar'}
        </button>
      </form>
      {ask.error && <p className="notice notice-error">{errorMessage(ask.error)}</p>}
      {ask.data && <RagView answer={ask.data} />}
    </div>
  )
}
