// Asistente (Capítulo 13): interpreta una frase y decide si buscar, responder con los
// documentos o proponer una acción. Una acción propuesta nunca se ejecuta sola.
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { OPPORTUNITY_STATUS, fmtDate, fmtMoney, label } from '../lib/format'
import type { AssistantResponse } from '../lib/types'
import { RagView } from '../components/AskDocuments'
import { OpportunityStatus } from '../components/status'
import { Highlight } from '../components/text'
import { Badge, Empty, ErrorBox, ScoreBar, Spinner, errorMessage, useToast } from '../components/ui'

const INTENT_TEXT: Record<string, string> = {
  AGENT_TOOLS: 'Búsqueda',
  CHAT_RAG: 'Pregunta sobre documentos',
  WORKFLOW: 'Encargo',
  OFF_TOPIC: 'Fuera de tema',
}

const FILTER_TEXT: Record<string, string> = {
  q: 'Texto',
  value_min: 'Importe mínimo',
  value_max: 'Importe máximo',
  deadline_within_days: 'Cierran en (días)',
  published_within_days: 'Publicadas hace (días)',
  only_open: 'Solo abiertas',
  status: 'Estado',
  phase: 'Fase',
  service_line: 'Línea',
  sector: 'Sector',
  cpv: 'CPV',
  owner: 'Responsable',
}

function filterValue(key: string, value: unknown): string {
  if (key.startsWith('value_')) return fmtMoney(value as number)
  if (typeof value === 'boolean') return value ? 'sí' : 'no'
  if (Array.isArray(value)) return value.map((v) => (key === 'status' ? label(OPPORTUNITY_STATUS, String(v)) : String(v))).join(', ')
  if (key === 'owner' && value === 'me') return 'yo'
  return String(value)
}

function Workflow({ r }: { r: Extract<AssistantResponse, { type: 'workflow_suggestion' }> }) {
  const navigate = useNavigate()
  const toast = useToast()
  const confirm = useMutation({
    mutationFn: () => api<{ id?: number }>(r.confirm!.path, { method: r.confirm!.method, body: r.confirm!.body ?? {} }),
    onSuccess: (res) => {
      toast('Hecho. Te avisaremos cuando termine.')
      if (r.action === 'create_proposal' && res?.id) navigate(`/proposals/${res.id}`)
      else if (r.target?.proposal_id) navigate(`/proposals/${r.target.proposal_id}`)
      else if (r.target) navigate(`/${r.target.kind === 'document' ? 'documents' : 'opportunities'}/${r.target.id}`)
    },
  })
  return (
    <section className="card">
      <p className="lead">{r.message}</p>
      {r.target && (
        <p>
          <Link to={`/${r.target.kind === 'document' ? 'documents' : 'opportunities'}/${r.target.id}`}>{r.target.title}</Link>
        </p>
      )}
      {confirm.error && <p className="notice notice-error">{errorMessage(confirm.error)}</p>}
      {r.confirm && (
        <div className="btn-row">
          <button className="btn btn-primary" onClick={() => confirm.mutate()} disabled={confirm.isPending || confirm.isSuccess}>
            Confirmar
          </button>
          <span className="muted">Tiene coste de IA y crea datos: solo se hace si confirmas.</span>
        </div>
      )}
    </section>
  )
}

export default function Search() {
  const [params] = useSearchParams()
  const q = params.get('q') ?? ''
  const [rated, setRated] = useState(false)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['assistant', q],
    queryFn: () => api<AssistantResponse & { query_log_id?: number }>('/api/assistant/query', { body: { query: q } }),
    enabled: q.length > 0,
    staleTime: 60_000,
  })

  async function feedback(rating: number) {
    if (!data?.query_log_id) return
    setRated(true)
    await api('/api/assistant/feedback', { body: { query_log_id: data.query_log_id, rating } }).catch(() => setRated(false))
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>«{q}»</h1>
          {data && (
            <p className="muted">
              Lo he entendido como: <Badge tone="accent">{INTENT_TEXT[data.intent.type] ?? data.intent.type}</Badge> (confianza{' '}
              {Math.round(data.intent.confidence * 100)} %)
            </p>
          )}
        </div>
        <Link className="btn" to={`/copilot?q=${encodeURIComponent(q)}`}>
          Seguir en el copiloto
        </Link>
      </header>
      {!q && <Empty title="Escribe algo en el buscador de arriba" />}
      {isLoading && <Spinner label="Pensando…" />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}

      {data?.type === 'search_results' && (
        <>
          {Object.keys(data.filters).length > 0 && (
            <div className="chips">
              {Object.entries(data.filters).map(([k, v]) => (
                <span key={k} className="chip chip-static">
                  {FILTER_TEXT[k] ?? k}: {filterValue(k, v)}
                </span>
              ))}
            </div>
          )}
          {!data.items.length && <Empty title="No he encontrado nada">Prueba con otras palabras o menos condiciones.</Empty>}
          {data.target === 'opportunities' && data.items.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {data.items.map((o) => (
                    <tr key={o.id}>
                      <td>
                        <Link to={`/opportunities/${o.id}`} className="row-title">
                          <Highlight html={o.highlight?.title} fallback={o.title} />
                        </Link>
                        <div className="row-sub">{[o.code, o.client_name ?? o.contracting_entity].filter(Boolean).join(' · ')}</div>
                      </td>
                      <td>
                        <OpportunityStatus status={o.status} />
                      </td>
                      <td className="num">{fmtMoney(o.estimated_value_eur)}</td>
                      <td>{fmtDate(o.deadline)}</td>
                      <td>
                        <ScoreBar value={o.relevance_score} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.target !== 'opportunities' && data.items.length > 0 && (
            <ul className="plain-list">
              {data.items.map((x) => (
                <li key={x.id}>
                  <Link to={`/${data.target}/${x.id}`}>{x.title ?? x.name}</Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {data?.type === 'rag_answer' && (
        <section className="card">
          <RagView answer={data} />
        </section>
      )}
      {data?.type === 'workflow_suggestion' && <Workflow r={data} />}
      {data?.type === 'off_topic' && <p className="notice notice-info">{data.message}</p>}

      {data?.query_log_id && data.type !== 'rag_answer' && (
        <div className="rating">
          <span className="muted">¿Era lo que buscabas?</span>
          <button className="btn btn-small" onClick={() => void feedback(5)} disabled={rated}>
            Sí
          </button>
          <button className="btn btn-small" onClick={() => void feedback(1)} disabled={rated}>
            No
          </button>
        </div>
      )}
    </div>
  )
}
