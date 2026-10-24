// Modelos y costes de IA: modelo por tipo de tarea, precios, presupuestos, uso, calidad,
// cumplimiento y colecciones del RAG. Cada pestaña va en la URL (?tab=).
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDate } from '../lib/format'
import { Meter } from '../components/charts'
import { Badge, Empty, ErrorBox, Field, Modal, Spinner, Stat, errorMessage, useToast } from '../components/ui'
import { SERVICE_TYPES } from '../analytics/AIValue'
import { DaysPicker, Tabs, pct, useTab } from './common'
import { BUDGET_SCOPE, COMPLIANCE_EVENTS, perPerson, usd } from './labels'
import type { AIHealth, Baseline, Budget, Compliance, Pricing, QualityRow, RagCollections, ServiceConfig, UsageRow } from './types'

const TABS = ['models', 'budgets', 'usage', 'pricing', 'quality', 'compliance', 'rag'] as const
type Tab = (typeof TABS)[number]
const TAB_LABELS: Record<Tab, string> = {
  models: 'Modelos',
  budgets: 'Presupuestos',
  usage: 'Uso y ahorro',
  pricing: 'Precios',
  quality: 'Calidad',
  compliance: 'Cumplimiento',
  rag: 'Documentos (RAG)',
}
const AI_STATUS: Record<string, string> = { healthy: 'funciona', degraded: 'funciona con avisos', unhealthy: 'con fallos', unreachable: 'no responde' }
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max']
const service = (s: string) => SERVICE_TYPES[s] ?? s
const num = (n: number) => n.toLocaleString('es-ES')

export default function AIConfig() {
  const [tab, setTab] = useTab(TABS)
  const { can } = useAuth()
  const tabs = TABS.filter((t) => t !== 'compliance' || can('audit', 'read')).map((t) => ({ key: t, label: TAB_LABELS[t] }))
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Modelos y costes de IA</h1>
          <p className="muted">Qué modelo hace cada tarea, cuánto se gasta, con qué límites y con qué calidad.</p>
        </div>
      </header>
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === 'models' && <Models />}
      {tab === 'budgets' && <Budgets />}
      {tab === 'usage' && <Usage />}
      {tab === 'pricing' && <PricingTab />}
      {tab === 'quality' && <Quality />}
      {tab === 'compliance' && <ComplianceTab />}
      {tab === 'rag' && <Rag />}
    </div>
  )
}

// ---------------------------------------------------------------- Modelos
function ServiceForm({ config, onClose }: { config: ServiceConfig; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({
    model_name: config.model_name,
    fallback_model: config.fallback_model ?? '',
    max_tokens: String(config.max_tokens),
    effort: config.effort ?? '',
    is_active: config.is_active,
  })
  const save = useMutation({
    mutationFn: () =>
      api<ServiceConfig>(`/api/admin/ai/services/${config.service_type}`, {
        method: 'PATCH',
        body: {
          model_name: form.model_name,
          fallback_model: form.fallback_model || null,
          fallback_provider: form.fallback_model ? config.fallback_provider ?? config.provider : null,
          max_tokens: Number(form.max_tokens),
          effort: form.effort || null,
          is_active: form.is_active,
        },
      }),
    onSuccess: () => {
      toast('Guardado. Se aplica en la siguiente llamada.')
      void qc.invalidateQueries({ queryKey: ['admin', 'services'] })
      onClose()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title={service(config.service_type)} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <Field label="Modelo">
          <input value={form.model_name} onChange={(e) => setForm({ ...form, model_name: e.target.value })} required pattern="[A-Za-z0-9._:/\-]{1,100}" />
        </Field>
        <Field label="Modelo de reserva" hint="Si el principal falla o está saturado. Vacío para no usar ninguno.">
          <input value={form.fallback_model} onChange={(e) => setForm({ ...form, fallback_model: e.target.value })} pattern="[A-Za-z0-9._:/\-]{1,100}" />
        </Field>
        <div className="grid-2">
          <Field label="Máximo de tokens de salida">
            <input type="number" min={1} max={64000} value={form.max_tokens} onChange={(e) => setForm({ ...form, max_tokens: e.target.value })} required />
          </Field>
          <Field label="Esfuerzo">
            <select value={form.effort} onChange={(e) => setForm({ ...form, effort: e.target.value })}>
              <option value="">Por defecto</option>
              {EFFORTS.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <label className="check">
          <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Tarea activa (si no, las llamadas de este tipo se rechazan)
        </label>
        <p className="field-hint">Comprueba que el modelo tiene precio en la pestaña «Precios»; si no, su coste se registra como cero.</p>
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

function Models() {
  const { can } = useAuth()
  const [editing, setEditing] = useState<ServiceConfig | null>(null)
  const services = useQuery({ queryKey: ['admin', 'services'], queryFn: () => api<{ items: ServiceConfig[] }>('/api/admin/ai/services') })
  const health = useQuery({ queryKey: ['admin', 'ai-health'], queryFn: () => api<AIHealth>('/api/admin/ai/health').catch((e: Error) => ({ status: 'unreachable', error: e.message }) as AIHealth) })
  if (services.isLoading) return <Spinner />
  if (services.error) return <ErrorBox error={services.error} onRetry={() => void services.refetch()} />
  const h = health.data
  return (
    <>
      {h && (
        <p className={`notice${h.status === 'healthy' ? '' : ' notice-error'}`}>
          Servicio de IA: <strong>{AI_STATUS[h.status] ?? h.status}</strong>
          {h.checks &&
            Object.entries(h.checks)
              .filter(([, v]) => !['healthy', 'ready', 'configured', 'closed'].includes(v))
              .map(([k, v]) => ` · ${k}: ${v}`)
              .join('')}
          {h.embedding && ` · embeddings ${h.embedding.model} (${h.embedding.dims} dimensiones)`}
          {h.error && ` · ${h.error}`}
        </p>
      )}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Tarea</th>
              <th>Modelo</th>
              <th>Reserva</th>
              <th className="num">Tokens</th>
              <th>Esfuerzo</th>
              <th>Prompt</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {services.data?.items.map((s) => (
              <tr key={s.service_type}>
                <td>
                  <strong>{service(s.service_type)}</strong> {!s.is_active && <Badge tone="warning">inactiva</Badge>}
                  <div className="row-sub">
                    <code>{s.service_type}</code>
                  </div>
                </td>
                <td>
                  <code>{s.model_name}</code>
                </td>
                <td>{s.fallback_model ? <code>{s.fallback_model}</code> : <span className="muted">—</span>}</td>
                <td className="num">{num(s.max_tokens)}</td>
                <td>{s.effort ?? <span className="muted">—</span>}</td>
                <td>{s.prompt_name ? <Link to={`/prompts/${encodeURIComponent(s.prompt_name)}`}>{s.prompt_name}</Link> : <span className="muted">—</span>}</td>
                <td className="num">
                  {can('llm_config', 'write') && (
                    <button className="btn btn-small btn-ghost" onClick={() => setEditing(s)}>
                      Editar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && <ServiceForm config={editing} onClose={() => setEditing(null)} />}
    </>
  )
}

// ---------------------------------------------------------------- Presupuestos
function BudgetForm({ budget, onClose }: { budget?: Budget; onClose: () => void }) {
  const qc = useQueryClient()
  const services = useQuery({ queryKey: ['admin', 'services'], queryFn: () => api<{ items: ServiceConfig[] }>('/api/admin/ai/services') })
  const [form, setForm] = useState({
    scope: budget?.scope ?? 'global',
    scope_id: budget?.scope_id ?? '',
    daily_limit_usd: budget?.daily_limit_usd ?? '',
    monthly_limit_usd: budget?.monthly_limit_usd ?? '',
    alert_threshold_pct: String(budget?.alert_threshold_pct ?? 80),
    throttle_threshold_pct: String(budget?.throttle_threshold_pct ?? 95),
    block_threshold_pct: String(budget?.block_threshold_pct ?? 100),
    is_active: budget?.is_active ?? true,
  })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...form,
        scope_id: form.scope === 'global' ? '' : form.scope_id,
        daily_limit_usd: form.daily_limit_usd || null,
        monthly_limit_usd: form.monthly_limit_usd || null,
        alert_threshold_pct: Number(form.alert_threshold_pct),
        throttle_threshold_pct: Number(form.throttle_threshold_pct),
        block_threshold_pct: Number(form.block_threshold_pct),
        throttle_delay_seconds: budget?.throttle_delay_seconds ?? 2,
      }
      return budget ? api<Budget>(`/api/admin/ai/budgets/${budget.id}`, { method: 'PUT', body }) : api<Budget>('/api/admin/ai/budgets', { body })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'budgets'] })
      onClose()
    },
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title={budget ? 'Editar presupuesto' : 'Nuevo presupuesto'} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Se aplica a">
            <select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value as Budget['scope'], scope_id: '' })} disabled={!!budget}>
              {Object.entries(BUDGET_SCOPE).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          {form.scope === 'service' && (
            <Field label="Tipo de tarea">
              <select value={form.scope_id} onChange={set('scope_id')} required disabled={!!budget}>
                <option value="">—</option>
                {services.data?.items.map((s) => (
                  <option key={s.service_type} value={s.service_type}>
                    {service(s.service_type)}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {form.scope === 'user' && (
            <Field label="Id de la persona" hint="Vacío: el límite se aplica a cada persona por separado.">
              <input value={form.scope_id} onChange={set('scope_id')} inputMode="numeric" pattern="[0-9]*" disabled={!!budget} />
            </Field>
          )}
        </div>
        <div className="grid-2">
          <Field label="Límite diario (USD)">
            <input type="number" min={0} step="0.01" value={form.daily_limit_usd} onChange={set('daily_limit_usd')} />
          </Field>
          <Field label="Límite mensual (USD)">
            <input type="number" min={0} step="0.01" value={form.monthly_limit_usd} onChange={set('monthly_limit_usd')} />
          </Field>
        </div>
        <div className="grid-3">
          <Field label="Aviso al (%)">
            <input type="number" min={1} max={100} value={form.alert_threshold_pct} onChange={set('alert_threshold_pct')} required />
          </Field>
          <Field label="Frenar al (%)">
            <input type="number" min={1} max={100} value={form.throttle_threshold_pct} onChange={set('throttle_threshold_pct')} required />
          </Field>
          <Field label="Bloquear al (%)">
            <input type="number" min={1} max={1000} value={form.block_threshold_pct} onChange={set('block_threshold_pct')} required />
          </Field>
        </div>
        <p className="field-hint">Al llegar al aviso se avisa a Administración; al frenar, cada llamada espera unos segundos; al bloquear, se rechaza.</p>
        <label className="check">
          <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Activo
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

function Budgets() {
  const { can } = useAuth()
  const [editing, setEditing] = useState<Budget | 'new' | null>(null)
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['admin', 'budgets'], queryFn: () => api<{ items: Budget[] }>('/api/admin/ai/budgets') })
  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  const canWrite = can('llm_config', 'write')
  return (
    <>
      {canWrite && (
        <div className="toolbar">
          <span className="grow" />
          <button className="btn btn-primary" onClick={() => setEditing('new')}>
            Nuevo presupuesto
          </button>
        </div>
      )}
      {!data?.items.length ? (
        <Empty title="Sin presupuestos: el gasto no tiene límite" />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Ámbito</th>
                <th>Hoy</th>
                <th>Este mes</th>
                <th>Umbrales</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((b) => (
                <tr key={b.id}>
                  <td>
                    {BUDGET_SCOPE[b.scope]}
                    {b.scope_id && <div className="row-sub">{b.scope === 'service' ? service(b.scope_id) : `Persona #${b.scope_id}`}</div>}
                    {!b.is_active && <Badge>inactivo</Badge>}
                  </td>
                  {perPerson(b) ? (
                    <>
                      <td>{b.daily_limit_usd ? `${usd(b.daily_limit_usd)} por persona` : '—'}</td>
                      <td>{b.monthly_limit_usd ? `${usd(b.monthly_limit_usd)} por persona` : '—'}</td>
                    </>
                  ) : (
                    <>
                      <td className="meter-cell">
                        <span className="row-sub">
                          {usd(b.spent_today_usd)} {b.daily_limit_usd ? `de ${usd(b.daily_limit_usd)}` : ''}
                        </span>
                        <Meter value={Number(b.spent_today_usd)} max={b.daily_limit_usd ? Number(b.daily_limit_usd) : null} warnAt={b.alert_threshold_pct / 100} />
                      </td>
                      <td className="meter-cell">
                        <span className="row-sub">
                          {usd(b.spent_month_usd)} {b.monthly_limit_usd ? `de ${usd(b.monthly_limit_usd)}` : ''}
                        </span>
                        <Meter value={Number(b.spent_month_usd)} max={b.monthly_limit_usd ? Number(b.monthly_limit_usd) : null} warnAt={b.alert_threshold_pct / 100} />
                      </td>
                    </>
                  )}
                  <td className="nowrap">
                    aviso {b.alert_threshold_pct} % · freno {b.throttle_threshold_pct} % · bloqueo {b.block_threshold_pct} %
                  </td>
                  <td className="num">
                    {canWrite && (
                      <button className="btn btn-small btn-ghost" onClick={() => setEditing(b)}>
                        Editar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <BudgetForm budget={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  )
}

// ---------------------------------------------------------------- Uso y ahorro
function BaselineRow({ service_type, baseline, canWrite }: { service_type: string; baseline?: Baseline; canWrite: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({
    minutes: String(baseline?.human_time_minutes ?? ''),
    cost: baseline?.human_hourly_cost_eur ?? '65',
  })
  const dirty = form.minutes !== String(baseline?.human_time_minutes ?? '') || form.cost !== (baseline?.human_hourly_cost_eur ?? '65')
  const save = useMutation({
    mutationFn: () =>
      api(`/api/admin/ai/baselines/${service_type}`, {
        method: 'PUT',
        body: { task_name: baseline?.task_name ?? service(service_type), human_time_minutes: Number(form.minutes), human_hourly_cost_eur: form.cost },
      }),
    onSuccess: () => {
      toast('Referencia guardada.')
      void qc.invalidateQueries({ queryKey: ['admin', 'baselines'] })
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })
  return (
    <tr>
      <td>{service(service_type)}</td>
      <td>
        <input
          className="input-small"
          type="number"
          min={0.1}
          step="0.1"
          value={form.minutes}
          disabled={!canWrite}
          onChange={(e) => setForm({ ...form, minutes: e.target.value })}
          aria-label={`Minutos a mano: ${service(service_type)}`}
        />
      </td>
      <td>
        <input
          className="input-small"
          type="number"
          min={0}
          step="0.01"
          value={form.cost}
          disabled={!canWrite}
          onChange={(e) => setForm({ ...form, cost: e.target.value })}
          aria-label={`Coste por hora: ${service(service_type)}`}
        />
      </td>
      <td className="num">
        {canWrite && dirty && form.minutes && (
          <button className="btn btn-small btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>
            Guardar
          </button>
        )}
      </td>
    </tr>
  )
}

function Usage() {
  const { can } = useAuth()
  const [days, setDays] = useState(30)
  const summary = useQuery({
    queryKey: ['admin', 'usage-summary', days],
    queryFn: () => api<{ items: UsageRow[]; total_cost_usd: string }>('/api/admin/ai/usage/summary', { query: { days } }),
  })
  const services = useQuery({ queryKey: ['admin', 'services'], queryFn: () => api<{ items: ServiceConfig[] }>('/api/admin/ai/services') })
  const baselines = useQuery({ queryKey: ['admin', 'baselines'], queryFn: () => api<{ items: Baseline[] }>('/api/admin/ai/baselines') })
  const rows = summary.data?.items ?? []
  const calls = rows.reduce((n, r) => n + r.calls, 0)
  const errors = rows.reduce((n, r) => n + r.errors, 0)
  const fallbacks = rows.reduce((n, r) => n + r.fallbacks, 0)
  return (
    <>
      <div className="toolbar">
        <DaysPicker days={days} onChange={setDays} />
        <span className="grow" />
        <a href="/analytics/ai">Ver el valor de la IA en Analítica</a>
      </div>
      {summary.isLoading && <Spinner />}
      {summary.error && <ErrorBox error={summary.error} />}
      {summary.data && (
        <>
          <div className="stats">
            <Stat label="Gasto" value={usd(summary.data.total_cost_usd)} />
            <Stat label="Llamadas" value={num(calls)} />
            <Stat label="Con error" value={calls ? pct(errors / calls, 1) : '—'} hint={`${errors} llamadas`} />
            <Stat label="Con modelo de reserva" value={num(fallbacks)} />
          </div>
          {!rows.length ? (
            <Empty title="Sin llamadas en el periodo" />
          ) : (
            <div className="table-wrap">
              <table className="table table-compact">
                <thead>
                  <tr>
                    <th>Tarea</th>
                    <th>Modelo</th>
                    <th className="num">Llamadas</th>
                    <th className="num">Tokens entrada</th>
                    <th className="num">Tokens salida</th>
                    <th className="num">De caché</th>
                    <th className="num">Gasto</th>
                    <th className="num">Errores</th>
                    <th className="num">Latencia media</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.service_type}-${r.model}`}>
                      <td>{service(r.service_type)}</td>
                      <td>
                        <code>{r.model}</code>
                      </td>
                      <td className="num">{num(r.calls)}</td>
                      <td className="num">{num(r.input_tokens)}</td>
                      <td className="num">{num(r.output_tokens)}</td>
                      <td className="num">{num(r.cache_read_tokens)}</td>
                      <td className="num">{usd(r.cost_usd, true)}</td>
                      <td className="num">{r.errors ? <Badge tone="warning">{r.errors}</Badge> : 0}</td>
                      <td className="num">{r.avg_latency_ms !== null ? `${num(r.avg_latency_ms)} ms` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      <section className="card section-gap">
        <h2>Cuánto se tarda a mano</h2>
        <p className="muted">
          Referencia para calcular el ahorro: minutos que lleva cada tarea sin IA y coste por hora de quien la hace. Sin
          referencia, la tarea no cuenta en el ahorro.
        </p>
        {(services.isLoading || baselines.isLoading) && <Spinner />}
        {services.data && baselines.data && (
          <div className="table-wrap">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Tarea</th>
                  <th>Minutos a mano</th>
                  <th>Coste por hora (€)</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {services.data.items.map((s) => (
                  <BaselineRow
                    key={s.service_type}
                    service_type={s.service_type}
                    baseline={baselines.data.items.find((b) => b.service_type === s.service_type)}
                    canWrite={can('llm_config', 'write')}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}

// ---------------------------------------------------------------- Precios
function PricingForm({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    model_name: '',
    effective_date: new Date().toISOString().slice(0, 10),
    input_usd_per_mtok: '',
    output_usd_per_mtok: '',
    cache_read_usd_per_mtok: '',
    cache_write_usd_per_mtok: '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })
  const save = useMutation({
    mutationFn: () =>
      api('/api/admin/ai/pricing', {
        body: { ...form, cache_read_usd_per_mtok: form.cache_read_usd_per_mtok || null, cache_write_usd_per_mtok: form.cache_write_usd_per_mtok || null },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'pricing'] })
      onClose()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title="Nuevo precio" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Modelo">
            <input value={form.model_name} onChange={set('model_name')} required pattern="[A-Za-z0-9._:/\-]{1,100}" autoFocus />
          </Field>
          <Field label="Desde">
            <input type="date" value={form.effective_date} onChange={set('effective_date')} required />
          </Field>
        </div>
        <p className="field-hint">Precios en dólares por millón de tokens, como los publica el proveedor.</p>
        <div className="grid-2">
          <Field label="Entrada">
            <input type="number" min={0} step="0.0001" value={form.input_usd_per_mtok} onChange={set('input_usd_per_mtok')} required />
          </Field>
          <Field label="Salida">
            <input type="number" min={0} step="0.0001" value={form.output_usd_per_mtok} onChange={set('output_usd_per_mtok')} required />
          </Field>
          <Field label="Lectura de caché">
            <input type="number" min={0} step="0.0001" value={form.cache_read_usd_per_mtok} onChange={set('cache_read_usd_per_mtok')} />
          </Field>
          <Field label="Escritura de caché">
            <input type="number" min={0} step="0.0001" value={form.cache_write_usd_per_mtok} onChange={set('cache_write_usd_per_mtok')} />
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

function PricingTab() {
  const { can } = useAuth()
  const [adding, setAdding] = useState(false)
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['admin', 'pricing'], queryFn: () => api<{ items: Pricing[] }>('/api/admin/ai/pricing') })
  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  return (
    <>
      <div className="toolbar">
        <p className="muted grow">Un precio nuevo se aplica desde su fecha; el anterior queda para recalcular el histórico.</p>
        {can('llm_config', 'write') && (
          <button className="btn btn-primary" onClick={() => setAdding(true)}>
            Nuevo precio
          </button>
        )}
      </div>
      <div className="table-wrap">
        <table className="table table-compact">
          <thead>
            <tr>
              <th>Modelo</th>
              <th>Desde</th>
              <th className="num">Entrada</th>
              <th className="num">Salida</th>
              <th className="num">Lectura caché</th>
              <th className="num">Escritura caché</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((p) => (
              <tr key={`${p.model_name}-${p.effective_date}`}>
                <td>
                  <code>{p.model_name}</code>
                </td>
                <td>{fmtDate(p.effective_date)}</td>
                <td className="num">{usd(p.input_usd_per_mtok, true)}</td>
                <td className="num">{usd(p.output_usd_per_mtok, true)}</td>
                <td className="num">{usd(p.cache_read_usd_per_mtok, true)}</td>
                <td className="num">{usd(p.cache_write_usd_per_mtok, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="field-hint">Dólares por millón de tokens.</p>
      {adding && <PricingForm onClose={() => setAdding(false)} />}
    </>
  )
}

// ---------------------------------------------------------------- Calidad
const REVIEWERS: Record<string, string> = { user: 'Valoración de las personas', llm_judge: 'Evaluación automática', human: 'Revisión experta' }
const score = (v: number | null) => (v === null ? '—' : v.toLocaleString('es-ES', { maximumFractionDigits: 2 }))

function Quality() {
  const [days, setDays] = useState(30)
  const { data, error, isLoading } = useQuery({
    queryKey: ['admin', 'quality', days],
    queryFn: () => api<{ items: QualityRow[] }>('/api/admin/ai/quality', { query: { days } }),
  })
  return (
    <>
      <div className="toolbar">
        <DaysPicker days={days} onChange={setDays} />
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} />}
      {data && !data.items.length && <Empty title="Sin valoraciones en el periodo" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table table-compact">
            <thead>
              <tr>
                <th>Tarea</th>
                <th>Quién valora</th>
                <th className="num">Valoraciones</th>
                <th className="num">Nota global</th>
                <th className="num">Fidelidad</th>
                <th className="num">Relevancia</th>
                <th className="num">Invención</th>
                <th className="num">Estrellas</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((q) => (
                <tr key={`${q.service_type}-${q.reviewer_type}`}>
                  <td>{service(q.service_type)}</td>
                  <td>{REVIEWERS[q.reviewer_type] ?? q.reviewer_type}</td>
                  <td className="num">{q.count}</td>
                  <td className="num">{score(q.composite)}</td>
                  <td className="num">{score(q.faithfulness)}</td>
                  <td className="num">{score(q.relevance)}</td>
                  <td className="num">{score(q.hallucination)}</td>
                  <td className="num">{score(q.user_rating)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="field-hint">Fidelidad, relevancia e invención van de 0 a 1 (en invención, cuanto más bajo mejor). Las estrellas, de 1 a 5.</p>
    </>
  )
}

// ---------------------------------------------------------------- Cumplimiento
function ComplianceTab() {
  const [days, setDays] = useState(30)
  const { data, error, isLoading } = useQuery({
    queryKey: ['admin', 'compliance', days],
    queryFn: () => api<Compliance>('/api/admin/ai/compliance', { query: { days } }),
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
          <div className="stats">
            {Object.entries(data.events).map(([k, v]) => (
              <Stat key={k} label={COMPLIANCE_EVENTS[k] ?? k} value={v} hint={v ? <Link to={`/audit?action=${k}&days=${days}`}>Ver en auditoría</Link> : undefined} />
            ))}
            <Stat
              label="Respuestas con datos personales"
              value={data.outputs_scanned ? pct(data.outputs_with_pii / data.outputs_scanned, 1) : '—'}
              hint={`${data.outputs_with_pii} de ${data.outputs_scanned} revisadas`}
            />
          </div>
          <section className="card section-gap">
            <h2>Integridad de los prompts</h2>
            {data.prompt_integrity.length ? (
              <ul className="plain-list">
                {data.prompt_integrity.map((p) => (
                  <li key={p.name}>
                    <Link to={`/prompts/${encodeURIComponent(p.name)}`}>
                      <code>{p.name}</code>
                    </Link>{' '}
                    v{p.version} <Badge tone="danger">modificado fuera de Admin</Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Todos los prompts activos coinciden con lo publicado desde aquí.</p>
            )}
          </section>
          <p className="field-hint">
            Para exportar o borrar los datos de IA de una persona (RGPD), entra en su ficha desde <Link to="/users">Usuarios</Link>.
          </p>
        </>
      )}
    </>
  )
}

// ---------------------------------------------------------------- RAG
const INDEX_LABELS: Record<string, string> = { indexed: 'Indexados', pending: 'Indexándose', failed: 'Con error', none: 'Sin indexar', skipped: 'No indexables' }

function Rag() {
  const { can } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const { data, error, isLoading } = useQuery({ queryKey: ['admin', 'rag'], queryFn: () => api<RagCollections>('/api/admin/ai/rag/collections') })
  const reindex = useMutation({
    mutationFn: (onlyFailed: boolean) => api<{ queued: number }>('/api/admin/ai/rag/reindex', { method: 'POST', query: { only_failed: onlyFailed ? 'true' : null } }),
    onSuccess: (r) => {
      toast(`${r.queued} documentos en cola para indexar.`)
      void qc.invalidateQueries({ queryKey: ['admin', 'rag'] })
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })
  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} />
  if (!data) return null
  const q = data.qdrant
  return (
    <>
      <div className="stats">
        {Object.entries(data.documents_by_index_status).map(([k, v]) => (
          <Stat key={k} label={INDEX_LABELS[k] ?? k} value={num(v)} />
        ))}
      </div>
      {can('llm_config', 'write') && (
        <div className="toolbar">
          <span className="grow muted">Reindexar vuelve a trocear y a calcular los vectores en segundo plano.</span>
          <button className="btn" disabled={reindex.isPending} onClick={() => reindex.mutate(true)}>
            Reindexar los fallidos
          </button>
          <button className="btn btn-ghost" disabled={reindex.isPending} onClick={() => reindex.mutate(false)}>
            Reindexar todo
          </button>
        </div>
      )}
      <section className="card section-gap">
        <h2>Colecciones de vectores</h2>
        {'error' in q ? (
          <p className="notice notice-error">No se ha podido consultar Qdrant: {q.error}</p>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table table-compact">
                <thead>
                  <tr>
                    <th>Colección</th>
                    <th>Contenido</th>
                    <th className="num">Fragmentos</th>
                  </tr>
                </thead>
                <tbody>
                  {q.collections.map((c) => (
                    <tr key={c.collection}>
                      <td>
                        <code>{c.collection}</code>
                        <div className="row-sub">{c.physical}</div>
                      </td>
                      <td>{c.description}</td>
                      <td className="num">{num(c.points)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="field-hint">Modelo de embeddings: {q.embedding_model}.</p>
          </>
        )}
      </section>
    </>
  )
}
