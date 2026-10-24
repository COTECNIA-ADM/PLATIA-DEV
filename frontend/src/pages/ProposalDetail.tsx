// Propuesta: secciones editables, redacción con IA, revisiones, adjuntos, CV a medida
// y paquete final (DOCX, PDF y PPTX).
import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, download } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  FAMILIES,
  PROPOSAL_STATUS,
  PROPOSAL_TYPES,
  REVIEW_KINDS,
  SENIORITY,
  fmtBytes,
  fmtDateTime,
  fmtMoney,
  label,
} from '../lib/format'
import type { Page, ProfileSummary, Proposal, Section } from '../lib/types'
import { GenerationStatus, ProposalStatus } from '../components/status'
import { Markdown } from '../components/text'
import { Badge, Empty, ErrorBox, Field, Modal, Spinner, errorMessage, useDebounced, useToast } from '../components/ui'

const ATTACHMENT_KINDS: Record<string, string> = {
  generated: 'Paquete',
  cv: 'CV a medida',
  competitive_analysis: 'Análisis competitivo',
  other: 'Otro',
}

function conflictText(err: unknown) {
  return err instanceof ApiError && err.status === 409
    ? 'Alguien ha cambiado esto mientras lo editabas. Recarga para ver su versión.'
    : errorMessage(err)
}

function SectionCard({ proposal, section, editable, onSaved }: { proposal: Proposal; section: Section; editable: boolean; onSaved: () => void }) {
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const save = useMutation({
    mutationFn: (value: string | null) =>
      api<Section>(`/api/proposals/${proposal.id}/sections/${section.id}`, {
        method: 'PATCH',
        body: { version: section.version, edited_content: value },
      }),
    onSuccess: () => {
      setEditing(false)
      toast('Sección guardada')
      onSaved()
    },
  })
  const content = section.final_content
  const source = section.edited_content ? 'Editada a mano' : section.ai_content ? 'Redactada por la IA' : null
  return (
    <section className="card section-card" id={`section-${section.key}`}>
      <header className="card-head">
        <h3>{section.title}</h3>
        <div className="btn-row">
          {source && <Badge tone={section.edited_content ? 'accent' : 'info'}>{source}</Badge>}
          {editable && !editing && (
            <button
              className="btn btn-small"
              onClick={() => {
                setText(content ?? '')
                setEditing(true)
              }}
            >
              Editar
            </button>
          )}
        </div>
      </header>
      {editing ? (
        <div className="stack">
          <textarea className="editor" rows={14} value={text} onChange={(e) => setText(e.target.value)} />
          {save.error && <p className="notice notice-error">{conflictText(save.error)}</p>}
          <div className="actions">
            {section.edited_content && section.ai_content && (
              <button className="btn btn-ghost" onClick={() => save.mutate(null)} title="Descarta tu edición y vuelve al texto de la IA">
                Volver al texto de la IA
              </button>
            )}
            <button className="btn btn-ghost" onClick={() => setEditing(false)}>
              Cancelar
            </button>
            <button className="btn btn-primary" onClick={() => save.mutate(text)} disabled={save.isPending}>
              Guardar
            </button>
          </div>
        </div>
      ) : content ? (
        <Markdown text={content} />
      ) : (
        <p className="muted">Vacía. Redáctala con IA o escríbela a mano.</p>
      )}
    </section>
  )
}

function Generate({ proposal, onClose, onStarted }: { proposal: Proposal; onClose: () => void; onStarted: () => void }) {
  const pending = proposal.sections.filter((s) => !s.edited_content).map((s) => s.key)
  const [selected, setSelected] = useState<string[]>(pending)
  const [instructions, setInstructions] = useState('')
  const run = useMutation({
    mutationFn: () =>
      api(`/api/proposals/${proposal.id}/generate`, {
        body: { sections: selected, instructions: instructions.trim() || null },
      }),
    onSuccess: onStarted,
  })
  return (
    <Modal title="Redactar con IA" onClose={onClose}>
      <div className="stack">
        <p className="muted">
          La IA redacta con el análisis, los documentos vinculados y propuestas anteriores parecidas. Por defecto no toca lo que has
          editado a mano; si marcas una de esas secciones, se sustituye.
        </p>
        <fieldset className="facet">
          <legend>Secciones</legend>
          {proposal.sections.map((s) => (
            <label key={s.id} className="check">
              <input
                type="checkbox"
                checked={selected.includes(s.key)}
                onChange={() => setSelected(selected.includes(s.key) ? selected.filter((k) => k !== s.key) : [...selected, s.key])}
              />
              <span>{s.title}</span>
              {s.edited_content && <Badge tone="warning">editada</Badge>}
            </label>
          ))}
        </fieldset>
        <Field label="Indicaciones (opcional)" hint="Por ejemplo: «tono cercano, destaca la experiencia en el sector público».">
          <textarea rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={2000} />
        </Field>
        {run.error && <p className="notice notice-error">{errorMessage(run.error)}</p>}
        <div className="actions">
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" onClick={() => run.mutate()} disabled={!selected.length || run.isPending}>
            Redactar {selected.length} secciones
          </button>
        </div>
      </div>
    </Modal>
  )
}

function ReviewForm({ proposal, onClose, onDone }: { proposal: Proposal; onClose: () => void; onDone: () => void }) {
  const done = new Set(proposal.reviews.filter((r) => r.decision === 'approve').map((r) => r.kind))
  const kinds = proposal.required_reviews.includes('any') ? ['general', 'technical', 'executive', 'area'] : proposal.required_reviews
  const [kind, setKind] = useState(kinds.find((k) => !done.has(k)) ?? kinds[0])
  const [decision, setDecision] = useState<'approve' | 'reject'>('approve')
  const [comment, setComment] = useState('')
  const send = useMutation({
    mutationFn: () => api(`/api/proposals/${proposal.id}/reviews`, { body: { kind, decision, comment: comment || null } }),
    onSuccess: onDone,
  })
  return (
    <Modal title="Revisar la propuesta" onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          send.mutate()
        }}
      >
        <Field label="Tipo de revisión">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {label(REVIEW_KINDS, k)} {done.has(k) ? '(ya aprobada)' : ''}
              </option>
            ))}
          </select>
        </Field>
        <div className="segmented">
          <label className={decision === 'approve' ? 'on' : ''}>
            <input type="radio" checked={decision === 'approve'} onChange={() => setDecision('approve')} /> Aprobar
          </label>
          <label className={decision === 'reject' ? 'on' : ''}>
            <input type="radio" checked={decision === 'reject'} onChange={() => setDecision('reject')} /> Devolver a borrador
          </label>
        </div>
        <Field label={decision === 'reject' ? 'Qué hay que cambiar (obligatorio)' : 'Comentario (opcional)'}>
          <textarea rows={4} value={comment} onChange={(e) => setComment(e.target.value)} required={decision === 'reject'} maxLength={4000} />
        </Field>
        {send.error && <p className="notice notice-error">{errorMessage(send.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={send.isPending}>
            Enviar revisión
          </button>
        </div>
      </form>
    </Modal>
  )
}

function StatusAction({ proposal, target, onDone }: { proposal: Proposal; target: string; onDone: () => void }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [comment, setComment] = useState('')
  const needsComment = target === 'lost'
  const change = useMutation({
    mutationFn: () => api(`/api/proposals/${proposal.id}/status`, { body: { version: proposal.version, status: target, comment: comment || null } }),
    onSuccess: () => {
      toast(`Estado: ${label(PROPOSAL_STATUS, target)}`)
      setOpen(false)
      onDone()
    },
    onError: (err) => !open && toast(conflictText(err), 'danger'),
  })
  const text: Record<string, string> = {
    in_review: 'Enviar a revisión',
    sent: 'Marcar como enviada',
    won: 'Ganada',
    lost: 'Perdida',
    archived: 'Archivar',
    draft: 'Volver a borrador',
  }
  return (
    <>
      <button
        className={`btn btn-small${target === 'in_review' || target === 'sent' ? ' btn-primary' : ''}`}
        onClick={() => (needsComment || target === 'sent' ? setOpen(true) : change.mutate())}
        disabled={change.isPending}
      >
        {text[target] ?? label(PROPOSAL_STATUS, target)}
      </button>
      {open && (
        <Modal title={text[target] ?? target} onClose={() => setOpen(false)}>
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault()
              change.mutate()
            }}
          >
            {target === 'sent' && <p>Confirma que la propuesta se ha entregado al cliente. Después ya no se puede editar.</p>}
            <Field label={needsComment ? 'Motivo (obligatorio)' : 'Comentario (opcional)'}>
              <textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} required={needsComment} />
            </Field>
            {change.error && <p className="notice notice-error">{conflictText(change.error)}</p>}
            <div className="actions">
              <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
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

function TailorCV({ proposal, onClose, onStarted }: { proposal: Proposal; onClose: () => void; onStarted: () => void }) {
  const [text, setText] = useState('')
  const q = useDebounced(text, 250)
  const profiles = useQuery({
    queryKey: ['talent', 'pick', q],
    queryFn: () => api<Page<ProfileSummary>>('/api/talent/profiles', { query: { q, per_page: 10 } }),
  })
  const run = useMutation({
    mutationFn: (profileId: number) => api(`/api/proposals/${proposal.id}/cv`, { body: { profile_id: profileId } }),
    onSuccess: onStarted,
  })
  return (
    <Modal title="CV a medida" onClose={onClose}>
      <div className="stack">
        <p className="muted">
          La IA adapta el CV a esta oportunidad usando solo lo que hay en el perfil: no inventa competencias ni experiencias. Se adjunta en
          Word y PDF.
        </p>
        <input type="search" placeholder="Buscar perfil por nombre o competencia" value={text} onChange={(e) => setText(e.target.value)} autoFocus />
        {profiles.isLoading && <Spinner />}
        {run.error && <p className="notice notice-error">{errorMessage(run.error)}</p>}
        {profiles.data && !profiles.data.items.length && <p className="muted">No hay perfiles que coincidan.</p>}
        <ul className="pick-list">
          {profiles.data?.items.map((p) => (
            <li key={p.id}>
              <span>
                <strong>{p.full_name}</strong> {p.headline && <span className="muted">· {p.headline}</span>}
                <div className="row-sub">
                  {[label(FAMILIES, p.family), label(SENIORITY, p.seniority), p.skills.slice(0, 5).join(', ')].filter((x) => x && x !== '—').join(' · ')}
                </div>
              </span>
              <button className="btn btn-small" onClick={() => run.mutate(p.id)} disabled={run.isPending}>
                Preparar CV
              </button>
            </li>
          ))}
        </ul>
      </div>
    </Modal>
  )
}

function EditHeader({ proposal, onClose, onSaved }: { proposal: Proposal; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(proposal.title)
  const [amount, setAmount] = useState(proposal.total_amount_eur ?? '')
  const save = useMutation({
    mutationFn: () =>
      api(`/api/proposals/${proposal.id}`, { method: 'PATCH', body: { version: proposal.version, title, total_amount_eur: amount || null } }),
    onSuccess: onSaved,
  })
  return (
    <Modal title="Editar propuesta" onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Field label="Título">
          <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={500} />
        </Field>
        <Field label="Importe total (€)" hint="Necesario para marcarla como enviada.">
          <input type="number" min={0} step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        {save.error && <p className="notice notice-error">{conflictText(save.error)}</p>}
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

export default function ProposalDetail() {
  const id = Number(useParams().id)
  const toast = useToast()
  const { can, canModify, hasAI, user } = useAuth()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [dialog, setDialog] = useState<'generate' | 'review' | 'cv' | 'edit' | null>(null)
  const [attachKind, setAttachKind] = useState('other')
  const key = ['proposals', id]
  const { data: p, error, isLoading, refetch } = useQuery({
    queryKey: key,
    queryFn: () => api<Proposal>(`/api/proposals/${id}`),
    refetchInterval: (q) => {
      const s = q.state.data?.generation_status
      return s === 'queued' || s === 'running' ? 4000 : false
    },
  })

  const refresh = () => {
    void refetch()
    void queryClient.invalidateQueries({ queryKey: ['proposals', 'list'] })
  }
  const pkg = useMutation({
    mutationFn: () => api(`/api/proposals/${id}/package`, { method: 'POST' }),
    onSuccess: () => toast('Preparando el paquete. Te avisaremos cuando esté listo.'),
    onError: (err) => toast(errorMessage(err), 'danger'),
  })
  const attach = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      form.append('kind', attachKind)
      return api(`/api/proposals/${id}/attachments`, { form })
    },
    onSuccess: () => {
      toast('Adjunto subido')
      refresh()
    },
    onError: (err) => toast(errorMessage(err), 'danger'),
  })
  const removeAttachment = useMutation({
    mutationFn: (attachmentId: number) => api(`/api/proposals/${id}/attachments/${attachmentId}`, { method: 'DELETE' }),
    onSuccess: refresh,
    onError: (err) => toast(errorMessage(err), 'danger'),
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!p) return null

  const mine = canModify('proposals', p.owner_user_id)
  const writable = can('proposals', 'write') && mine
  const editable = writable && p.status === 'draft'
  const generating = p.generation_status === 'queued' || p.generation_status === 'running'
  const isOwner = p.owner_user_id === user?.id
  const canReview = p.status === 'in_review' && can('proposals', 'approve') && (!isOwner || user?.is_superadmin)
  const transitions = p.allowed_transitions.filter((t) => t !== 'sent' || can('proposals', 'send'))
  const generated = p.attachments.filter((a) => a.kind === 'generated')
  const others = p.attachments.filter((a) => a.kind !== 'generated')

  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/proposals">Propuestas</Link> / <Link to={`/opportunities/${p.opportunity_id}`}>{p.opportunity_title}</Link>
      </nav>
      <header className="page-head">
        <div>
          <h1>{p.title}</h1>
          <div className="meta-row">
            <ProposalStatus status={p.status} />
            <Badge>{label(PROPOSAL_TYPES, p.proposal_type)}</Badge>
            <GenerationStatus status={p.generation_status} />
            <span className="muted">
              v{p.version_number} · {fmtMoney(p.total_amount_eur)}
            </span>
          </div>
        </div>
        <div className="btn-row">
          {writable && p.status === 'draft' && (
            <button className="btn" onClick={() => setDialog('edit')}>
              Editar
            </button>
          )}
          {editable && hasAI('proposal_generator') && (
            <button className="btn btn-primary" onClick={() => setDialog('generate')} disabled={generating}>
              {generating ? 'Redactando…' : 'Redactar con IA'}
            </button>
          )}
        </div>
      </header>

      {generating && <Spinner label="La IA está redactando. Las secciones aparecen según terminan; puedes salir y volver." />}
      {p.generation_status === 'failed' && <p className="notice notice-error">La redacción falló: {p.generation_error}</p>}

      {(transitions.length > 0 && writable) || canReview ? (
        <div className="card workflow">
          <div>
            <strong>Siguiente paso</strong>
            {p.status === 'in_review' && (
              <p className="muted">
                Revisiones necesarias: {p.required_reviews.map((k) => label(REVIEW_KINDS, k)).join(', ')}. Hechas en esta ronda:{' '}
                {p.reviews.filter((r) => r.decision === 'approve').map((r) => label(REVIEW_KINDS, r.kind)).join(', ') || 'ninguna'}.
              </p>
            )}
          </div>
          <div className="btn-row">
            {canReview && (
              <button className="btn btn-primary btn-small" onClick={() => setDialog('review')}>
                Revisar
              </button>
            )}
            {writable && transitions.map((t) => <StatusAction key={t} proposal={p} target={t} onDone={refresh} />)}
          </div>
        </div>
      ) : null}

      <div className="detail-grid">
        <div className="stack">
          {!p.sections.length && <Empty title="Sin secciones" />}
          {p.sections.map((s) => (
            <SectionCard key={s.id} proposal={p} section={s} editable={editable && !generating} onSaved={refresh} />
          ))}
        </div>
        <aside className="stack">
          <section className="card toc">
            <h2>Índice</h2>
            <ol>
              {p.sections.map((s) => (
                <li key={s.id}>
                  <a href={`#section-${s.key}`}>{s.title}</a> {!s.final_content && <span className="muted">(vacía)</span>}
                </li>
              ))}
            </ol>
          </section>

          <section className="card">
            <header className="card-head">
              <h2>Paquete final</h2>
              {['approved', 'sent', 'won', 'lost'].includes(p.status) && can('proposals', 'write') && (
                <button className="btn btn-small" onClick={() => pkg.mutate()} disabled={pkg.isPending}>
                  Regenerar
                </button>
              )}
            </header>
            {!generated.length && <p className="muted">Se genera al aprobarse: Word, PDF y PowerPoint.</p>}
            <ul className="plain-list">
              {generated.map((a) => (
                <li key={a.id}>
                  <button className="btn-link" onClick={() => void download(`/api/proposals/${id}/attachments/${a.id}`, a.filename).catch((e) => toast(errorMessage(e), 'danger'))}>
                    {a.filename}
                  </button>{' '}
                  <span className="muted">{fmtBytes(a.file_size_bytes)}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="card">
            <header className="card-head">
              <h2>Adjuntos</h2>
              {writable && can('talent', 'read') && hasAI('proposal_generator') && (
                <button className="btn btn-small" onClick={() => setDialog('cv')}>
                  CV a medida
                </button>
              )}
            </header>
            {!others.length && <p className="muted">Sin adjuntos.</p>}
            <ul className="plain-list">
              {others.map((a) => (
                <li key={a.id} className="row-between">
                  <span>
                    <button className="btn-link" onClick={() => void download(`/api/proposals/${id}/attachments/${a.id}`, a.filename).catch((e) => toast(errorMessage(e), 'danger'))}>
                      {a.filename}
                    </button>{' '}
                    <Badge>{label(ATTACHMENT_KINDS, a.kind)}</Badge>
                  </span>
                  {editable && (
                    <button className="btn btn-small btn-ghost" onClick={() => removeAttachment.mutate(a.id)}>
                      Quitar
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {writable && (
              <div className="inline-upload">
                <select value={attachKind} onChange={(e) => setAttachKind(e.target.value)} aria-label="Tipo de adjunto">
                  <option value="other">Otro</option>
                  <option value="competitive_analysis">Análisis competitivo</option>
                </select>
                <button className="btn btn-small" onClick={() => fileInput.current?.click()} disabled={attach.isPending}>
                  Subir adjunto
                </button>
                <input
                  ref={fileInput}
                  type="file"
                  hidden
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) attach.mutate(file)
                    e.target.value = ''
                  }}
                />
              </div>
            )}
            {p.proposal_type === 'competitive' && p.status === 'draft' && !others.some((a) => a.kind === 'competitive_analysis') && (
              <p className="notice notice-warning">Una propuesta competitiva necesita un análisis competitivo adjunto antes de ir a revisión.</p>
            )}
          </section>

          {p.reviews.length > 0 && (
            <section className="card">
              <h2>Revisiones (ronda {p.review_round})</h2>
              <ul className="plain-list">
                {p.reviews.map((r) => (
                  <li key={r.id}>
                    <Badge tone={r.decision === 'approve' ? 'success' : 'danger'}>{r.decision === 'approve' ? 'Aprobada' : 'Devuelta'}</Badge>{' '}
                    {label(REVIEW_KINDS, r.kind)} <span className="muted">{fmtDateTime(r.created_at)}</span>
                    {r.comment && <p className="row-sub">{r.comment}</p>}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
      </div>

      {dialog === 'generate' && (
        <Generate
          proposal={p}
          onClose={() => setDialog(null)}
          onStarted={() => {
            setDialog(null)
            toast('Redacción en marcha')
            refresh()
          }}
        />
      )}
      {dialog === 'review' && (
        <ReviewForm
          proposal={p}
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null)
            toast('Revisión registrada')
            refresh()
          }}
        />
      )}
      {dialog === 'cv' && (
        <TailorCV
          proposal={p}
          onClose={() => setDialog(null)}
          onStarted={() => {
            setDialog(null)
            toast('Preparando el CV. Aparecerá en los adjuntos y te llegará un aviso.')
          }}
        />
      )}
      {dialog === 'edit' && (
        <EditHeader
          proposal={p}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}
