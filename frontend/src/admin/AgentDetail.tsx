// Un agente: configuración, herramientas con su nivel de aprobación, prueba en sandbox,
// versiones y métricas de uso.
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { TOOL_NAMES, fmtDateTime } from '../lib/format'
import type { Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Field, Spinner, Stat, errorMessage, useToast } from '../components/ui'
import { SERVICE_TYPES } from '../analytics/AIValue'
import { Tabs, pct, useTab } from './common'
import { AGENT_STATUS, APPROVAL_LEVELS, usd } from './labels'
import { AGENT_TYPES, AgentStatus } from './Agents'
import type { Agent, AgentMetrics, AgentRun, AgentTestResult, AgentTool, AgentVersion, ServiceConfig, ToolInfo } from './types'

const TABS = ['config', 'tools', 'test', 'metrics', 'versions'] as const
const TAB_LABELS = { config: 'Configuración', tools: 'Herramientas', test: 'Probar', metrics: 'Uso', versions: 'Versiones' }
const LEVELS = ['auto', 'notify', 'approve'] as const
const METRIC_NAMES: Record<string, string> = {
  avg_iterations: 'Vueltas por respuesta',
  avg_tool_calls: 'Herramientas por respuesta',
  completion_rate: 'Terminadas bien',
  error_rate: 'Con error',
  p95_duration_ms: 'Duración (p95)',
  approval_rejection_rate: 'Aprobaciones rechazadas',
}

export default function AgentDetail() {
  const { id } = useParams()
  const [tab, setTab] = useTab(TABS)
  const qc = useQueryClient()
  const key = ['admin', 'agent', id]
  const { data, error, isLoading, refetch } = useQuery({ queryKey: key, queryFn: () => api<Agent>(`/api/admin/agents/${id}`) })
  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!data) return null
  const saved = (a: Agent) => {
    qc.setQueryData(key, a)
    void qc.invalidateQueries({ queryKey: ['admin', 'agents'] })
    void qc.invalidateQueries({ queryKey: ['admin', 'agent-versions', id] })
  }
  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/agents">Agentes</Link> / {data.name}
      </nav>
      <header className="page-head">
        <div>
          <h1>
            {data.name} <AgentStatus status={data.status} />
          </h1>
          <p className="muted">
            {data.description ?? 'Sin descripción'} · {AGENT_TYPES[data.agent_type]} · versión {data.version_number}
          </p>
        </div>
      </header>
      <Tabs tabs={TABS.map((t) => ({ key: t, label: TAB_LABELS[t] }))} value={tab} onChange={setTab} />
      {tab === 'config' && <Config agent={data} onSaved={saved} />}
      {tab === 'tools' && <ToolsTab agent={data} onSaved={saved} />}
      {tab === 'test' && <TestTab agent={data} />}
      {tab === 'metrics' && <Metrics agent={data} />}
      {tab === 'versions' && <Versions agent={data} onSaved={saved} />}
    </div>
  )
}

// ---------------------------------------------------------------- Configuración
function Config({ agent, onSaved }: { agent: Agent; onSaved: (a: Agent) => void }) {
  const { can } = useAuth()
  const toast = useToast()
  const services = useQuery({ queryKey: ['admin', 'services'], queryFn: () => api<{ items: ServiceConfig[] }>('/api/admin/ai/services') })
  const [form, setForm] = useState({
    name: agent.name,
    description: agent.description ?? '',
    status: agent.status,
    llm_service_type: agent.llm_service_type,
    max_iterations: String(agent.max_iterations),
    max_tool_calls: String(agent.max_tool_calls),
    timeout_seconds: String(agent.timeout_seconds),
    intent_keywords: agent.intent_keywords.join(', '),
    success_criteria: agent.success_criteria ?? '',
    notes: '',
  })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })
  const save = useMutation({
    mutationFn: () =>
      api<Agent>(`/api/admin/agents/${agent.id}`, {
        method: 'PATCH',
        body: {
          version: agent.version,
          name: form.name,
          description: form.description || null,
          status: form.status,
          llm_service_type: form.llm_service_type,
          max_iterations: Number(form.max_iterations),
          max_tool_calls: Number(form.max_tool_calls),
          timeout_seconds: Number(form.timeout_seconds),
          intent_keywords: form.intent_keywords.split(',').map((s) => s.trim()).filter(Boolean),
          success_criteria: form.success_criteria || null,
          notes: form.notes || null,
        },
      }),
    onSuccess: (a) => {
      onSaved(a)
      setForm((f) => ({ ...f, notes: '' }))
      toast(`Guardado como versión ${a.version_number}.`)
    },
  })
  const canWrite = can('agents', 'write')
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <div className="detail-grid">
      <form className="card stack" onSubmit={submit}>
        <fieldset disabled={!canWrite} className="stack">
          <div className="grid-2">
            <Field label="Nombre">
              <input value={form.name} onChange={set('name')} required maxLength={100} />
            </Field>
            <Field label="Estado" hint="Solo los activos los usa el copiloto.">
              <select value={form.status} onChange={set('status')}>
                {Object.entries(AGENT_STATUS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Para qué sirve">
            <input value={form.description} onChange={set('description')} maxLength={500} />
          </Field>
          <Field label="Tipo de tarea de IA" hint="Decide el modelo y el presupuesto que usa.">
            <select value={form.llm_service_type} onChange={set('llm_service_type')}>
              {(services.data?.items ?? [{ service_type: agent.llm_service_type }]).map((s) => (
                <option key={s.service_type} value={s.service_type}>
                  {SERVICE_TYPES[s.service_type] ?? s.service_type}
                </option>
              ))}
            </select>
          </Field>
          <div className="grid-3">
            <Field label="Vueltas máximas">
              <input type="number" min={1} max={25} value={form.max_iterations} onChange={set('max_iterations')} />
            </Field>
            <Field label="Herramientas máximas">
              <input type="number" min={1} max={50} value={form.max_tool_calls} onChange={set('max_tool_calls')} />
            </Field>
            <Field label="Tiempo máximo (s)">
              <input type="number" min={10} max={600} value={form.timeout_seconds} onChange={set('timeout_seconds')} />
            </Field>
          </div>
          <Field label="Palabras que lo activan" hint="Separadas por comas. Ayudan a elegir este agente.">
            <input value={form.intent_keywords} onChange={set('intent_keywords')} />
          </Field>
          <Field label="Cuándo ha hecho bien su trabajo">
            <textarea rows={3} value={form.success_criteria} onChange={set('success_criteria')} maxLength={2000} />
          </Field>
          <Field label="Nota de la versión">
            <input value={form.notes} onChange={set('notes')} maxLength={500} placeholder="Qué cambias y por qué" />
          </Field>
          {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
          {canWrite && (
            <div className="actions">
              <button className="btn btn-primary" disabled={save.isPending}>
                Guardar
              </button>
            </div>
          )}
        </fieldset>
      </form>
      <aside className="card">
        <header className="card-head">
          <h2>Prompt</h2>
          <Link to={`/prompts/${encodeURIComponent(agent.prompt_name)}`}>{agent.prompt ? 'Editar' : 'Publicar'}</Link>
        </header>
        {agent.prompt ? (
          <>
            <p className="muted">
              <code>{agent.prompt_name}</code> · versión {agent.prompt.version}
            </p>
            <pre className="code-block code-block-short">{agent.prompt.system_prompt}</pre>
          </>
        ) : (
          <p className="notice notice-error">
            Falta el prompt <code>{agent.prompt_name}</code>. Sin él no se puede activar.
          </p>
        )}
      </aside>
    </div>
  )
}

// ---------------------------------------------------------------- Herramientas
function ToolsTab({ agent, onSaved }: { agent: Agent; onSaved: (a: Agent) => void }) {
  const { can } = useAuth()
  const toast = useToast()
  const catalog = useQuery({ queryKey: ['admin', 'tool-catalog'], queryFn: () => api<{ items: ToolInfo[]; max_tools_per_agent: number }>('/api/admin/agents/tools') })
  const [selected, setSelected] = useState<Record<string, AgentTool['approval_level']>>(() =>
    Object.fromEntries(agent.tools.map((t) => [t.tool_name, t.approval_level])),
  )
  const save = useMutation({
    mutationFn: () =>
      api<Agent>(`/api/admin/agents/${agent.id}/tools`, {
        method: 'PUT',
        body: { version: agent.version, tools: Object.entries(selected).map(([tool_name, approval_level], i) => ({ tool_name, approval_level, sort_order: i })) },
      }),
    onSuccess: (a) => {
      onSaved(a)
      toast('Herramientas guardadas.')
    },
  })
  if (catalog.isLoading) return <Spinner />
  if (catalog.error) return <ErrorBox error={catalog.error} />
  const max = catalog.data?.max_tools_per_agent ?? 12
  const count = Object.keys(selected).length
  const canWrite = can('agents', 'write')
  const dirty =
    count !== agent.tools.length || agent.tools.some((t) => selected[t.tool_name] !== t.approval_level)
  return (
    <section className="card">
      <p className="muted">
        Elige qué puede hacer el agente ({count} de {max} como máximo). Cada herramienta tiene un nivel mínimo: lo que
        cambia datos siempre pide aprobación y no se puede rebajar.
      </p>
      <div className="table-wrap">
        <table className="table table-compact">
          <thead>
            <tr>
              <th />
              <th>Herramienta</th>
              <th>Permiso necesario</th>
              <th>Cómo se usa</th>
            </tr>
          </thead>
          <tbody>
            {catalog.data?.items.map((t) => {
              const on = t.name in selected
              const minIdx = LEVELS.indexOf(t.min_level)
              return (
                <tr key={t.name}>
                  <td>
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={!canWrite || (!on && count >= max)}
                      aria-label={t.title}
                      onChange={() => {
                        const next = { ...selected }
                        if (on) delete next[t.name]
                        else next[t.name] = t.min_level
                        setSelected(next)
                      }}
                    />
                  </td>
                  <td>
                    <strong>{TOOL_NAMES[t.name] ?? t.title}</strong>
                    <div className="row-sub">{t.description}</div>
                  </td>
                  <td>
                    <code>{t.permission}</code>
                    {t.ai_module && <div className="row-sub">IA: {t.ai_module}</div>}
                  </td>
                  <td>
                    {on ? (
                      <select
                        value={selected[t.name]}
                        disabled={!canWrite}
                        aria-label={`Nivel de ${t.title}`}
                        onChange={(e) => setSelected({ ...selected, [t.name]: e.target.value as AgentTool['approval_level'] })}
                      >
                        {LEVELS.slice(minIdx).map((l) => (
                          <option key={l} value={l}>
                            {APPROVAL_LEVELS[l]}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="muted">Mínimo: {APPROVAL_LEVELS[t.min_level].toLowerCase()}</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
      {canWrite && (
        <div className="actions">
          <button className="btn btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            Guardar herramientas
          </button>
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- Probar
function TraceEvent({ e }: { e: AgentTestResult['trace'][number] }) {
  const name = typeof e.name === 'string' ? e.name : typeof e.tool === 'string' ? e.tool : ''
  const label: Record<string, string> = {
    tool_call: 'Llama a',
    tool_result: 'Resultado de',
    notice: 'Aviso de',
    approval_required: 'Pide aprobación',
    done: 'Terminado',
    error: 'Error',
    replace: 'Reescribe la respuesta',
  }
  const ok = e.ok === false ? <Badge tone="danger">falla</Badge> : e.rejected ? <Badge tone="warning">rechazada</Badge> : null
  return (
    <li>
      <strong>{label[e.event] ?? e.event}</strong> {name && <code>{TOOL_NAMES[name] ?? name}</code>} {ok}
      {typeof e.summary === 'string' && <div className="row-sub">{e.summary}</div>}
      {typeof e.message === 'string' && <div className="row-sub">{e.message}</div>}
      {typeof e.ms === 'number' && <span className="muted"> · {e.ms} ms</span>}
    </li>
  )
}

function TestTab({ agent }: { agent: Agent }) {
  const { can } = useAuth()
  const [input, setInput] = useState(agent.test_cases[0]?.input ?? '')
  const [expect, setExpect] = useState<string[]>(agent.test_cases[0]?.expect_tools ?? [])
  const run = useMutation({
    mutationFn: () => api<AgentTestResult>(`/api/admin/agents/${agent.id}/test`, { body: { input, expect_tools: expect } }),
  })
  if (!can('agents', 'write')) return <Empty title="Probar un agente necesita permiso de edición en Agentes" />
  function submit(e: FormEvent) {
    e.preventDefault()
    run.mutate()
  }
  const summary = run.data?.summary as { iterations?: number; cost_usd?: string; status?: string } | undefined
  return (
    <div className="detail-grid">
      <form className="card stack" onSubmit={submit}>
        <p className="muted">
          Se ejecuta en modo prueba, también en borrador: las herramientas que cambian datos no se aplican. Consume tokens
          del modelo.
        </p>
        {agent.test_cases.length > 0 && (
          <Field label="Casos guardados">
            <select
              onChange={(e) => {
                const c = agent.test_cases[Number(e.target.value)]
                if (c) {
                  setInput(c.input)
                  setExpect(c.expect_tools)
                }
              }}
            >
              {agent.test_cases.map((c, i) => (
                <option key={i} value={i}>
                  {c.input.slice(0, 80)}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Lo que diría una persona">
          <textarea rows={4} value={input} onChange={(e) => setInput(e.target.value)} required maxLength={2000} />
        </Field>
        {agent.tools.length > 0 && (
          <fieldset className="stack">
            <legend className="field-label">Debería usar</legend>
            {agent.tools.map((t) => (
              <label key={t.tool_name} className="check">
                <input
                  type="checkbox"
                  checked={expect.includes(t.tool_name)}
                  onChange={() => setExpect(expect.includes(t.tool_name) ? expect.filter((x) => x !== t.tool_name) : [...expect, t.tool_name])}
                />
                {TOOL_NAMES[t.tool_name] ?? t.tool_name}
              </label>
            ))}
          </fieldset>
        )}
        {run.error && <p className="notice notice-error">{errorMessage(run.error)}</p>}
        <div className="actions">
          <button className="btn btn-primary" disabled={run.isPending}>
            {run.isPending ? 'Ejecutando…' : 'Ejecutar'}
          </button>
        </div>
      </form>
      <section className="card stack">
        <h2>Resultado</h2>
        {run.isPending && <Spinner label="El agente está trabajando…" />}
        {!run.data && !run.isPending && <p className="muted">Aquí verás la respuesta y cada paso que da.</p>}
        {run.data && (
          <>
            {run.data.check && (
              <p className={`notice${run.data.check.passed ? ' notice-success' : ' notice-error'}`}>
                {run.data.check.passed ? 'Ha usado las herramientas esperadas.' : `No ha usado: ${run.data.check.missing.map((t) => TOOL_NAMES[t] ?? t).join(', ')}`}
              </p>
            )}
            <pre className="code-block">{run.data.text || '(sin texto)'}</pre>
            <h3>Pasos</h3>
            <ol className="trace">
              {run.data.trace.map((e, i) => (
                <TraceEvent key={i} e={e} />
              ))}
            </ol>
            <p className="field-hint">
              {summary?.iterations ?? '?'} vueltas · {usd(summary?.cost_usd, true)} · ejecución <code>{run.data.run_id}</code>
            </p>
          </>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------- Uso
function metricValue(key: string, v: number) {
  if (key.endsWith('_rate')) return pct(v)
  if (key.endsWith('_ms')) return `${(v / 1000).toLocaleString('es-ES', { maximumFractionDigits: 1 })} s`
  return v.toLocaleString('es-ES', { maximumFractionDigits: 2 })
}

function Metrics({ agent }: { agent: Agent }) {
  const [days, setDays] = useState(30)
  const metrics = useQuery({
    queryKey: ['admin', 'agent-metrics', agent.id, days],
    queryFn: () => api<AgentMetrics>(`/api/admin/agents/${agent.id}/metrics`, { query: { days } }),
  })
  const runs = useQuery({
    queryKey: ['admin', 'agent-runs', agent.id],
    queryFn: () => api<Page<AgentRun>>('/api/admin/agents/runs', { query: { agent_id: agent.id, per_page: 20 } }),
  })
  const m = metrics.data?.metrics
  return (
    <>
      <div className="toolbar">
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Periodo">
          {[7, 30, 90].map((d) => (
            <option key={d} value={d}>
              Últimos {d} días
            </option>
          ))}
        </select>
        <span className="muted">Solo conversaciones reales del copiloto; las pruebas no cuentan.</span>
      </div>
      {metrics.isLoading && <Spinner />}
      {metrics.error && <ErrorBox error={metrics.error} />}
      {metrics.data && m && (
        <>
          {metrics.data.alerts.length > 0 && (
            <p className="notice notice-error">
              Fuera de lo normal:{' '}
              {metrics.data.alerts.map((a) => `${METRIC_NAMES[a.metric] ?? a.metric} ${metricValue(a.metric, a.value)} (límite ${metricValue(a.metric, a.threshold)})`).join(' · ')}
            </p>
          )}
          <div className="stats">
            <Stat label="Conversaciones" value={m.runs} />
            <Stat label="Terminadas bien" value={pct(m.completion_rate)} />
            <Stat label="Con error" value={pct(m.error_rate)} />
            <Stat label="Coste medio" value={usd(m.avg_cost_usd, true)} />
            <Stat label="Duración (p95)" value={m.p95_duration_ms !== null ? metricValue('p95_duration_ms', m.p95_duration_ms) : '—'} />
            <Stat label="Aprobaciones rechazadas" value={pct(m.approval_rejection_rate)} />
          </div>
          {Object.keys(m.tools).length > 0 && (
            <section className="card section-gap">
              <h2>Herramientas usadas</h2>
              <div className="table-wrap">
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th>Herramienta</th>
                      <th className="num">Usos</th>
                      <th className="num">Fallos</th>
                      <th className="num">Tiempo medio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(m.tools)
                      .sort((a, b) => b[1].calls - a[1].calls)
                      .map(([name, t]) => (
                        <tr key={name}>
                          <td>{TOOL_NAMES[name] ?? name}</td>
                          <td className="num">{t.calls}</td>
                          <td className="num">{t.errors}</td>
                          <td className="num">{t.avg_ms} ms</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
      <section className="card section-gap">
        <h2>Últimas ejecuciones</h2>
        {runs.isLoading && <Spinner />}
        {runs.data && !runs.data.items.length && <p className="muted">Todavía no se ha usado.</p>}
        {runs.data && runs.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Modo</th>
                  <th>Estado</th>
                  <th className="num">Vueltas</th>
                  <th>Herramientas</th>
                  <th className="num">Coste</th>
                  <th className="num">Duración</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((r) => (
                  <tr key={r.run_id}>
                    <td className="nowrap">{fmtDateTime(r.created_at)}</td>
                    <td>{r.mode === 'sandbox' ? 'Prueba' : 'Copiloto'}</td>
                    <td>
                      <Badge tone={r.status === 'completed' ? 'success' : r.status === 'failed' ? 'danger' : 'neutral'}>{r.status}</Badge>
                      {r.error && <div className="row-sub">{r.error}</div>}
                    </td>
                    <td className="num">{r.iterations}</td>
                    <td>{r.tool_calls.map((c) => TOOL_NAMES[c.name] ?? c.name).join(', ') || '—'}</td>
                    <td className="num">{usd(r.cost_usd, true)}</td>
                    <td className="num">{r.duration_ms !== null && r.duration_ms >= 0 ? `${(r.duration_ms / 1000).toFixed(1)} s` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}

// ---------------------------------------------------------------- Versiones
function Versions({ agent, onSaved }: { agent: Agent; onSaved: (a: Agent) => void }) {
  const { can } = useAuth()
  const toast = useToast()
  const { data, error, isLoading } = useQuery({
    queryKey: ['admin', 'agent-versions', String(agent.id)],
    queryFn: () => api<{ items: AgentVersion[] }>(`/api/admin/agents/${agent.id}/versions`),
  })
  const restore = useMutation({
    mutationFn: (n: number) => api<Agent>(`/api/admin/agents/${agent.id}/versions/${n}/restore`, { method: 'POST' }),
    onSuccess: (a) => {
      onSaved(a)
      toast(`Restaurada. Ahora es la versión ${a.version_number}.`)
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })
  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} />
  return (
    <section className="card">
      <p className="muted">Cada cambio de configuración o de herramientas guarda una versión. Restaurar crea una versión nueva con aquella configuración.</p>
      <div className="table-wrap">
        <table className="table table-compact">
          <thead>
            <tr>
              <th>Versión</th>
              <th>Nota</th>
              <th>Fecha</th>
              <th>Herramientas</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.items.map((v) => {
              const tools = (v.snapshot.tools as { tool_name: string }[] | undefined) ?? []
              return (
                <tr key={v.version_number}>
                  <td>
                    v{v.version_number} {v.version_number === agent.version_number && <Badge tone="success">actual</Badge>}
                  </td>
                  <td>{v.notes ?? '—'}</td>
                  <td className="nowrap">{fmtDateTime(v.created_at)}</td>
                  <td>{tools.map((t) => TOOL_NAMES[t.tool_name] ?? t.tool_name).join(', ') || '—'}</td>
                  <td className="num">
                    {can('agents', 'write') && v.version_number !== agent.version_number && (
                      <button className="btn btn-small btn-ghost" disabled={restore.isPending} onClick={() => restore.mutate(v.version_number)}>
                        Restaurar
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
