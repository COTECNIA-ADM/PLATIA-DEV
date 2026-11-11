// Detalle de una ejecución: estado, datos de entrada y resultado que devolvió n8n.
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { api } from '../lib/api'
import { fmtDateTime } from '../lib/format'
import { ErrorBox, Spinner } from '../components/ui'
import { DataTable, OPEN_STATUSES, RunStatusBadge } from './common'
import type { RunDetail as Detail } from './types'

export default function RunDetail() {
  const { id } = useParams()
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['automation', 'run', id],
    queryFn: () => api<Detail>(`/api/automation/runs/${id}`),
    refetchInterval: (query) => (query.state.data && OPEN_STATUSES.includes(query.state.data.status) ? 3000 : false),
  })

  return (
    <div className="page">
      <p>
        <Link to="/runs">← Ejecuciones</Link>
      </p>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && (
        <>
          <header className="page-head">
            <div>
              <h1>{data.workflow_name}</h1>
              <p className="muted">Ejecución n.º {data.id}</p>
            </div>
            <RunStatusBadge status={data.status} />
          </header>
          {OPEN_STATUSES.includes(data.status) && (
            <p className="notice notice-info" role="status">
              La automatización está en marcha. Esta página se actualiza sola.
            </p>
          )}
          {data.error && (
            <p className="notice notice-error" role="alert">
              {data.error}
            </p>
          )}
          <section className="card">
            <dl className="facts">
            <dt>Lanzada</dt>
            <dd>{fmtDateTime(data.created_at)}</dd>
            <dt>Empezó</dt>
            <dd>{data.started_at ? fmtDateTime(data.started_at) : '—'}</dd>
            <dt>Terminó</dt>
            <dd>{data.finished_at ? fmtDateTime(data.finished_at) : '—'}</dd>
            </dl>
          </section>
          <section className="card">
            <h2>Datos de entrada</h2>
            <DataTable data={data.input} empty="Sin datos de entrada." />
          </section>
          <section className="card">
            <h2>Resultado</h2>
            <DataTable
              data={data.result}
              empty={data.status === 'succeeded' ? 'La automatización no devolvió datos.' : 'Todavía no hay resultado.'}
            />
          </section>
        </>
      )}
    </div>
  )
}
