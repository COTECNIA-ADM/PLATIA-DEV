// Resumen de Admin: lo que pide atención hoy (servicios, presupuestos, tareas fallidas,
// eventos de cumplimiento). Cada bloque solo aparece si el rol puede verlo.
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { HealthResponse, Page } from '../lib/types'
import { Meter } from '../components/charts'
import { SERVICE_TYPES } from '../analytics/AIValue'
import { Badge, Spinner, Stat } from '../components/ui'
import type { Budget, Compliance, FailedTask, UsageRow } from './types'
import { BUDGET_SCOPE, COMPLIANCE_EVENTS, perPerson, eur } from './labels'

export default function Overview() {
  const { can, user } = useAuth()
  const health = useQuery({
    queryKey: ['health', true],
    queryFn: () => api<HealthResponse>('/api/health/full'),
    enabled: can('health', 'read'),
  })
  const budgets = useQuery({
    queryKey: ['admin', 'budgets'],
    queryFn: () => api<{ items: Budget[] }>('/api/admin/ai/budgets'),
    enabled: can('llm_config', 'read'),
  })
  const usage = useQuery({
    queryKey: ['admin', 'usage-summary', 30],
    queryFn: () => api<{ items: UsageRow[]; total_cost_usd: string }>('/api/admin/ai/usage/summary', { query: { days: 30 } }),
    enabled: can('llm_config', 'read'),
  })
  const failed = useQuery({
    queryKey: ['admin', 'failed', 'pending'],
    queryFn: () => api<Page<FailedTask>>('/api/admin/tasks/failed', { query: { reviewed: 'false', per_page: 5 } }),
    enabled: can('tasks', 'read'),
  })
  const compliance = useQuery({
    queryKey: ['admin', 'compliance', 7],
    queryFn: () => api<Compliance>('/api/admin/ai/compliance', { query: { days: 7 } }),
    enabled: can('audit', 'read'),
  })

  const down = health.data?.services.filter((s) => s.status !== 'healthy') ?? []
  const calls = usage.data?.items.reduce((n, r) => n + r.calls, 0) ?? 0
  const errors = usage.data?.items.reduce((n, r) => n + r.errors, 0) ?? 0

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Administración</h1>
          <p className="muted">Hola, {user?.full_name}. Esto es lo que pide atención.</p>
        </div>
      </header>
      <div className="stats">
        {can('health', 'read') && (
          <Stat
            label="Servicios"
            value={health.isLoading ? '…' : down.length ? `${down.length} con aviso` : 'Todo bien'}
            hint={<Link to="/status">Ver estado</Link>}
          />
        )}
        {can('llm_config', 'read') && (
          <Stat
            label="Gasto en IA (30 días)"
            value={usage.data ? eur(usage.data.total_cost_usd) : '…'}
            hint={`${calls} llamadas, ${errors} con error`}
          />
        )}
        {can('tasks', 'read') && (
          <Stat
            label="Tareas fallidas sin revisar"
            value={failed.data?.pagination.total ?? '…'}
            hint={<Link to="/tasks">Revisar</Link>}
          />
        )}
        {can('audit', 'read') && (
          <Stat
            label="Peticiones a la IA bloqueadas (7 días)"
            value={compliance.data?.events.AI_REQUEST_BLOCKED ?? '…'}
            hint={<Link to="/audit?action=AI_REQUEST_BLOCKED">Ver en auditoría</Link>}
          />
        )}
      </div>
      <div className="home-grid">
        {can('llm_config', 'read') && (
          <section className="card">
            <header className="card-head">
              <h2>Presupuestos de IA</h2>
              <Link to="/ai?tab=budgets">Gestionar</Link>
            </header>
            {budgets.isLoading && <Spinner />}
            <ul className="plain-list">
              {budgets.data?.items.map((b) => (
                <li key={b.id}>
                  <div className="row-between">
                    <span>
                      {BUDGET_SCOPE[b.scope]}
                      {b.scope_id && <span className="muted"> · {b.scope === 'service' ? SERVICE_TYPES[b.scope_id] ?? b.scope_id : `#${b.scope_id}`}</span>}
                      {!b.is_active && <Badge>inactivo</Badge>}
                    </span>
                    {perPerson(b) ? (
                      <span className="muted">{b.daily_limit_usd ? `${eur(b.daily_limit_usd)} al día por persona` : 'por persona'}</span>
                    ) : (
                      <span className="muted">
                        hoy {eur(b.spent_today_usd)}
                        {b.daily_limit_usd && ` de ${eur(b.daily_limit_usd)}`}
                      </span>
                    )}
                  </div>
                  {!perPerson(b) && (
                    <Meter
                      value={Number(b.spent_today_usd)}
                      max={b.daily_limit_usd ? Number(b.daily_limit_usd) : null}
                      warnAt={b.alert_threshold_pct / 100}
                    />
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
        {can('audit', 'read') && compliance.data && (
          <section className="card">
            <header className="card-head">
              <h2>Cumplimiento (7 días)</h2>
              <Link to="/ai?tab=compliance">Detalle</Link>
            </header>
            <dl className="facts facts-compact">
              {Object.entries(compliance.data.events).map(([k, v]) => (
                <span key={k} className="facts-pair">
                  <dt>{COMPLIANCE_EVENTS[k] ?? k}</dt>
                  <dd>{v ? <Badge tone="warning">{v}</Badge> : 0}</dd>
                </span>
              ))}
              <span className="facts-pair">
                <dt>Respuestas con datos personales</dt>
                <dd>
                  {compliance.data.outputs_with_pii} de {compliance.data.outputs_scanned}
                </dd>
              </span>
            </dl>
            {!!compliance.data.prompt_integrity.length && (
              <p className="notice notice-error">
                Hay prompts modificados fuera de Admin: {compliance.data.prompt_integrity.map((p) => p.name).join(', ')}
              </p>
            )}
          </section>
        )}
        {can('tasks', 'read') && !!failed.data?.items.length && (
          <section className="card">
            <header className="card-head">
              <h2>Últimas tareas fallidas</h2>
              <Link to="/tasks">Ver todas</Link>
            </header>
            <ul className="plain-list">
              {failed.data.items.map((t) => (
                <li key={t.id}>
                  <code>{t.task_name}</code>
                  <div className="row-sub">
                    {t.error_type}: {t.error_message}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
        {can('health', 'read') && !!down.length && (
          <section className="card">
            <h2>Servicios con aviso</h2>
            <ul className="plain-list">
              {down.map((s) => (
                <li key={s.name}>
                  <strong>{s.name}</strong> <Badge tone="danger">{s.status}</Badge>
                  {s.error && <div className="row-sub">{s.error}</div>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
