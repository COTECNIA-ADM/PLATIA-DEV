// Oportunidades: buscador con filtros y facetas (Capítulo 13) sobre el embudo F1–F5.
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { OPPORTUNITY_STATUS, PHASES, daysUntil, fmtDate, fmtMoney, label } from '../lib/format'
import type { ClientSummary, OpportunitySearch, Opportunity, Page } from '../lib/types'
import { OpportunityStatus } from '../components/status'
import { Highlight } from '../components/text'
import { Empty, ErrorBox, Field, Modal, Pager, ScoreBar, Spinner, errorMessage, useDebounced, useToast } from '../components/ui'

const SORTS: Record<string, string> = {
  relevance: 'Más relevantes',
  deadline: 'Cierran antes',
  '-relevance_score': 'Mejor puntuación',
  '-value': 'Mayor importe',
  '-created': 'Más recientes',
}

type ServiceLine = { code: string; name: string }

export function useServiceLines() {
  return useQuery({
    queryKey: ['service-lines'],
    queryFn: () => api<Page<ServiceLine>>('/api/portfolio/service-lines', { query: { per_page: 100 } }),
    staleTime: 5 * 60_000,
  })
}

export function NewOpportunity({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const toast = useToast()
  const queryClient = useQueryClient()
  const lines = useServiceLines()
  const clients = useQuery({
    queryKey: ['clients', 'all'],
    queryFn: () => api<Page<ClientSummary>>('/api/clients', { query: { per_page: 100 } }),
  })
  const [form, setForm] = useState({
    title: '',
    description: '',
    client_id: '',
    service_line: '',
    estimated_value_eur: '',
    deadline: '',
    contracting_entity: '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })

  const create = useMutation({
    mutationFn: () =>
      api<Opportunity>('/api/opportunities', {
        body: {
          title: form.title,
          description: form.description || null,
          client_id: form.client_id ? Number(form.client_id) : null,
          service_line: form.service_line || null,
          estimated_value_eur: form.estimated_value_eur || null,
          deadline: form.deadline ? new Date(`${form.deadline}T23:59:00`).toISOString() : null,
          contracting_entity: form.contracting_entity || null,
        },
      }),
    onSuccess: (opp) => {
      void queryClient.invalidateQueries({ queryKey: ['opportunities'] })
      toast(`Oportunidad creada. Puntuación de relevancia: ${opp.relevance_score ?? '—'}`)
      navigate(`/opportunities/${opp.id}`)
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    create.mutate()
  }

  return (
    <Modal title="Nueva oportunidad" onClose={onClose}>
      <form onSubmit={submit} className="stack">
        <Field label="Título">
          <input value={form.title} onChange={set('title')} required maxLength={500} autoFocus />
        </Field>
        <Field label="Descripción" hint="Cuanto más detalle, mejor será la puntuación automática.">
          <textarea rows={4} value={form.description} onChange={set('description')} />
        </Field>
        <div className="grid-2">
          <Field label="Cliente">
            <select value={form.client_id} onChange={set('client_id')}>
              <option value="">Sin cliente</option>
              {clients.data?.items.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Línea de servicio" hint="Si la dejas vacía, se deduce del texto.">
            <select value={form.service_line} onChange={set('service_line')}>
              <option value="">Automática</option>
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
          <Field label="Fecha límite">
            <input type="date" value={form.deadline} onChange={set('deadline')} />
          </Field>
        </div>
        <Field label="Entidad contratante">
          <input value={form.contracting_entity} onChange={set('contracting_entity')} maxLength={255} />
        </Field>
        {create.error && <p className="notice notice-error">{errorMessage(create.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? 'Creando…' : 'Crear'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function FacetList({
  title,
  values,
  labels,
  selected,
  onToggle,
}: {
  title: string
  values: Record<string, number> | undefined
  labels?: Record<string, string>
  selected: string[]
  onToggle: (value: string) => void
}) {
  const entries = Object.entries(values ?? {}).sort((a, b) => b[1] - a[1])
  if (!entries.length) return null
  return (
    <fieldset className="facet">
      <legend>{title}</legend>
      {entries.map(([value, count]) => (
        <label key={value} className="check">
          <input type="checkbox" checked={selected.includes(value)} onChange={() => onToggle(value)} />
          <span>{labels?.[value] ?? value}</span>
          <span className="muted">{count}</span>
        </label>
      ))}
    </fieldset>
  )
}

export default function Opportunities() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const [creating, setCreating] = useState(false)
  const [text, setText] = useState(params.get('q') ?? '')
  const q = useDebounced(text.trim(), 300)
  const lines = useServiceLines()

  const list = (key: string) => (params.get(key) ? params.get(key)!.split(',') : [])
  const filters = {
    q,
    phase: list('phase'),
    status: list('status'),
    service_line: list('service_line'),
    only_open: params.get('open') !== 'false',
    owner: params.get('mine') === 'true' ? 'me' : undefined,
    deadline_within_days: params.get('closing') ? Number(params.get('closing')) : undefined,
    sort: params.get('sort') ?? 'relevance',
    page: Number(params.get('page') ?? 1),
    per_page: 20,
    semantic: params.get('semantic') === 'true' && q.length > 0,
  }

  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['opportunities', 'search', filters],
    queryFn: () =>
      api<OpportunitySearch>('/api/search/opportunities', {
        body: {
          ...filters,
          phase: filters.phase.length ? filters.phase : undefined,
          status: filters.status.length ? filters.status : undefined,
          service_line: filters.service_line.length ? filters.service_line : undefined,
        },
      }),
    placeholderData: keepPreviousData,
  })

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === '') next.delete(k)
      else next.set(k, v)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next, { replace: true })
  }

  function toggle(key: string, value: string) {
    const current = list(key)
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
    update({ [key]: next.join(',') })
  }

  function logClick(id: number, position: number) {
    if (data?.query_log_id) {
      void api('/api/search/click', {
        body: { query_log_id: data.query_log_id, kind: 'opportunity', object_id: id, position },
      }).catch(() => undefined)
    }
  }

  const lineNames = Object.fromEntries((lines.data?.items ?? []).map((l) => [l.code, l.name]))
  const offset = ((data?.pagination.page ?? 1) - 1) * (data?.pagination.per_page ?? 20)

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Oportunidades</h1>
          <p className="muted">
            {data ? `${data.pagination.total} resultados` : ' '}
            {data?.engine === 'mysql' && ' · búsqueda básica (el buscador rápido no responde)'}
          </p>
        </div>
        {can('opportunities', 'write') && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            Nueva oportunidad
          </button>
        )}
      </header>

      <div className="toolbar">
        <input
          type="search"
          className="grow"
          placeholder="Buscar por título, entidad, código o descripción"
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            update({ q: e.target.value.trim() || null })
          }}
        />
        <select value={filters.sort} onChange={(e) => update({ sort: e.target.value })} aria-label="Orden">
          {Object.entries(SORTS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      <div className="chips">
        {Object.entries(PHASES).map(([k, v]) => (
          <button key={k} className={`chip${filters.phase.includes(k) ? ' chip-on' : ''}`} onClick={() => toggle('phase', k)}>
            {v}
          </button>
        ))}
        <span className="chips-sep" />
        <button className={`chip${filters.owner ? ' chip-on' : ''}`} onClick={() => update({ mine: filters.owner ? null : 'true' })}>
          Mías
        </button>
        <button className={`chip${filters.only_open ? ' chip-on' : ''}`} onClick={() => update({ open: filters.only_open ? 'false' : null })}>
          Solo abiertas
        </button>
        <button
          className={`chip${filters.deadline_within_days ? ' chip-on' : ''}`}
          onClick={() => update({ closing: filters.deadline_within_days ? null : '30' })}
        >
          Cierran en 30 días
        </button>
        <button
          className={`chip${filters.semantic ? ' chip-on' : ''}`}
          onClick={() => update({ semantic: params.get('semantic') === 'true' ? null : 'true' })}
          title="Reordena la primera página por significado, no solo por palabras"
          disabled={!q}
        >
          Por significado
        </button>
      </div>

      <div className="with-sidebar">
        <aside className="filters">
          <FacetList
            title="Estado"
            values={data?.facets?.status}
            labels={OPPORTUNITY_STATUS}
            selected={filters.status}
            onToggle={(v) => toggle('status', v)}
          />
          <FacetList
            title="Línea de servicio"
            values={data?.facets?.service_line}
            labels={lineNames}
            selected={filters.service_line}
            onToggle={(v) => toggle('service_line', v)}
          />
        </aside>
        <section className={isFetching && !isLoading ? 'is-refreshing' : undefined}>
          {isLoading && <Spinner />}
          {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
          {data?.notes?.map((n) => (
            <p key={n} className="notice notice-warning">
              {n}
            </p>
          ))}
          {data && !data.items.length && (
            <Empty title="No hay oportunidades con estos filtros">Prueba a quitar alguno o a buscar con otras palabras.</Empty>
          )}
          {data && data.items.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Oportunidad</th>
                    <th>Estado</th>
                    <th className="num">Importe</th>
                    <th>Cierre</th>
                    <th>Relevancia</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((o, i) => {
                    const days = daysUntil(o.deadline)
                    return (
                      <tr key={o.id}>
                        <td>
                          <Link to={`/opportunities/${o.id}`} className="row-title" onClick={() => logClick(o.id, offset + i + 1)}>
                            <Highlight html={o.highlight?.title} fallback={o.title} />
                          </Link>
                          <div className="row-sub">
                            {[o.code, o.client_name ?? o.contracting_entity, label(lineNames, o.service_line)]
                              .filter((x) => x && x !== '—')
                              .join(' · ')}
                          </div>
                          {o.highlight?.snippet && (
                            <div className="row-snippet">
                              <Highlight html={o.highlight.snippet} />
                            </div>
                          )}
                        </td>
                        <td>
                          <OpportunityStatus status={o.status} />
                        </td>
                        <td className="num">{fmtMoney(o.estimated_value_eur)}</td>
                        <td className={days !== null && days >= 0 && days <= 7 ? 'text-warning' : undefined}>
                          {fmtDate(o.deadline)}
                          {days !== null && days >= 0 && days <= 30 && <div className="row-sub">en {days} días</div>}
                        </td>
                        <td>
                          <ScoreBar value={o.relevance_score} />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {data && <Pager pagination={data.pagination} onPage={(p) => update({ page: String(p) })} />}
        </section>
      </div>
      {creating && <NewOpportunity onClose={() => setCreating(false)} />}
    </div>
  )
}
