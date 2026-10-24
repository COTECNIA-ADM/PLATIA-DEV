import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDate, fmtMoney } from '../lib/format'
import type { Client, Contact, OpportunitySummary, Page } from '../lib/types'
import { OpportunityStatus } from '../components/status'
import { Badge, ErrorBox, Field, Modal, Spinner, errorMessage, useToast } from '../components/ui'
import { ClientForm, RISK, SECTORS, SEGMENTS } from './Clients'

const PROJECT_STATUS: Record<string, string> = { active: 'En curso', completed: 'Terminado', on_hold: 'En pausa', cancelled: 'Cancelado' }

function ContactForm({ clientId, contact, onClose, onSaved }: { clientId: number; contact?: Contact; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    full_name: contact?.full_name ?? '',
    email: contact?.email ?? '',
    phone: contact?.phone ?? '',
    position: contact?.position ?? '',
  })
  const [primary, setPrimary] = useState(contact?.is_primary ?? false)
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })
  const save = useMutation({
    mutationFn: () => {
      const body = { ...Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v || null])), is_primary: primary }
      return contact
        ? api(`/api/clients/${clientId}/contacts/${contact.id}`, { method: 'PATCH', body: { ...body, version: contact.version } })
        : api(`/api/clients/${clientId}/contacts`, { body })
    },
    onSuccess: onSaved,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title={contact ? 'Editar contacto' : 'Nuevo contacto'} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <Field label="Nombre">
          <input value={form.full_name} onChange={set('full_name')} required maxLength={255} autoFocus />
        </Field>
        <div className="grid-2">
          <Field label="Email">
            <input type="email" value={form.email} onChange={set('email')} maxLength={255} />
          </Field>
          <Field label="Teléfono">
            <input value={form.phone} onChange={set('phone')} maxLength={50} />
          </Field>
        </div>
        <Field label="Cargo">
          <input value={form.position} onChange={set('position')} maxLength={150} />
        </Field>
        <label className="check">
          <input type="checkbox" checked={primary} onChange={(e) => setPrimary(e.target.checked)} />
          <span>Contacto principal</span>
        </label>
        {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
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

export default function ClientDetail() {
  const id = Number(useParams().id)
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [contact, setContact] = useState<Contact | 'new' | null>(null)
  const key = ['clients', id]
  const { data: c, error, isLoading, refetch } = useQuery({ queryKey: key, queryFn: () => api<Client>(`/api/clients/${id}`) })
  const opps = useQuery({
    queryKey: ['opportunities', 'client', id],
    queryFn: () => api<Page<OpportunitySummary>>('/api/opportunities', { query: { client_id: id, per_page: 20 } }),
    enabled: can('opportunities', 'read'),
  })
  const removeContact = useMutation({
    mutationFn: (contactId: number) => api(`/api/clients/${id}/contacts/${contactId}`, { method: 'DELETE' }),
    onSuccess: () => void refetch(),
    onError: (err) => toast(errorMessage(err), 'danger'),
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!c) return null
  const writable = can('clients', 'write')

  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/clients">Clientes</Link> / {c.name}
      </nav>
      <header className="page-head">
        <div>
          <h1>{c.name}</h1>
          <div className="meta-row">
            {c.segment && <Badge tone="accent">{SEGMENTS[c.segment]}</Badge>}
            {c.risk_level && <Badge tone={c.risk_level === 'high' ? 'danger' : 'neutral'}>Riesgo {RISK[c.risk_level]?.toLowerCase()}</Badge>}
            <span className="muted">{SECTORS[c.sector ?? ''] ?? c.sector}</span>
            {c.website && /^https?:\/\//.test(c.website) && (
              <a href={c.website} target="_blank" rel="noreferrer noopener">
                {c.website.replace(/^https?:\/\//, '')} ↗
              </a>
            )}
          </div>
        </div>
        {writable && (
          <button className="btn" onClick={() => setEditing(true)}>
            Editar
          </button>
        )}
      </header>
      <div className="detail-grid">
        <div className="stack">
          <section className="card">
            <h2>Oportunidades ({c.open_opportunities} abiertas)</h2>
            {opps.data && !opps.data.items.length && <p className="muted">Sin oportunidades.</p>}
            <ul className="plain-list">
              {opps.data?.items.map((o) => (
                <li key={o.id} className="row-between">
                  <span>
                    <Link to={`/opportunities/${o.id}`}>{o.title}</Link>
                    <div className="row-sub">
                      {fmtMoney(o.estimated_value_eur)} · cierre {fmtDate(o.deadline)}
                    </div>
                  </span>
                  <OpportunityStatus status={o.status} />
                </li>
              ))}
            </ul>
          </section>
          <section className="card">
            <h2>Proyectos</h2>
            {!c.projects.length && <p className="muted">Sin proyectos registrados.</p>}
            <ul className="plain-list">
              {c.projects.map((p) => (
                <li key={p.id}>
                  <strong>{p.name}</strong> <Badge>{PROJECT_STATUS[p.status] ?? p.status}</Badge>
                  <div className="row-sub">
                    {fmtDate(p.start_date)} – {fmtDate(p.end_date)} · {fmtMoney(p.budget_eur)}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </div>
        <aside className="stack">
          <section className="card">
            <header className="card-head">
              <h2>Contactos</h2>
              {writable && (
                <button className="btn btn-small" onClick={() => setContact('new')}>
                  Añadir
                </button>
              )}
            </header>
            {!c.contacts.length && <p className="muted">Sin contactos.</p>}
            <ul className="plain-list">
              {c.contacts.map((x) => (
                <li key={x.id}>
                  <div className="row-between">
                    <strong>
                      {x.full_name} {x.is_primary && <Badge tone="accent">principal</Badge>}
                    </strong>
                    {writable && (
                      <span className="btn-row">
                        <button className="btn btn-small btn-ghost" onClick={() => setContact(x)}>
                          Editar
                        </button>
                        <button className="btn btn-small btn-ghost" onClick={() => window.confirm('¿Borrar el contacto?') && removeContact.mutate(x.id)}>
                          Borrar
                        </button>
                      </span>
                    )}
                  </div>
                  <div className="row-sub">{[x.position, x.email, x.phone].filter(Boolean).join(' · ')}</div>
                </li>
              ))}
            </ul>
          </section>
          {c.notes && (
            <section className="card">
              <h2>Notas</h2>
              <p className="pre-line">{c.notes}</p>
            </section>
          )}
          <section className="card">
            <dl className="facts">
              <dt>CIF / NIF</dt>
              <dd>{c.tax_id ?? '—'}</dd>
              <dt>Alta</dt>
              <dd>{fmtDate(c.created_at)}</dd>
            </dl>
          </section>
        </aside>
      </div>
      {editing && (
        <ClientForm
          client={c}
          onClose={() => setEditing(false)}
          onSaved={(updated) => {
            queryClient.setQueryData(key, updated)
            setEditing(false)
            toast('Cambios guardados')
          }}
        />
      )}
      {contact && (
        <ContactForm
          clientId={id}
          contact={contact === 'new' ? undefined : contact}
          onClose={() => setContact(null)}
          onSaved={() => {
            setContact(null)
            void refetch()
          }}
        />
      )}
    </div>
  )
}
