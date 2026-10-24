// Competidores (fase 9a): ficha con DAFO, líneas y sectores en los que compiten y
// posición de precio. Se pueden cargar a mano o desde Excel (página de objetivos).
import { useState, type FormEvent } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { SECTORS, fmtRelative } from '../lib/format'
import type { Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Field, Modal, Pager, Spinner, errorMessage, useDebounced, useToast } from '../components/ui'
import { useServiceLines } from './common'
import type { Competitor } from './types'

export const COMPETITOR_TYPES: Record<Competitor['competitor_type'], string> = {
  direct: 'Directo',
  indirect: 'Indirecto',
  substitute: 'Sustitutivo',
}
const PRICE: Record<string, string> = { '-1': 'Más barato', '0': 'Similar', '1': 'Más caro' }
const SWOT: { key: 'strengths' | 'weaknesses' | 'opportunities' | 'threats'; label: string }[] = [
  { key: 'strengths', label: 'Fortalezas' },
  { key: 'weaknesses', label: 'Debilidades' },
  { key: 'opportunities', label: 'Oportunidades' },
  { key: 'threats', label: 'Amenazas' },
]

export default function Competitors() {
  const { can } = useAuth()
  const { lines, names } = useServiceLines()
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const q = useDebounced(text.trim(), 300)
  const type = params.get('type') ?? ''
  const line = params.get('service_line') ?? ''
  const page = Number(params.get('page') ?? 1)
  const [open, setOpen] = useState<Competitor | 'new' | null>(null)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['analytics', 'competitors', q, type, line, page],
    queryFn: () => api<Page<Competitor>>('/api/analytics/competitors', { query: { q, type, service_line: line, page } }),
    placeholderData: keepPreviousData,
  })

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    setParams(next, { replace: true })
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Competidores</h1>
          <p className="muted">
            Con quién competimos, en qué líneas y sectores, y su DAFO. También se cargan desde Excel en{' '}
            <Link to="/targets">Objetivos e importación</Link>.
          </p>
        </div>
        {can('competitors', 'write') && (
          <button className="btn btn-primary" onClick={() => setOpen('new')}>
            Nuevo competidor
          </button>
        )}
      </header>
      <div className="toolbar">
        <input
          type="search"
          className="grow"
          placeholder="Buscar por nombre o descripción"
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setFilter('q', e.target.value.trim())
          }}
        />
        <select value={type} onChange={(e) => setFilter('type', e.target.value)} aria-label="Tipo">
          <option value="">Todos los tipos</option>
          {Object.entries(COMPETITOR_TYPES).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select value={line} onChange={(e) => setFilter('service_line', e.target.value)} aria-label="Línea de servicio">
          <option value="">Todas las líneas</option>
          {lines.map((l) => (
            <option key={l.code} value={l.code}>
              {l.name}
            </option>
          ))}
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay competidores" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Competidor</th>
                <th>Tipo</th>
                <th>Líneas</th>
                <th>Precio</th>
                <th>DAFO</th>
                <th>Actualizado</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <button className="btn-link row-title" onClick={() => setOpen(c)}>
                      {c.name}
                    </button>
                  </td>
                  <td>
                    <Badge tone={c.competitor_type === 'direct' ? 'danger' : 'neutral'}>{COMPETITOR_TYPES[c.competitor_type]}</Badge>
                  </td>
                  <td>{c.service_lines.map((l) => names[l] ?? l).join(', ') || '—'}</td>
                  <td>{PRICE[String(c.price_positioning)]}</td>
                  <td className="muted small">
                    {SWOT.map((s) => `${c[s.key].length} ${s.label.toLowerCase()}`).join(' · ')}
                  </td>
                  <td>{fmtRelative(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && (
        <Pager
          pagination={data.pagination}
          onPage={(p) => {
            const next = new URLSearchParams(params)
            next.set('page', String(p))
            setParams(next)
          }}
        />
      )}
      {open && <CompetitorModal competitor={open === 'new' ? undefined : open} onClose={() => setOpen(null)} />}
    </div>
  )
}

/** Ficha de un competidor: lectura y, con permiso, edición en el mismo diálogo. */
function CompetitorModal({ competitor, onClose }: { competitor?: Competitor; onClose: () => void }) {
  const { can } = useAuth()
  const [editing, setEditing] = useState(!competitor)
  const { names } = useServiceLines()
  const queryClient = useQueryClient()
  const toast = useToast()
  const remove = useMutation({
    mutationFn: () => api(`/api/analytics/competitors/${competitor!.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast('Competidor borrado.', 'success')
      void queryClient.invalidateQueries({ queryKey: ['analytics', 'competitors'] })
      onClose()
    },
  })
  if (editing) return <CompetitorForm competitor={competitor} onClose={competitor ? () => setEditing(false) : onClose} onSaved={onClose} />
  const c = competitor!
  return (
    <Modal title={c.name} onClose={onClose} wide>
      <div className="stack">
        <div className="tags">
          <Badge tone={c.competitor_type === 'direct' ? 'danger' : 'neutral'}>{COMPETITOR_TYPES[c.competitor_type]}</Badge>
          <Badge>Precio: {PRICE[String(c.price_positioning)].toLowerCase()}</Badge>
          {c.website && (
            <a href={c.website} target="_blank" rel="noopener noreferrer">
              {c.website}
            </a>
          )}
        </div>
        {c.description && <p>{c.description}</p>}
        <dl className="facts">
          <dt>Líneas</dt>
          <dd>{c.service_lines.map((l) => names[l] ?? l).join(', ') || '—'}</dd>
          <dt>Sectores</dt>
          <dd>{c.sectors.map((s) => SECTORS[s] ?? s).join(', ') || '—'}</dd>
        </dl>
        <div className="swot">
          {SWOT.map((s) => (
            <section key={s.key}>
              <h4>{s.label}</h4>
              {c[s.key].length ? (
                <ul>
                  {c[s.key].map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted small">Sin datos</p>
              )}
            </section>
          ))}
        </div>
        {remove.error && <p className="notice notice-error">{errorMessage(remove.error)}</p>}
        <div className="actions">
          {can('competitors', 'delete') && (
            <button
              className="btn btn-danger-ghost"
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`¿Borrar a ${c.name}?`)) remove.mutate()
              }}
            >
              Borrar
            </button>
          )}
          <div className="grow" />
          {can('competitors', 'write') && (
            <button className="btn btn-primary" onClick={() => setEditing(true)}>
              Editar
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}

const toLines = (items: string[]) => items.join('\n')
const fromLines = (text: string) =>
  text
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)

function CompetitorForm({ competitor, onClose, onSaved }: { competitor?: Competitor; onClose: () => void; onSaved: () => void }) {
  const { lines } = useServiceLines()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({
    name: competitor?.name ?? '',
    competitor_type: competitor?.competitor_type ?? 'direct',
    website: competitor?.website ?? '',
    description: competitor?.description ?? '',
    price_positioning: competitor?.price_positioning ?? 0,
    strengths: toLines(competitor?.strengths ?? []),
    weaknesses: toLines(competitor?.weaknesses ?? []),
    opportunities: toLines(competitor?.opportunities ?? []),
    threats: toLines(competitor?.threats ?? []),
  })
  const [serviceLines, setServiceLines] = useState<string[]>(competitor?.service_lines ?? [])
  const [sectors, setSectors] = useState<string[]>(competitor?.sectors ?? [])
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })
  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((x) => x !== value) : [...list, value])

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        competitor_type: form.competitor_type,
        website: form.website.trim() || null,
        description: form.description.trim() || null,
        price_positioning: Number(form.price_positioning),
        strengths: fromLines(form.strengths),
        weaknesses: fromLines(form.weaknesses),
        opportunities: fromLines(form.opportunities),
        threats: fromLines(form.threats),
        service_lines: serviceLines,
        sectors,
      }
      return competitor
        ? api<Competitor>(`/api/analytics/competitors/${competitor.id}`, { method: 'PATCH', body: { ...body, version: competitor.version } })
        : api<Competitor>('/api/analytics/competitors', { body })
    },
    onSuccess: () => {
      toast('Competidor guardado.', 'success')
      void queryClient.invalidateQueries({ queryKey: ['analytics', 'competitors'] })
      onSaved()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title={competitor ? `Editar ${competitor.name}` : 'Nuevo competidor'} onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Nombre">
            <input value={form.name} onChange={set('name')} required maxLength={200} autoFocus />
          </Field>
          <Field label="Web">
            <input value={form.website} onChange={set('website')} maxLength={255} placeholder="https://" />
          </Field>
          <Field label="Tipo">
            <select value={form.competitor_type} onChange={set('competitor_type')}>
              {Object.entries(COMPETITOR_TYPES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Precio frente al nuestro">
            <select value={form.price_positioning} onChange={set('price_positioning')}>
              {Object.entries(PRICE).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Descripción">
          <textarea rows={2} value={form.description} onChange={set('description')} maxLength={2000} />
        </Field>
        <fieldset className="field">
          <legend className="field-label">Líneas en las que compite</legend>
          <div className="tags">
            {lines.map((l) => (
              <button
                key={l.code}
                type="button"
                className={`chip${serviceLines.includes(l.code) ? ' chip-on' : ''}`}
                aria-pressed={serviceLines.includes(l.code)}
                onClick={() => setServiceLines(toggle(serviceLines, l.code))}
              >
                {l.name}
              </button>
            ))}
          </div>
        </fieldset>
        <fieldset className="field">
          <legend className="field-label">Sectores</legend>
          <div className="tags">
            {Object.entries(SECTORS).map(([k, v]) => (
              <button
                key={k}
                type="button"
                className={`chip${sectors.includes(k) ? ' chip-on' : ''}`}
                aria-pressed={sectors.includes(k)}
                onClick={() => setSectors(toggle(sectors, k))}
              >
                {v}
              </button>
            ))}
          </div>
        </fieldset>
        <div className="grid-2">
          {SWOT.map((s) => (
            <Field key={s.key} label={s.label} hint="Una por línea (máximo 20)">
              <textarea rows={3} value={form[s.key]} onChange={set(s.key)} />
            </Field>
          ))}
        </div>
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
