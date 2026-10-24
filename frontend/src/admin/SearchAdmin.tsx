// Búsqueda: patrones del clasificador de intención, banco de pruebas, calidad del
// buscador y estado de los índices de Meilisearch.
import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtRelative } from '../lib/format'
import { BarList, ChartCard } from '../components/charts'
import { Badge, Empty, ErrorBox, Field, Modal, Spinner, Stat, errorMessage, useToast } from '../components/ui'
import { DaysPicker, Tabs, useTab } from './common'
import { INTENTS } from './labels'
import type { IntentPattern, IntentTest, SearchIndex, SearchQuality } from './types'

const TABS = ['quality', 'patterns', 'test', 'indexes'] as const
const TAB_LABELS = { quality: 'Calidad', patterns: 'Patrones de intención', test: 'Probar una frase', indexes: 'Índices' }
const INDEX_NAMES: Record<string, string> = { opportunities: 'Oportunidades', documents: 'Documentos', clients: 'Clientes' }
const LAYERS: Record<string, string> = { pattern: 'Patrones', llm: 'Modelo', fallback: 'Por defecto', cache: 'Caché' }
const intent = (i: string) => INTENTS[i] ?? i
const pctText = (v: number | null) => (v === null ? '—' : `${v.toLocaleString('es-ES')} %`)

export default function SearchAdmin() {
  const [tab, setTab] = useTab(TABS)
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Búsqueda</h1>
          <p className="muted">Cómo entiende el buscador lo que se le pide y si encuentra lo que se busca.</p>
        </div>
      </header>
      <Tabs tabs={TABS.map((t) => ({ key: t, label: TAB_LABELS[t] }))} value={tab} onChange={setTab} />
      {tab === 'quality' && <Quality />}
      {tab === 'patterns' && <Patterns />}
      {tab === 'test' && <TestBox />}
      {tab === 'indexes' && <Indexes />}
    </div>
  )
}

// ---------------------------------------------------------------- Calidad
function Quality() {
  const [days, setDays] = useState(7)
  const { data, error, isLoading } = useQuery({
    queryKey: ['admin', 'search-quality', days],
    queryFn: () => api<SearchQuality>('/api/admin/search/quality', { query: { days } }),
  })
  return (
    <>
      <div className="toolbar">
        <DaysPicker days={days} onChange={setDays} />
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} />}
      {data && (
        <>
          {data.warnings.length > 0 && (
            <ul className="notice notice-error plain-list">
              {data.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <div className="stats">
            <Stat label="Sin resultados" value={pctText(data.zero_results_pct)} />
            <Stat label="Con clic en un resultado" value={pctText(data.click_through_rate_pct)} />
            <Stat label="Reformuladas" value={pctText(data.reformulation_rate_pct)} hint="Se vuelve a buscar enseguida" />
            <Stat label="Resueltas con patrones" value={pctText(data.layer1_share_pct)} hint="Sin llamar al modelo" />
            <Stat
              label="Tiempo de clasificación"
              value={data.classify_ms.p50 !== null ? `${data.classify_ms.p50} ms` : '—'}
              hint={data.classify_ms.p95 !== null ? `p95: ${data.classify_ms.p95} ms` : undefined}
            />
            <Stat label="Valoración" value={data.ratings.average?.toLocaleString('es-ES', { maximumFractionDigits: 1 }) ?? '—'} hint={`${data.ratings.count} valoraciones`} />
          </div>
          <div className="home-grid section-gap">
            <ChartCard
              title="Qué se pide"
              subtitle="Peticiones al asistente por intención"
              table={
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th>Intención</th>
                      <th className="num">Peticiones</th>
                      <th className="num">Confianza media</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.intents.map((i) => (
                      <tr key={i.intent}>
                        <td>{intent(i.intent)}</td>
                        <td className="num">{i.count}</td>
                        <td className="num">{i.avg_confidence?.toLocaleString('es-ES', { maximumFractionDigits: 2 }) ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              }
            >
              {data.intents.length ? (
                <BarList
                  items={data.intents.map((i) => ({ key: i.intent, label: intent(i.intent), value: i.count }))}
                  detail={(k) => {
                    const row = data.intents.find((i) => i.intent === k)
                    return row?.avg_confidence != null ? [{ label: 'confianza media', value: row.avg_confidence.toFixed(2) }] : []
                  }}
                />
              ) : (
                <p className="muted">Sin peticiones en el periodo.</p>
              )}
            </ChartCard>
            <section className="card">
              <h2>Búsquedas sin resultados</h2>
              {data.top_zero_result_queries.length ? (
                <ul className="plain-list">
                  {data.top_zero_result_queries.map((q) => (
                    <li key={q.query} className="row-between">
                      <span>«{q.query}»</span>
                      <span className="muted">{q.count}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">Ninguna. Todas las búsquedas han encontrado algo.</p>
              )}
            </section>
            {data.misclassified.length > 0 && (
              <section className="card">
                <h2>Mal clasificadas (según las personas)</h2>
                <ul className="plain-list">
                  {data.misclassified.map((m) => (
                    <li key={`${m.classified}-${m.expected}`}>
                      {intent(m.classified)} en vez de <strong>{intent(m.expected)}</strong> <span className="muted">· {m.count}</span>
                    </li>
                  ))}
                </ul>
                <p className="field-hint">Añade un patrón para la intención correcta en «Patrones de intención».</p>
              </section>
            )}
          </div>
        </>
      )}
    </>
  )
}

// ---------------------------------------------------------------- Patrones
function PatternForm({ pattern, onClose }: { pattern?: IntentPattern; onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    intent: pattern?.intent ?? 'CHAT_RAG',
    subtype: pattern?.subtype ?? '',
    pattern: pattern?.pattern ?? '',
    priority: String(pattern?.priority ?? 100),
    description: pattern?.description ?? '',
  })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, priority: Number(form.priority), description: form.description || null }
      return pattern
        ? api(`/api/admin/search/intent-patterns/${pattern.id}`, { method: 'PATCH', body })
        : api('/api/admin/search/intent-patterns', { body })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'intent-patterns'] })
      onClose()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title={pattern ? 'Editar patrón' : 'Nuevo patrón'} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Intención">
            <select value={form.intent} onChange={set('intent')}>
              {Object.entries(INTENTS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Subtipo" hint="Opcional, en minúsculas.">
            <input value={form.subtype} onChange={set('subtype')} pattern="[a-z_]{0,50}" />
          </Field>
        </div>
        <Field label="Expresión regular" hint="Se compara con la frase en minúsculas y sin tildes.">
          <input className="mono" value={form.pattern} onChange={set('pattern')} required minLength={2} maxLength={300} />
        </Field>
        <div className="grid-2">
          <Field label="Prioridad" hint="Menor número, antes se comprueba.">
            <input type="number" min={0} max={1000} value={form.priority} onChange={set('priority')} />
          </Field>
          <Field label="Descripción">
            <input value={form.description} onChange={set('description')} maxLength={255} />
          </Field>
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

function Patterns() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [showInactive, setShowInactive] = useState(false)
  const [editing, setEditing] = useState<IntentPattern | 'new' | null>(null)
  const { data, error, isLoading } = useQuery({
    queryKey: ['admin', 'intent-patterns', showInactive],
    queryFn: () => api<{ items: IntentPattern[] }>('/api/admin/search/intent-patterns', { query: { include_inactive: showInactive ? 'true' : null } }),
  })
  const toggle = useMutation({
    mutationFn: (p: IntentPattern) => api(`/api/admin/search/intent-patterns/${p.id}`, { method: 'PATCH', body: { is_active: !p.is_active } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'intent-patterns'] }),
    onError: (e) => toast(errorMessage(e), 'danger'),
  })
  const canWrite = can('search', 'write')
  return (
    <>
      <div className="toolbar">
        <p className="muted grow">
          Primera capa del clasificador: si una frase encaja con un patrón, se resuelve al momento y sin coste. Si no, decide
          el modelo.
        </p>
        <label className="check">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          Ver desactivados
        </label>
        {canWrite && (
          <button className="btn btn-primary" onClick={() => setEditing('new')}>
            Nuevo patrón
          </button>
        )}
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} />}
      {data && !data.items.length && <Empty title="No hay patrones" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table table-compact">
            <thead>
              <tr>
                <th className="num">Prioridad</th>
                <th>Intención</th>
                <th>Patrón</th>
                <th>Actualizado</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((p) => (
                <tr key={p.id} className={p.is_active ? '' : 'row-muted'}>
                  <td className="num">{p.priority}</td>
                  <td>
                    {intent(p.intent)}
                    {p.subtype && <div className="row-sub">{p.subtype}</div>}
                  </td>
                  <td className="cell-wrap">
                    <code>{p.pattern}</code>
                    {p.description && <div className="row-sub">{p.description}</div>}
                  </td>
                  <td className="nowrap">{fmtRelative(p.updated_at)}</td>
                  <td className="num nowrap">
                    {canWrite && (
                      <span className="btn-row">
                        <button className="btn btn-small btn-ghost" onClick={() => setEditing(p)}>
                          Editar
                        </button>
                        <button className="btn btn-small btn-ghost" disabled={toggle.isPending} onClick={() => toggle.mutate(p)}>
                          {p.is_active ? 'Desactivar' : 'Activar'}
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <PatternForm pattern={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  )
}

// ---------------------------------------------------------------- Probar
function TestBox() {
  const [query, setQuery] = useState('')
  const [useLlm, setUseLlm] = useState(false)
  const run = useMutation({ mutationFn: () => api<IntentTest>('/api/admin/search/intent/test', { body: { query, use_llm: useLlm } }) })
  function submit(e: FormEvent) {
    e.preventDefault()
    run.mutate()
  }
  const r = run.data
  return (
    <div className="detail-grid">
      <form className="card stack" onSubmit={submit}>
        <Field label="Frase" hint="No se registra en las métricas.">
          <input value={query} onChange={(e) => setQuery(e.target.value)} required maxLength={500} placeholder="¿Qué licitaciones de ciberseguridad vencen este mes?" />
        </Field>
        <label className="check">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          Si ningún patrón encaja, preguntar también al modelo (consume tokens)
        </label>
        {run.error && <p className="notice notice-error">{errorMessage(run.error)}</p>}
        <div className="actions">
          <button className="btn btn-primary" disabled={run.isPending}>
            Clasificar
          </button>
        </div>
      </form>
      <section className="card stack">
        <h2>Resultado</h2>
        {run.isPending && <Spinner />}
        {!r && !run.isPending && <p className="muted">Escribe una frase para ver qué patrones encajan y qué decidiría el clasificador.</p>}
        {r && (
          <>
            <dl className="facts facts-compact">
              <span className="facts-pair">
                <dt>Intención</dt>
                <dd>
                  <strong>{intent(r.result.type)}</strong>
                  {r.result.subtype && ` · ${r.result.subtype}`}
                </dd>
              </span>
              <span className="facts-pair">
                <dt>Decide</dt>
                <dd>{LAYERS[r.result.layer] ?? r.result.layer}</dd>
              </span>
              <span className="facts-pair">
                <dt>Confianza</dt>
                <dd>{r.result.confidence.toFixed(2)}</dd>
              </span>
              <span className="facts-pair">
                <dt>Tiempo</dt>
                <dd>{r.result.latency_ms} ms</dd>
              </span>
            </dl>
            <p className="field-hint">
              Frase normalizada: <code>{r.normalized}</code>
            </p>
            {r.result.reasoning && <p className="muted">{r.result.reasoning}</p>}
            <h3>Patrones que encajan</h3>
            {r.layer1.matched.length ? (
              <ul className="plain-list">
                {r.layer1.matched.map((p) => (
                  <li key={p.id}>
                    <Badge>{p.priority}</Badge> {intent(p.intent)} · <code>{p.pattern}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Ninguno.</p>
            )}
            {r.llm_filters && (
              <>
                <h3>Filtros que ha extraído el modelo</h3>
                <pre className="code-block">{JSON.stringify(r.llm_filters, null, 2)}</pre>
              </>
            )}
          </>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------- Índices
function Indexes() {
  const { can } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const { data, error, isLoading } = useQuery({
    queryKey: ['admin', 'search-indexes'],
    queryFn: () => api<{ items: SearchIndex[] }>('/api/admin/search/indexes'),
    refetchInterval: (q) => (q.state.data?.items.some((i) => i.is_indexing || i.pending > 0) ? 5000 : false),
  })
  const reindex = useMutation({
    mutationFn: (index: string | null) => api<{ queued: string[] }>('/api/admin/search/reindex', { body: index ? { index } : {} }),
    onSuccess: (r) => {
      toast(`Reconstruyendo: ${r.queued.map((n) => INDEX_NAMES[n] ?? n).join(', ')}.`)
      void qc.invalidateQueries({ queryKey: ['admin', 'search-indexes'] })
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })
  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} />
  const canWrite = can('search', 'write')
  return (
    <>
      <div className="toolbar">
        <p className="muted grow">MySQL es la fuente de verdad; el índice se sincroniza solo. Reconstruir no corta las búsquedas.</p>
        {canWrite && (
          <button className="btn" disabled={reindex.isPending} onClick={() => reindex.mutate(null)}>
            Reconstruir todos
          </button>
        )}
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Índice</th>
              <th className="num">En el índice</th>
              <th className="num">En MySQL</th>
              <th>Estado</th>
              <th>Última reconstrucción</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.items.map((i) => (
              <tr key={i.index}>
                <td>
                  {INDEX_NAMES[i.index] ?? i.index}
                  <div className="row-sub">
                    <code>{i.uid}</code>
                  </div>
                </td>
                <td className="num">{i.documents ?? '—'}</td>
                <td className="num">{i.mysql_count}</td>
                <td>
                  {i.is_indexing ? (
                    <Badge tone="info">Indexando</Badge>
                  ) : i.in_sync ? (
                    <Badge tone="success">Al día</Badge>
                  ) : (
                    <Badge tone="warning">Descuadrado</Badge>
                  )}
                  {i.pending > 0 && <div className="row-sub">{i.pending} cambios pendientes</div>}
                </td>
                <td className="nowrap">{i.last_rebuild ? fmtRelative(i.last_rebuild) : '—'}</td>
                <td className="num">
                  {canWrite && (
                    <button className="btn btn-small btn-ghost" disabled={reindex.isPending} onClick={() => reindex.mutate(i.index)}>
                      Reconstruir
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
