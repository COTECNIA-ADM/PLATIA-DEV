import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtRelative } from '../lib/format'
import type { Client, ClientSummary, Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Field, Modal, Pager, Spinner, errorMessage, useDebounced } from '../components/ui'

export const SEGMENTS: Record<string, string> = { A: 'A · estratégico', B: 'B · recurrente', C: 'C · ocasional' }
export const RISK: Record<string, string> = { low: 'Bajo', medium: 'Medio', high: 'Alto' }
export const SECTORS: Record<string, string> = {
  public: 'Sector público',
  health: 'Sanidad',
  finance: 'Banca y seguros',
  energy: 'Energía',
  industry: 'Industria',
  retail: 'Comercio',
  telecom: 'Telecomunicaciones',
  education: 'Educación',
  other: 'Otro',
}

export function ClientForm({ client, onClose, onSaved }: { client?: Client; onClose: () => void; onSaved: (c: Client) => void }) {
  const [form, setForm] = useState({
    name: client?.name ?? '',
    tax_id: client?.tax_id ?? '',
    sector: client?.sector ?? '',
    segment: client?.segment ?? '',
    risk_level: client?.risk_level ?? '',
    website: client?.website ?? '',
    notes: client?.notes ?? '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })
  const save = useMutation({
    mutationFn: () => {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v || null]))
      return client
        ? api<Client>(`/api/clients/${client.id}`, { method: 'PATCH', body: { ...body, version: client.version } })
        : api<Client>('/api/clients', { body })
    },
    onSuccess: onSaved,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title={client ? 'Editar cliente' : 'Nuevo cliente'} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <Field label="Nombre">
          <input value={form.name} onChange={set('name')} required maxLength={255} autoFocus />
        </Field>
        <div className="grid-2">
          <Field label="CIF / NIF">
            <input value={form.tax_id} onChange={set('tax_id')} maxLength={32} />
          </Field>
          <Field label="Sector">
            <select value={form.sector} onChange={set('sector')}>
              <option value="">—</option>
              {Object.entries(SECTORS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Segmento">
            <select value={form.segment} onChange={set('segment')}>
              <option value="">—</option>
              {Object.entries(SEGMENTS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Riesgo">
            <select value={form.risk_level} onChange={set('risk_level')}>
              <option value="">—</option>
              {Object.entries(RISK).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Web">
          <input value={form.website} onChange={set('website')} maxLength={255} placeholder="https://" />
        </Field>
        <Field label="Notas">
          <textarea rows={3} value={form.notes} onChange={set('notes')} />
        </Field>
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

export default function Clients() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const [creating, setCreating] = useState(false)
  const q = useDebounced(text.trim(), 300)
  const page = Number(params.get('page') ?? 1)
  const segment = params.get('segment') ?? ''
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['clients', 'list', q, segment, page],
    queryFn: () => api<Page<ClientSummary>>('/api/clients', { query: { q, segment, page } }),
    placeholderData: keepPreviousData,
  })

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Clientes</h1>
        </div>
        {can('clients', 'write') && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            Nuevo cliente
          </button>
        )}
      </header>
      <div className="toolbar">
        <input type="search" className="grow" placeholder="Buscar por nombre o CIF" value={text} onChange={(e) => setText(e.target.value)} />
        <select value={segment} onChange={(e) => setParams(e.target.value ? { segment: e.target.value } : {})} aria-label="Segmento">
          <option value="">Todos los segmentos</option>
          {Object.entries(SEGMENTS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay clientes" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Cliente</th>
                <th>Sector</th>
                <th>Segmento</th>
                <th>Riesgo</th>
                <th>Actualizado</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link to={`/clients/${c.id}`} className="row-title">
                      {c.name}
                    </Link>
                  </td>
                  <td>{SECTORS[c.sector ?? ''] ?? c.sector ?? '—'}</td>
                  <td>{c.segment ? <Badge tone={c.segment === 'A' ? 'accent' : 'neutral'}>{c.segment}</Badge> : '—'}</td>
                  <td>{c.risk_level ? <Badge tone={c.risk_level === 'high' ? 'danger' : c.risk_level === 'medium' ? 'warning' : 'success'}>{RISK[c.risk_level]}</Badge> : '—'}</td>
                  <td>{fmtRelative(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager pagination={data.pagination} onPage={(p) => setParams({ ...(segment ? { segment } : {}), page: String(p) })} />}
      {creating && <ClientForm onClose={() => setCreating(false)} onSaved={(c) => navigate(`/clients/${c.id}`)} />}
    </div>
  )
}
