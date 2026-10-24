// Auditoría: registro inmutable de acciones, con filtros en la URL y el detalle de cada una.
import { Fragment, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtDateTime } from '../lib/format'
import type { Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Pager, Spinner } from '../components/ui'
import { SEVERITY_TONE } from './labels'
import type { AuditEntry } from './types'

const DAYS: Record<string, string> = { '1': 'Últimas 24 horas', '7': 'Últimos 7 días', '30': 'Últimos 30 días', '90': 'Últimos 90 días' }

/** AI_REQUEST_BLOCKED → «ai request blocked», legible sin perder el código original. */
function actionLabel(action: string) {
  return action.toLowerCase().replace(/_/g, ' ')
}

export default function Audit() {
  const [params, setParams] = useSearchParams()
  const [open, setOpen] = useState<number | null>(null)
  const action = params.get('action') ?? ''
  const severity = params.get('severity') ?? ''
  const userId = params.get('user_id') ?? ''
  const days = params.get('days') ?? ''
  const page = Number(params.get('page') ?? 1)
  const actions = useQuery({ queryKey: ['admin', 'audit-actions'], queryFn: () => api<{ items: string[] }>('/api/admin/audit/actions'), staleTime: Infinity })
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['admin', 'audit', action, severity, userId, days, page],
    queryFn: () => api<Page<AuditEntry>>('/api/admin/audit', { query: { action, severity, user_id: userId, days, page } }),
    placeholderData: keepPreviousData,
  })
  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    setParams(next)
  }

  return (
    <div className={`page${isFetching ? ' is-refreshing' : ''}`}>
      <header className="page-head">
        <div>
          <h1>Auditoría</h1>
          <p className="muted">Accesos, cambios de permisos y configuración, y eventos de seguridad de la IA. No se puede modificar.</p>
        </div>
      </header>
      <div className="toolbar">
        <select value={action} onChange={(e) => setFilter('action', e.target.value)} aria-label="Acción">
          <option value="">Todas las acciones</option>
          {actions.data?.items.map((a) => (
            <option key={a} value={a}>
              {actionLabel(a)}
            </option>
          ))}
        </select>
        <select value={severity} onChange={(e) => setFilter('severity', e.target.value)} aria-label="Gravedad">
          <option value="">Cualquier gravedad</option>
          {['INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select value={days} onChange={(e) => setFilter('days', e.target.value)} aria-label="Periodo">
          <option value="">Desde el principio</option>
          {Object.entries(DAYS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        {userId && (
          <button className="btn btn-small btn-ghost" onClick={() => setFilter('user_id', '')}>
            Usuario #{userId} ×
          </button>
        )}
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay registros con estos filtros" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table table-compact">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Acción</th>
                <th>Gravedad</th>
                <th>Quién</th>
                <th>Sobre</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <Fragment key={row.id}>
                  <tr>
                    <td className="nowrap">{fmtDateTime(row.created_at)}</td>
                    <td>
                      <code>{row.action}</code>
                    </td>
                    <td>
                      <Badge tone={SEVERITY_TONE[row.severity] ?? 'neutral'}>{row.severity}</Badge>
                    </td>
                    <td>
                      {row.user_id ? (
                        <Link to={`/users/${row.user_id}`}>{row.user_email ?? `#${row.user_id}`}</Link>
                      ) : (
                        <span className="muted">Sistema</span>
                      )}
                    </td>
                    <td>
                      {row.resource_type ? (
                        <span>
                          {row.resource_type}
                          {row.resource_id && <span className="muted"> #{row.resource_id}</span>}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="num">
                      <button className="btn btn-small btn-ghost" aria-expanded={open === row.id} onClick={() => setOpen(open === row.id ? null : row.id)}>
                        {open === row.id ? 'Ocultar' : 'Detalle'}
                      </button>
                    </td>
                  </tr>
                  {open === row.id && (
                    <tr className="row-detail">
                      <td colSpan={6}>
                        <dl className="facts facts-compact">
                          <span className="facts-pair">
                            <dt>IP</dt>
                            <dd>{row.ip_address ?? '—'}</dd>
                          </span>
                          <span className="facts-pair">
                            <dt>Petición</dt>
                            <dd>
                              <code>{row.request_id ?? '—'}</code>
                            </dd>
                          </span>
                        </dl>
                        {row.details ? <pre className="code-block">{JSON.stringify(row.details, null, 2)}</pre> : <p className="muted">Sin más detalle.</p>}
                      </td>
                    </tr>
                  )}
                </Fragment>
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
    </div>
  )
}
