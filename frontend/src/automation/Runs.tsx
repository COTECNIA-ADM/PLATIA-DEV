// Ejecuciones del portal Low-Code: cada persona ve las suyas; quien administra, todas.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtRelative } from '../lib/format'
import type { Page } from '../lib/types'
import { Empty, ErrorBox, Pager, Spinner } from '../components/ui'
import { OPEN_STATUSES, RUN_STATUS, RunStatusBadge } from './common'
import type { Run, RunStatus } from './types'

export default function Runs() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const mine = params.get('mine') ?? ''
  const page = Number(params.get('page') ?? 1)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['automation', 'runs', status, mine, page],
    queryFn: () => api<Page<Run>>('/api/automation/runs', { query: { status, mine, page } }),
    placeholderData: keepPreviousData,
    // Mientras haya alguna en marcha, se refresca sola
    refetchInterval: (query) =>
      query.state.data?.items.some((r) => OPEN_STATUSES.includes(r.status)) ? 5000 : false,
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
          <h1>Ejecuciones</h1>
          <p className="muted">
            {can('automations', 'manage')
              ? 'Todas las automatizaciones lanzadas desde PLATIA.'
              : 'Las automatizaciones que has lanzado.'}
          </p>
        </div>
      </header>
      <div className="toolbar">
        <select value={status} onChange={(e) => setFilter('status', e.target.value)} aria-label="Estado">
          <option value="">Todos los estados</option>
          {(Object.keys(RUN_STATUS) as RunStatus[]).map((s) => (
            <option key={s} value={s}>
              {RUN_STATUS[s].label}
            </option>
          ))}
        </select>
        {can('automations', 'manage') && (
          <label className="check">
            <input type="checkbox" checked={mine === 'true'} onChange={(e) => setFilter('mine', e.target.checked ? 'true' : '')} />
            Solo las mías
          </label>
        )}
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay ejecuciones" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Automatización</th>
                <th>Estado</th>
                <th>Lanzada</th>
                <th>Terminada</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id}>
                  <td className="row-title">
                    <Link to={`/runs/${r.id}`}>{r.workflow_name}</Link>
                  </td>
                  <td>
                    <RunStatusBadge status={r.status} />
                  </td>
                  <td>{fmtRelative(r.created_at)}</td>
                  <td>{r.finished_at ? fmtRelative(r.finished_at) : '—'}</td>
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
    </div>
  )
}
