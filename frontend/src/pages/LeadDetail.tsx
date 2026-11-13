// Detalle de una solicitud del formulario web y la decisión de comercial (caso P2, ADR-020).
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime } from '../lib/format'
import type { ClientSummary, Lead, Page } from '../lib/types'
import { ErrorBox, Field, Spinner, errorMessage, useDebounced, useToast } from '../components/ui'
import { LeadStatusBadge } from './Leads'

type Action = 'contact' | 'opportunity' | 'discard'

function ClientPicker({ lead, value, onChange }: { lead: Lead; value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState('')
  const q = useDebounced(text.trim(), 300)
  const found = useQuery({
    queryKey: ['clients', 'list', q, '', 1],
    queryFn: () => api<Page<ClientSummary>>('/api/clients', { query: { q, per_page: 10 } }),
    enabled: value === 'search' && q.length >= 2,
  })
  return (
    <fieldset className="stack">
      <legend>Cliente</legend>
      {lead.matches.map((m) => (
        <label key={m.id} className="check">
          <input type="radio" name="client" checked={value === `id:${m.id}`} onChange={() => onChange(`id:${m.id}`)} />
          {m.name} {m.tax_id && <span className="muted">· {m.tax_id}</span>} <span className="muted">(ya existe)</span>
        </label>
      ))}
      <label className="check">
        <input type="radio" name="client" checked={value === 'new'} onChange={() => onChange('new')} />
        Cliente nuevo
      </label>
      <label className="check">
        <input type="radio" name="client" checked={value === 'search' || (value.startsWith('id:') && !lead.matches.some((m) => value === `id:${m.id}`))} onChange={() => onChange('search')} />
        Otro cliente que ya existe
      </label>
      {(value === 'search' || (value.startsWith('id:') && !lead.matches.some((m) => value === `id:${m.id}`))) && (
        <div className="stack">
          <input type="search" placeholder="Busca por nombre o CIF" value={text} onChange={(e) => setText(e.target.value)} aria-label="Buscar cliente" />
          {found.data && (
            <select value={value.startsWith('id:') ? value : ''} onChange={(e) => onChange(e.target.value || 'search')} aria-label="Cliente encontrado">
              <option value="">{found.data.items.length ? 'Elige un cliente' : 'Sin resultados'}</option>
              {found.data.items.map((c) => (
                <option key={c.id} value={`id:${c.id}`}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
        </div>
      )}
    </fieldset>
  )
}

function Resolve({ lead }: { lead: Lead }) {
  const { can } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const canContact = can('clients', 'write')
  const canOpportunity = canContact && can('opportunities', 'write')
  const [action, setAction] = useState<Action>(canOpportunity ? 'opportunity' : canContact ? 'contact' : 'discard')
  const [client, setClient] = useState(lead.matches.length ? `id:${lead.matches[0].id}` : 'new')
  const [clientName, setClientName] = useState(lead.company ?? '')
  const [title, setTitle] = useState(lead.subject ?? '')
  const [note, setNote] = useState('')
  const resolve = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { version: lead.version, action, note: note.trim() || null }
      if (action !== 'discard') {
        if (client.startsWith('id:')) body.client_id = Number(client.slice(3))
        else if (clientName.trim()) body.new_client_name = clientName.trim()
      }
      if (action === 'opportunity' && title.trim()) body.opportunity_title = title.trim()
      return api<Lead>(`/api/leads/${lead.id}/resolve`, { body })
    },
    onSuccess: (data) => {
      qc.setQueryData(['leads', 'detail', String(lead.id)], data)
      void qc.invalidateQueries({ queryKey: ['leads', 'list'] })
      toast(data.status === 'discarded' ? 'Solicitud descartada' : 'Solicitud convertida')
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    resolve.mutate()
  }
  const pickingClient = action !== 'discard'
  const missingClient = pickingClient && (client === 'search' || (client === 'new' && !clientName.trim()))
  return (
    <section className="card">
      <h2>¿Qué hacemos con ella?</h2>
      <form className="stack" onSubmit={submit}>
        <fieldset className="stack">
          <legend>Decisión</legend>
          <label className="check">
            <input type="radio" name="action" checked={action === 'opportunity'} disabled={!canOpportunity} onChange={() => setAction('opportunity')} />
            Crear contacto y oportunidad
          </label>
          <label className="check">
            <input type="radio" name="action" checked={action === 'contact'} disabled={!canContact} onChange={() => setAction('contact')} />
            Solo crear el contacto
          </label>
          <label className="check">
            <input type="radio" name="action" checked={action === 'discard'} onChange={() => setAction('discard')} />
            Descartar
          </label>
        </fieldset>
        {pickingClient && <ClientPicker lead={lead} value={client} onChange={setClient} />}
        {pickingClient && client === 'new' && (
          <Field label="Nombre del cliente nuevo">
            <input value={clientName} onChange={(e) => setClientName(e.target.value)} maxLength={255} required />
          </Field>
        )}
        {action === 'opportunity' && (
          <Field label="Título de la oportunidad" hint="Si lo dejas vacío, se usa el asunto de la solicitud.">
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={500} />
          </Field>
        )}
        <Field label="Nota (opcional)">
          <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        </Field>
        {resolve.error && <p className="notice notice-error">{errorMessage(resolve.error)}</p>}
        <div className="actions">
          <button className="btn btn-primary" disabled={resolve.isPending || missingClient}>
            {action === 'discard' ? 'Descartar' : 'Convertir'}
          </button>
        </div>
      </form>
    </section>
  )
}

function Outcome({ lead }: { lead: Lead }) {
  return (
    <section className="card">
      <h2>Decisión</h2>
      <p>
        <LeadStatusBadge lead={lead} /> {fmtDateTime(lead.resolved_at)}
      </p>
      <ul className="plain-list">
        {lead.client_id && (
          <li>
            <Link to={`/clients/${lead.client_id}`}>Ver el cliente y su contacto</Link>
          </li>
        )}
        {lead.opportunity_id && (
          <li>
            <Link to={`/opportunities/${lead.opportunity_id}`}>Ver la oportunidad</Link>
          </li>
        )}
      </ul>
      {lead.resolution_note && <p className="text-block">{lead.resolution_note}</p>}
    </section>
  )
}

export default function LeadDetail() {
  const { id } = useParams()
  const { can } = useAuth()
  const { data: lead, error, isLoading, refetch } = useQuery({
    queryKey: ['leads', 'detail', id],
    queryFn: () => api<Lead>(`/api/leads/${id}`),
  })
  if (isLoading) return <Spinner />
  if (error || !lead) return <ErrorBox error={error} onRetry={() => void refetch()} />
  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/leads">Solicitudes</Link>
      </nav>
      <header className="page-head">
        <div>
          <h1>{lead.subject || `Solicitud de ${lead.full_name}`}</h1>
          <div className="meta-row">
            <LeadStatusBadge lead={lead} />
            <span className="muted">Recibida {fmtDateTime(lead.created_at)}</span>
            <span className="muted">{lead.ack_sent ? 'Acuse enviado' : 'Sin acuse'}</span>
          </div>
        </div>
      </header>
      <div className="detail-grid">
        <div className="stack">
          <section className="card">
            <h2>Mensaje</h2>
            {lead.message ? <p className="text-block">{lead.message}</p> : <p className="muted">Sin mensaje.</p>}
          </section>
          {lead.status === 'new' && can('leads', 'manage') && <Resolve lead={lead} />}
          {lead.status !== 'new' && <Outcome lead={lead} />}
        </div>
        <aside className="stack">
          <section className="card">
            <h2>Quién escribe</h2>
            <dl className="facts">
              <dt>Nombre</dt>
              <dd>{lead.full_name}</dd>
              <dt>Correo</dt>
              <dd>{lead.email}</dd>
              <dt>Teléfono</dt>
              <dd>{lead.phone ?? '—'}</dd>
              <dt>Empresa</dt>
              <dd>{lead.company ?? '—'}</dd>
              <dt>CIF / NIF</dt>
              <dd>{lead.tax_id ?? '—'}</dd>
            </dl>
          </section>
        </aside>
      </div>
    </div>
  )
}
