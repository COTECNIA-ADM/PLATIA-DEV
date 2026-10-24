import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  DOC_LINK_ROLES,
  OPPORTUNITY_STATUS,
  PHASES,
  PROPOSAL_TYPES,
  daysUntil,
  fmtDate,
  fmtMoney,
  label,
} from '../lib/format'
import type { DocumentSummary, Opportunity, Page, SimilarOpportunity, Template } from '../lib/types'
import AnalysisPanel from '../components/AnalysisPanel'
import { DocumentStatus, OpportunityStatus, ProposalStatus } from '../components/status'
import { Empty, ErrorBox, Field, Modal, ScoreBar, Spinner, errorMessage, useDebounced, useToast } from '../components/ui'
import { useServiceLines } from './Opportunities'

const BREAKDOWN: Record<string, string> = {
  keywords: 'Palabras clave',
  taxonomy: 'Códigos CPV',
  text: 'Texto',
  semantic: 'Parecido semántico',
  win_rate: 'Tasa de éxito de la línea',
}

function StatusChanger({ opp, onDone }: { opp: Opportunity; onDone: (o: Opportunity) => void }) {
  const toast = useToast()
  const [target, setTarget] = useState<string | null>(null)
  const [comment, setComment] = useState('')
  const change = useMutation({
    mutationFn: () =>
      api<Opportunity>(`/api/opportunities/${opp.id}/status`, {
        body: { version: opp.version, status: target, comment: comment || null },
      }),
    onSuccess: (o) => {
      toast(`Estado: ${label(OPPORTUNITY_STATUS, o.status)}`)
      setTarget(null)
      setComment('')
      onDone(o)
    },
  })
  if (!opp.allowed_transitions.length) return null
  return (
    <>
      <div className="btn-row status-actions">
        {opp.allowed_transitions.map((s) => (
          <button key={s} className={`btn btn-small${s === 'discarded' || s === 'lost' ? ' btn-danger-ghost' : ''}`} onClick={() => setTarget(s)}>
            {s === 'discarded' ? 'Descartar' : `→ ${label(OPPORTUNITY_STATUS, s)}`}
          </button>
        ))}
      </div>
      {target && (
        <Modal title={`Cambiar a «${label(OPPORTUNITY_STATUS, target)}»`} onClose={() => setTarget(null)}>
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault()
              change.mutate()
            }}
          >
            <Field label={target === 'discarded' ? 'Motivo (obligatorio)' : 'Comentario (opcional)'}>
              <textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} required={target === 'discarded'} maxLength={2000} />
            </Field>
            {change.error && (
              <p className="notice notice-error">
                {change.error instanceof ApiError && change.error.status === 409
                  ? 'Alguien ha cambiado la oportunidad mientras la mirabas. Recarga y vuelve a intentarlo.'
                  : errorMessage(change.error)}
              </p>
            )}
            <div className="actions">
              <button type="button" className="btn btn-ghost" onClick={() => setTarget(null)}>
                Cancelar
              </button>
              <button className="btn btn-primary" disabled={change.isPending}>
                Confirmar
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}

function EditOpportunity({ opp, onClose, onSaved }: { opp: Opportunity; onClose: () => void; onSaved: (o: Opportunity) => void }) {
  const lines = useServiceLines()
  const [form, setForm] = useState({
    title: opp.title,
    description: opp.description ?? '',
    service_line: opp.service_line ?? '',
    estimated_value_eur: opp.estimated_value_eur ?? '',
    probability: opp.probability?.toString() ?? '',
    deadline: opp.deadline ? opp.deadline.slice(0, 10) : '',
    contracting_entity: opp.contracting_entity ?? '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })
  const save = useMutation({
    mutationFn: () =>
      api<Opportunity>(`/api/opportunities/${opp.id}`, {
        method: 'PATCH',
        body: {
          version: opp.version,
          title: form.title,
          description: form.description || null,
          service_line: form.service_line || null,
          estimated_value_eur: form.estimated_value_eur || null,
          probability: form.probability ? Number(form.probability) : null,
          deadline: form.deadline ? new Date(`${form.deadline}T23:59:00`).toISOString() : null,
          contracting_entity: form.contracting_entity || null,
        },
      }),
    onSuccess: onSaved,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title="Editar oportunidad" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <Field label="Título">
          <input value={form.title} onChange={set('title')} required maxLength={500} />
        </Field>
        <Field label="Descripción">
          <textarea rows={5} value={form.description} onChange={set('description')} />
        </Field>
        <div className="grid-2">
          <Field label="Línea de servicio">
            <select value={form.service_line} onChange={set('service_line')}>
              <option value="">—</option>
              {lines.data?.items.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Importe estimado (€)">
            <input type="number" min={0} step="0.01" value={form.estimated_value_eur} onChange={set('estimated_value_eur')} />
          </Field>
          <Field label="Probabilidad (%)">
            <input type="number" min={0} max={100} value={form.probability} onChange={set('probability')} />
          </Field>
          <Field label="Fecha límite">
            <input type="date" value={form.deadline} onChange={set('deadline')} />
          </Field>
        </div>
        <Field label="Entidad contratante">
          <input value={form.contracting_entity} onChange={set('contracting_entity')} maxLength={255} />
        </Field>
        {save.error && (
          <p className="notice notice-error">
            {save.error instanceof ApiError && save.error.status === 409
              ? 'Alguien ha cambiado la oportunidad mientras la editabas. Cierra, recarga y vuelve a intentarlo.'
              : errorMessage(save.error)}
          </p>
        )}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Guardar
          </button>
        </div>
      </form>
    </Modal>
  )
}

function LinkDocument({ opp, onClose, onLinked }: { opp: Opportunity; onClose: () => void; onLinked: (o: Opportunity) => void }) {
  const [text, setText] = useState('')
  const [role, setRole] = useState('requirements')
  const q = useDebounced(text, 250)
  const docs = useQuery({
    queryKey: ['documents', 'pick', q],
    queryFn: () => api<Page<DocumentSummary>>('/api/documents', { query: { q, per_page: 10 } }),
  })
  const link = useMutation({
    mutationFn: (documentId: number) =>
      api<Opportunity>(`/api/opportunities/${opp.id}/documents`, { body: { document_id: documentId, role } }),
    onSuccess: onLinked,
  })
  const linked = new Set(opp.documents.map((d) => d.document_id))
  return (
    <Modal title="Vincular un documento" onClose={onClose}>
      <div className="stack">
        <div className="grid-2">
          <input type="search" placeholder="Buscar documento" value={text} onChange={(e) => setText(e.target.value)} autoFocus />
          <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Papel del documento">
            {Object.entries(DOC_LINK_ROLES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        {link.error && <p className="notice notice-error">{errorMessage(link.error)}</p>}
        {docs.isLoading && <Spinner />}
        <ul className="pick-list">
          {docs.data?.items.map((d) => (
            <li key={d.id}>
              <span>
                {d.title} <DocumentStatus status={d.processing_status} />
              </span>
              <button className="btn btn-small" disabled={linked.has(d.id) || link.isPending} onClick={() => link.mutate(d.id)}>
                {linked.has(d.id) ? 'Ya vinculado' : 'Vincular'}
              </button>
            </li>
          ))}
        </ul>
        <p className="muted">
          ¿No está? <Link to="/documents">Súbelo en Documentos</Link> y vuelve aquí.
        </p>
      </div>
    </Modal>
  )
}

function NewProposal({ opp, onClose }: { opp: Opportunity; onClose: () => void }) {
  const navigate = useNavigate()
  const [type, setType] = useState('base')
  const [templateId, setTemplateId] = useState('')
  const templates = useQuery({
    queryKey: ['templates', type],
    queryFn: () => api<Page<Template>>('/api/proposal-templates', { query: { proposal_type: type } }),
  })
  const create = useMutation({
    mutationFn: () =>
      api<{ id: number }>('/api/proposals', {
        body: { opportunity_id: opp.id, proposal_type: type, template_id: templateId ? Number(templateId) : null },
      }),
    onSuccess: (p) => navigate(`/proposals/${p.id}`),
  })
  return (
    <Modal title="Nueva propuesta" onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate()
        }}
      >
        <Field label="Tipo">
          <select value={type} onChange={(e) => (setType(e.target.value), setTemplateId(''))}>
            {Object.entries(PROPOSAL_TYPES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Plantilla" hint="Define las secciones. Sin plantilla se usa la estándar del tipo.">
          <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            <option value="">Estándar</option>
            {templates.data?.items.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.sections.length} secciones)
              </option>
            ))}
          </select>
        </Field>
        {create.error && <p className="notice notice-error">{errorMessage(create.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={create.isPending}>
            Crear propuesta
          </button>
        </div>
      </form>
    </Modal>
  )
}

function Similar({ id }: { id: number }) {
  const { data, error, isLoading } = useQuery({
    queryKey: ['similar', id],
    queryFn: () => api<{ items: SimilarOpportunity[] }>(`/api/opportunities/${id}/similar`),
    retry: false,
  })
  return (
    <section className="card">
      <h2>Oportunidades parecidas</h2>
      {isLoading && <Spinner />}
      {error && <p className="muted">{errorMessage(error)}</p>}
      {data && !data.items.length && <p className="muted">No hay ninguna lo bastante parecida.</p>}
      <ul className="plain-list">
        {data?.items.map((s) => (
          <li key={s.opportunity_id}>
            <Link to={`/opportunities/${s.opportunity_id}`}>{s.title}</Link>{' '}
            <span className="muted">
              {label(OPPORTUNITY_STATUS, s.status)} · {Math.round(s.score * 100)} % parecida
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function OpportunityDetail() {
  const id = Number(useParams().id)
  const { can, canModify, hasAI } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [linking, setLinking] = useState(false)
  const [proposing, setProposing] = useState(false)
  const key = ['opportunities', id]
  const { data: opp, error, isLoading, refetch } = useQuery({
    queryKey: key,
    queryFn: () => api<Opportunity>(`/api/opportunities/${id}`),
  })
  const lines = useServiceLines()

  const updated = (o: Opportunity) => {
    queryClient.setQueryData(key, o)
    void queryClient.invalidateQueries({ queryKey: ['opportunities', 'search'] })
  }
  const rescore = useMutation({
    mutationFn: () => api(`/api/opportunities/${id}/score`, { method: 'POST' }),
    onSuccess: () => {
      toast('Puntuación recalculada')
      void refetch()
    },
    onError: (err) => toast(errorMessage(err), 'danger'),
  })
  const unlink = useMutation({
    mutationFn: (docId: number) => api(`/api/opportunities/${id}/documents/${docId}`, { method: 'DELETE' }),
    onSuccess: () => void refetch(),
    onError: (err) => toast(errorMessage(err), 'danger'),
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!opp) return null

  const mine = canModify('opportunities', opp.owner_user_id)
  const writable = can('opportunities', 'write') && mine
  const days = daysUntil(opp.deadline)
  const lineName = lines.data?.items.find((l) => l.code === opp.service_line)?.name ?? opp.service_line
  const hasText = !!opp.description?.trim() || opp.documents.length > 0

  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/opportunities">Oportunidades</Link> / {opp.code ?? `#${opp.id}`}
      </nav>
      <header className="page-head">
        <div>
          <h1>{opp.title}</h1>
          <div className="meta-row">
            <OpportunityStatus status={opp.status} />
            <span className="muted">{label(PHASES, opp.phase)}</span>
            {opp.client_name && <Link to={`/clients/${opp.client_id}`}>{opp.client_name}</Link>}
            {opp.link && (
              <a href={opp.link} target="_blank" rel="noreferrer noopener">
                Ver en el portal ↗
              </a>
            )}
          </div>
        </div>
        <div className="btn-row">
          {hasAI('copilot_chat') && can('copilot', 'write') && (
            <Link className="btn" to={`/copilot?opportunity=${opp.id}`}>
              Preguntar al copiloto
            </Link>
          )}
          {writable && (
            <button className="btn" onClick={() => setEditing(true)}>
              Editar
            </button>
          )}
          {can('proposals', 'write') && (
            <button className="btn btn-primary" onClick={() => setProposing(true)}>
              Nueva propuesta
            </button>
          )}
        </div>
      </header>

      {writable && <StatusChanger opp={opp} onDone={updated} />}

      <div className="detail-grid">
        <div className="stack">
          <section className="card">
            <h2>Descripción</h2>
            {opp.description ? <p className="pre-line">{opp.description}</p> : <p className="muted">Sin descripción.</p>}
            {opp.ai_summary && (
              <p className="callout">
                <strong>Resumen IA:</strong> {opp.ai_summary}
              </p>
            )}
          </section>

          <AnalysisPanel
            path={`/api/opportunities/${id}`}
            canRun={can('opportunities', 'write') && hasAI('document_analyzer')}
            disabledReason={hasText ? undefined : 'Añade una descripción o vincula el pliego para poder analizarla.'}
          />

          <section className="card">
            <header className="card-head">
              <h2>Documentos</h2>
              {writable && (
                <button className="btn btn-small" onClick={() => setLinking(true)}>
                  Vincular documento
                </button>
              )}
            </header>
            {!opp.documents.length && <Empty title="Sin documentos">Vincula el pliego para analizarlo con la oportunidad.</Empty>}
            <ul className="plain-list">
              {opp.documents.map((d) => (
                <li key={d.document_id} className="row-between">
                  <span>
                    <Link to={`/documents/${d.document_id}`}>{d.title}</Link>{' '}
                    <span className="muted">{label(DOC_LINK_ROLES, d.role)}</span> <DocumentStatus status={d.processing_status} />
                  </span>
                  {writable && (
                    <button className="btn btn-small btn-ghost" onClick={() => unlink.mutate(d.document_id)}>
                      Quitar
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>

          <section className="card">
            <h2>Propuestas</h2>
            {!opp.proposals.length && <p className="muted">Todavía no hay propuestas.</p>}
            <ul className="plain-list">
              {opp.proposals.map((p) => (
                <li key={p.id}>
                  <Link to={`/proposals/${p.id}`}>{p.title}</Link> <ProposalStatus status={p.status} />{' '}
                  <span className="muted">
                    {label(PROPOSAL_TYPES, p.proposal_type)} · v{p.version_number}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <aside className="stack">
          <section className="card">
            <dl className="facts">
              <dt>Importe estimado</dt>
              <dd>{fmtMoney(opp.estimated_value_eur)}</dd>
              <dt>Probabilidad</dt>
              <dd>{opp.probability !== null ? `${opp.probability} %` : '—'}</dd>
              <dt>Fecha límite</dt>
              <dd className={days !== null && days >= 0 && days <= 7 ? 'text-warning' : undefined}>
                {fmtDate(opp.deadline)}
                {days !== null && (days >= 0 ? ` (en ${days} días)` : ' (vencida)')}
              </dd>
              <dt>Entidad</dt>
              <dd>{opp.contracting_entity ?? '—'}</dd>
              <dt>Línea de servicio</dt>
              <dd>{lineName ?? '—'}</dd>
              <dt>Origen</dt>
              <dd>{opp.source ?? '—'}</dd>
              {opp.cpv_codes.length > 0 && (
                <>
                  <dt>CPV</dt>
                  <dd>{opp.cpv_codes.join(', ')}</dd>
                </>
              )}
              <dt>Publicada</dt>
              <dd>{fmtDate(opp.published_at)}</dd>
            </dl>
          </section>
          <section className="card">
            <header className="card-head">
              <h2>Relevancia</h2>
              {can('opportunities', 'write') && (
                <button className="btn btn-small" onClick={() => rescore.mutate()} disabled={rescore.isPending}>
                  Recalcular
                </button>
              )}
            </header>
            <ScoreBar value={opp.relevance_score} />
            {opp.score_breakdown && (
              <dl className="facts facts-compact">
                {Object.entries(BREAKDOWN).map(([k, v]) =>
                  opp.score_breakdown?.[k] !== undefined && opp.score_breakdown?.[k] !== null ? (
                    <div key={k} className="facts-pair">
                      <dt>{v}</dt>
                      <dd>
                        {k === 'win_rate' || k === 'semantic'
                          ? `${Math.round(Number(opp.score_breakdown[k]) * 100)} %`
                          : Number(opp.score_breakdown[k]).toFixed(1)}
                      </dd>
                    </div>
                  ) : null,
                )}
              </dl>
            )}
          </section>
          <Similar id={id} />
        </aside>
      </div>

      {editing && (
        <EditOpportunity
          opp={opp}
          onClose={() => setEditing(false)}
          onSaved={(o) => {
            updated(o)
            setEditing(false)
            toast('Cambios guardados')
          }}
        />
      )}
      {linking && (
        <LinkDocument
          opp={opp}
          onClose={() => setLinking(false)}
          onLinked={(o) => {
            updated(o)
            setLinking(false)
          }}
        />
      )}
      {proposing && <NewProposal opp={opp} onClose={() => setProposing(false)} />}
    </div>
  )
}
