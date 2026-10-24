// Copiloto (Capítulos 14 y 15): conversación en streaming con herramientas y
// aprobación humana. Lo que cambia datos nunca se hace sin pulsar «Aprobar».
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, stream, type StreamEvent } from '../lib/api'
import { MEMORY_CATEGORIES, TOOL_NAMES, fmtRelative, label } from '../lib/format'
import type { ChatMessage, Conversation, Memory, Page, PendingAction, Source, ToolUse } from '../lib/types'
import { Sources } from '../components/AskDocuments'
import { Markdown } from '../components/text'
import { Badge, Empty, ErrorBox, Field, Modal, Spinner, errorMessage, useToast } from '../components/ui'

type Live = {
  text: string
  tools: ToolUse[]
  notices: string[]
  agent?: string
  intent?: string
  sources?: Source[]
  approval?: { run_id: string; actions: PendingAction[]; expires_at?: string }
  error?: string
}

const EXAMPLES = [
  '¿Qué oportunidades de ciberseguridad cierran este mes?',
  'Resume los requisitos de solvencia del último pliego que he subido',
  'Prepara una propuesta base para @oportunidad:1',
  '¿Qué perfiles tenemos con experiencia en Kubernetes?',
]

function ToolChips({ tools }: { tools: ToolUse[] }) {
  if (!tools.length) return null
  return (
    <div className="tool-chips">
      {tools.map((t, i) => (
        <span key={i} className={`tool-chip${t.ok === false ? ' tool-chip-error' : t.ok ? ' tool-chip-ok' : ''}`} title={t.summary}>
          {t.ok === undefined && <span className="spinner-dot" aria-hidden />}
          {label(TOOL_NAMES, t.name)}
          {t.ms !== undefined && <span className="muted"> · {t.ms} ms</span>}
        </span>
      ))}
    </div>
  )
}

function ApprovalCard({
  actions,
  status,
  busy,
  onDecide,
}: {
  actions: PendingAction[]
  status: 'pending' | 'approved' | 'rejected'
  busy: boolean
  onDecide?: (approve: boolean, comment?: string) => void
}) {
  const [comment, setComment] = useState('')
  return (
    <div className={`approval approval-${status}`}>
      <strong>{status === 'pending' ? 'El copiloto quiere hacer esto. ¿Lo apruebas?' : status === 'approved' ? 'Aprobado' : 'Rechazado'}</strong>
      <ul>
        {actions.map((a) => (
          <li key={a.id}>
            <Badge tone="accent">{label(TOOL_NAMES, a.name)}</Badge> {a.summary}
          </li>
        ))}
      </ul>
      {status === 'pending' && onDecide && (
        <div className="stack">
          <input
            placeholder="Comentario para el copiloto (opcional, p. ej. «mejor del tipo competitiva»)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={1000}
          />
          <div className="btn-row">
            <button className="btn btn-primary" onClick={() => onDecide(true, comment)} disabled={busy}>
              Aprobar
            </button>
            <button className="btn" onClick={() => onDecide(false, comment)} disabled={busy}>
              Rechazar
            </button>
          </div>
          <p className="muted">Caduca a los 15 minutos. Si escribes otro mensaje, se cancela.</p>
        </div>
      )}
    </div>
  )
}

function MessageView({ m, last, busy, onDecide }: { m: ChatMessage; last: boolean; busy: boolean; onDecide: (runId: string, approve: boolean, comment?: string) => void }) {
  if (m.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="bubble">{m.content}</div>
        {!!m.meta.references?.length && (
          <div className="refs">
            {m.meta.references.map((r) => (
              <Link key={`${r.kind}-${r.id}`} to={`/${r.kind === 'opportunity' ? 'opportunities' : r.kind === 'document' ? 'documents' : r.kind === 'client' ? 'clients' : 'proposals'}/${r.id}`} className="ref">
                {r.title}
              </Link>
            ))}
          </div>
        )}
      </div>
    )
  }
  const approval = m.meta.approval
  return (
    <div className={`msg msg-assistant${m.meta.error ? ' msg-error' : ''}`}>
      <ToolChips tools={(m.meta.tools ?? []).map((t) => ({ ...t, ok: true }))} />
      <div className="bubble">
        <Markdown text={m.content} />
        {!!m.meta.sources?.length && (
          <details>
            <summary>Fuentes ({m.meta.sources.length})</summary>
            <Sources sources={m.meta.sources} />
          </details>
        )}
      </div>
      {approval && (
        <ApprovalCard
          actions={approval.actions}
          status={approval.status}
          busy={busy}
          onDecide={last ? (approve, comment) => onDecide(approval.run_id, approve, comment) : undefined}
        />
      )}
    </div>
  )
}

function LiveView({ live, busy, onDecide }: { live: Live; busy: boolean; onDecide: (runId: string, approve: boolean, comment?: string) => void }) {
  return (
    <div className="msg msg-assistant">
      {live.agent && <div className="msg-agent muted">{live.agent}</div>}
      <ToolChips tools={live.tools} />
      {live.notices.map((n, i) => (
        <p key={i} className="notice notice-info">
          {n}
        </p>
      ))}
      {(live.text || !live.approval) && (
        <div className="bubble">
          {live.text ? <Markdown text={live.text} /> : <span className="typing" aria-label="Escribiendo" />}
          {!!live.sources?.length && (
            <details>
              <summary>Fuentes ({live.sources.length})</summary>
              <Sources sources={live.sources} />
            </details>
          )}
        </div>
      )}
      {live.error && <p className="notice notice-error">{live.error}</p>}
      {live.approval && (
        <ApprovalCard
          actions={live.approval.actions}
          status="pending"
          busy={busy}
          onDecide={(approve, comment) => onDecide(live.approval!.run_id, approve, comment)}
        />
      )}
    </div>
  )
}

function Memories() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<Memory | 'new' | null>(null)
  const [content, setContent] = useState('')
  const [category, setCategory] = useState('preference')
  const { data, error, isLoading } = useQuery({ queryKey: ['memories'], queryFn: () => api<{ items: Memory[] }>('/api/copilot/memories') })
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['memories'] })
  const save = useMutation({
    mutationFn: () =>
      editing === 'new'
        ? api('/api/copilot/memories', { body: { category, content } })
        : api(`/api/copilot/memories/${(editing as Memory).id}`, { method: 'PATCH', body: { category, content } }),
    onSuccess: () => {
      setEditing(null)
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/copilot/memories/${id}`, { method: 'DELETE' }),
    onSuccess: refresh,
  })
  const forgetAll = useMutation({
    mutationFn: () => api<{ deleted: number }>('/api/copilot/memories', { method: 'DELETE' }),
    onSuccess: (r) => {
      toast(`Olvidados ${r.deleted} recuerdos`)
      refresh()
    },
  })
  function open(m: Memory | 'new') {
    setEditing(m)
    setContent(m === 'new' ? '' : m.content)
    setCategory(m === 'new' ? 'preference' : m.category)
  }
  return (
    <div className="page page-narrow">
      <header className="page-head">
        <div>
          <h2>Lo que el copiloto recuerda de ti</h2>
          <p className="muted">
            Preferencias y contexto que aprende de las conversaciones (sin datos personales). Usa los 10 más útiles en cada respuesta.
            Puedes corregirlos o borrarlos cuando quieras.
          </p>
        </div>
        <div className="btn-row">
          <button className="btn" onClick={() => open('new')}>
            Añadir
          </button>
          {!!data?.items.length && (
            <button className="btn btn-danger-ghost" onClick={() => window.confirm('¿Borrar todo lo que recuerda?') && forgetAll.mutate()}>
              Olvidar todo
            </button>
          )}
        </div>
      </header>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} />}
      {data && !data.items.length && <Empty title="Todavía no recuerda nada">Se irá llenando a medida que converses.</Empty>}
      <ul className="memory-list">
        {data?.items.map((m) => (
          <li key={m.id} className="card">
            <div>
              <Badge tone={m.source === 'user' ? 'accent' : 'neutral'}>{label(MEMORY_CATEGORIES, m.category)}</Badge> {m.content}
              <div className="row-sub">
                {m.source === 'user' ? 'Añadido por ti' : 'Aprendido'} · usado {m.access_count} veces · {fmtRelative(m.last_accessed_at ?? m.created_at)}
              </div>
            </div>
            <div className="btn-row">
              <button className="btn btn-small" onClick={() => open(m)}>
                Corregir
              </button>
              <button className="btn btn-small btn-ghost" onClick={() => remove.mutate(m.id)}>
                Borrar
              </button>
            </div>
          </li>
        ))}
      </ul>
      <p className="muted">
        <button className="btn-link" onClick={() => void api('/api/copilot/export').then((d) => {
          const url = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' }))
          const a = document.createElement('a')
          a.href = url
          a.download = 'mis-conversaciones.json'
          a.click()
          setTimeout(() => URL.revokeObjectURL(url), 10_000)
        })}>
          Descargar mis conversaciones y recuerdos
        </button>
      </p>
      {editing && (
        <Modal title={editing === 'new' ? 'Añadir recuerdo' : 'Corregir recuerdo'} onClose={() => setEditing(null)}>
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault()
              save.mutate()
            }}
          >
            <Field label="Tipo">
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                {Object.entries(MEMORY_CATEGORIES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Qué debe recordar" hint="Ejemplo: «Prefiero los importes sin IVA».">
              <textarea rows={3} value={content} onChange={(e) => setContent(e.target.value)} maxLength={500} required />
            </Field>
            {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
            <div className="actions">
              <button type="button" className="btn btn-ghost" onClick={() => setEditing(null)}>
                Cancelar
              </button>
              <button className="btn btn-primary" disabled={save.isPending}>
                Guardar
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}

function Chat({ conversationId }: { conversationId: number }) {
  const queryClient = useQueryClient()
  const [params] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const [live, setLive] = useState<Live | null>(null)
  const [pendingUser, setPendingUser] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abort = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const opportunityId = params.get('opportunity') ? Number(params.get('opportunity')) : undefined

  const key = ['conversation', conversationId]
  const { data, error: loadError, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => api<Conversation & { messages: ChatMessage[] }>(`/api/copilot/conversations/${conversationId}`),
  })

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [data?.messages.length, live?.text, live?.tools.length, live?.approval, pendingUser])

  useEffect(() => () => abort.current?.abort(), [])

  async function run(events: AsyncGenerator<StreamEvent>) {
    let state: Live = { text: '', tools: [], notices: [] }
    const push = (next: Partial<Live>) => {
      state = { ...state, ...next }
      setLive(state)
    }
    push({})
    for await (const { event, data: d } of events) {
      switch (event) {
        case 'intent':
          push({ intent: String(d.type ?? '') })
          break
        case 'agent':
          push({ agent: String(d.name ?? '') })
          break
        case 'delta':
          push({ text: state.text + String(d.text ?? '') })
          break
        case 'replace':
          push({ text: String(d.text ?? '') })
          break
        case 'tool_call':
          push({ tools: [...state.tools, { id: String(d.id), name: String(d.name), title: d.title as string, summary: d.summary as string }] })
          break
        case 'tool_result':
          push({
            tools: state.tools.map((t) => (t.id === d.id ? { ...t, ok: Boolean(d.ok), ms: d.ms as number | undefined } : t)),
          })
          break
        case 'notice':
          push({ notices: [...state.notices, String(d.message ?? '')] })
          break
        case 'rag_answer':
          push({ sources: (d.sources as Source[]) ?? [] })
          break
        case 'approval_required':
          push({ approval: { run_id: String(d.run_id), actions: d.actions as PendingAction[], expires_at: d.expires_at as string } })
          break
        case 'error':
          push({ error: String(d.message ?? 'Error'), text: d.retract ? '' : state.text })
          break
      }
    }
  }

  async function consume(make: () => AsyncGenerator<StreamEvent>) {
    setBusy(true)
    setError(null)
    abort.current = new AbortController()
    try {
      await run(make())
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        setError(err instanceof ApiError && err.status === 422 ? `No se ha enviado: ${err.message}` : errorMessage(err))
      }
    } finally {
      setBusy(false)
      setPendingUser(null)
      // Lo que ha quedado guardado en el servidor sustituye a la vista en directo
      await queryClient.invalidateQueries({ queryKey: key })
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
      setLive(null)
    }
  }

  function send(e?: FormEvent) {
    e?.preventDefault()
    const content = text.trim()
    if (!content || busy) return
    setText('')
    setPendingUser(content)
    void consume(() =>
      stream(`/api/copilot/conversations/${conversationId}/messages`, { content, opportunity_id: opportunityId }, abort.current!.signal),
    )
  }

  function decide(runId: string, approve: boolean, comment?: string) {
    void consume(() => stream(`/api/copilot/runs/${runId}/approval`, { approve, comment: comment || null }, abort.current!.signal))
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  if (isLoading) return <Spinner />
  if (loadError) return <ErrorBox error={loadError} />
  const messages = data?.messages ?? []

  return (
    <div className="chat">
      <div className="chat-log">
        {data?.has_summary && <p className="muted chat-summary">Los mensajes antiguos se han resumido para el copiloto.</p>}
        {!messages.length && !pendingUser && (
          <div className="chat-empty">
            <h2>¿En qué te ayudo?</h2>
            <p className="muted">
              Busco oportunidades, leo tus documentos, preparo análisis y propuestas. Nombra un registro con @oportunidad:12, @documento:5 o
              @cliente:3. Antes de crear o cambiar nada, te pido permiso.
            </p>
            <div className="examples">
              {EXAMPLES.map((x) => (
                <button key={x} className="chip" onClick={() => setText(x)}>
                  {x}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <MessageView key={m.id} m={m} last={i === messages.length - 1 && !live} busy={busy} onDecide={decide} />
        ))}
        {pendingUser && (
          <div className="msg msg-user">
            <div className="bubble">{pendingUser}</div>
          </div>
        )}
        {live && <LiveView live={live} busy={busy} onDecide={decide} />}
        {error && <p className="notice notice-error">{error}</p>}
        <div ref={bottom} />
      </div>
      <form className="composer" onSubmit={send}>
        {opportunityId && (
          <div className="composer-context">
            Contexto: <Link to={`/opportunities/${opportunityId}`}>oportunidad #{opportunityId}</Link>
          </div>
        )}
        <textarea
          rows={2}
          placeholder="Escribe tu mensaje. Intro para enviar, Mayús+Intro para salto de línea."
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          maxLength={4000}
          disabled={busy}
          autoFocus
        />
        {busy ? (
          <button type="button" className="btn" onClick={() => abort.current?.abort()}>
            Detener
          </button>
        ) : (
          <button className="btn btn-primary" disabled={!text.trim()}>
            Enviar
          </button>
        )}
      </form>
    </div>
  )
}

export default function Copilot() {
  const params = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const toast = useToast()
  const queryClient = useQueryClient()
  const tab = search.get('tab') === 'memories' ? 'memories' : 'chat'
  const current = params.id ? Number(params.id) : null
  const conversations = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api<Page<Conversation>>('/api/copilot/conversations', { query: { per_page: 50 } }),
  })
  const create = useMutation({
    mutationFn: () => api<Conversation>('/api/copilot/conversations', { body: {} }),
    onSuccess: (c) => {
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
      const keep = new URLSearchParams(search)
      keep.delete('tab')
      navigate(`/copilot/${c.id}${keep.toString() ? `?${keep}` : ''}`)
    },
    onError: (err) => toast(errorMessage(err), 'danger'),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/copilot/conversations/${id}`, { method: 'DELETE' }),
    onSuccess: (_r, id) => {
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
      if (id === current) navigate('/copilot')
    },
  })

  // Si llega con contexto (desde una oportunidad o el buscador) y sin conversación, se abre una nueva
  useEffect(() => {
    if (!current && tab === 'chat' && (search.get('opportunity') || search.get('q')) && !create.isPending && !create.isSuccess) {
      create.mutate()
    }
  }, [current, tab, search, create])

  return (
    <div className="copilot">
      <aside className="conversations">
        <button className="btn btn-primary btn-block" onClick={() => create.mutate()} disabled={create.isPending}>
          Nueva conversación
        </button>
        <nav className="tabs-vertical">
          <Link to="/copilot?tab=memories" className={tab === 'memories' ? 'active' : undefined}>
            Lo que recuerdo de ti
          </Link>
        </nav>
        {conversations.isLoading && <Spinner />}
        <ul className="conversation-list">
          {conversations.data?.items.map((c) => (
            <li key={c.id} className={c.id === current && tab === 'chat' ? 'active' : undefined}>
              <Link to={`/copilot/${c.id}`}>
                <span className="conversation-title">{c.title}</span>
                <small className="muted">{fmtRelative(c.last_message_at ?? c.created_at)}</small>
              </Link>
              <button className="btn-icon" title="Borrar conversación" onClick={() => window.confirm('¿Borrar esta conversación?') && remove.mutate(c.id)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section className="copilot-main">
        {tab === 'memories' ? (
          <Memories />
        ) : current ? (
          <Chat key={current} conversationId={current} />
        ) : (
          <div className="chat-empty">
            <h2>Copiloto</h2>
            <p className="muted">Empieza una conversación nueva o abre una anterior.</p>
            <button className="btn btn-primary" onClick={() => create.mutate()}>
              Nueva conversación
            </button>
          </div>
        )}
      </section>
    </div>
  )
}
