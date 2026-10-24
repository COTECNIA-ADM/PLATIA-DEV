// Tareas en segundo plano: colas de Celery y tareas que han agotado los reintentos.
import { useSearchParams } from 'react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime } from '../lib/format'
import type { Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Pager, Spinner, errorMessage, useToast } from '../components/ui'
import type { FailedTask, Queues } from './types'

const QUEUE_NAMES: Record<string, string> = {
  default: 'General',
  priority: 'Prioritaria',
  ai: 'IA',
  documents: 'Documentos',
  sync: 'Sincronización',
  crm: 'CRM',
  automation: 'Automatizaciones',
}

export default function Tasks() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const reviewed = params.get('reviewed') ?? 'false'
  const page = Number(params.get('page') ?? 1)
  const queues = useQuery({ queryKey: ['admin', 'queues'], queryFn: () => api<Queues>('/api/admin/tasks/queues'), refetchInterval: 15_000 })
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['admin', 'failed', reviewed, page],
    queryFn: () => api<Page<FailedTask>>('/api/admin/tasks/failed', { query: { reviewed: reviewed === 'all' ? '' : reviewed, page } }),
    placeholderData: keepPreviousData,
  })
  const act = useMutation({
    mutationFn: ({ id, what }: { id: number; what: 'retry' | 'review' }) => api<FailedTask>(`/api/admin/tasks/failed/${id}/${what}`, { method: 'POST' }),
    onSuccess: (_t, v) => {
      toast(v.what === 'retry' ? 'Tarea reencolada.' : 'Marcada como revisada.')
      void qc.invalidateQueries({ queryKey: ['admin', 'failed'] })
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })
  const canWrite = can('tasks', 'write')

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Tareas</h1>
          <p className="muted">Trabajo en segundo plano: análisis, indexado, avisos. Aquí quedan las que fallaron tras reintentarlo.</p>
        </div>
      </header>
      <section className="card">
        <h2>Pendientes por cola</h2>
        {queues.isLoading && <Spinner />}
        {queues.error && <ErrorBox error={queues.error} />}
        {queues.data && (
          <div className="stats stats-compact">
            {queues.data.known_queues.map((q) => {
              const n = queues.data.queues[q]
              return (
                <div key={q} className="stat">
                  <span className="stat-label">{QUEUE_NAMES[q] ?? q}</span>
                  <span className="stat-value">{n ?? '—'}</span>
                </div>
              )
            })}
          </div>
        )}
        <p className="field-hint">Se actualiza cada 15 segundos.</p>
      </section>

      <div className="toolbar section-gap">
        <h2 className="grow">Tareas fallidas</h2>
        <select value={reviewed} onChange={(e) => setParams({ reviewed: e.target.value })} aria-label="Revisión">
          <option value="false">Sin revisar</option>
          <option value="true">Revisadas</option>
          <option value="all">Todas</option>
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title={reviewed === 'false' ? 'Nada pendiente de revisar' : 'No hay tareas'} />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table table-compact">
            <thead>
              <tr>
                <th>Tarea</th>
                <th>Error</th>
                <th>Falló</th>
                <th>Estado</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((t) => (
                <tr key={t.id}>
                  <td>
                    <code>{t.task_name}</code>
                    <div className="row-sub">
                      {t.queue ?? '—'} · {t.retries} reintentos
                      {t.args && t.args.length > 0 && <> · args {JSON.stringify(t.args).slice(0, 60)}</>}
                    </div>
                  </td>
                  <td className="cell-wrap">
                    <strong>{t.error_type}</strong>
                    <div className="row-sub">{t.error_message}</div>
                  </td>
                  <td className="nowrap">{fmtDateTime(t.failed_at)}</td>
                  <td>
                    {t.requeued_task_id ? <Badge tone="info">Reencolada</Badge> : t.reviewed ? <Badge>Revisada</Badge> : <Badge tone="warning">Pendiente</Badge>}
                  </td>
                  <td className="num nowrap">
                    {canWrite && !t.reviewed && (
                      <span className="btn-row">
                        <button className="btn btn-small" disabled={act.isPending} onClick={() => act.mutate({ id: t.id, what: 'retry' })}>
                          Reintentar
                        </button>
                        <button className="btn btn-small btn-ghost" disabled={act.isPending} onClick={() => act.mutate({ id: t.id, what: 'review' })}>
                          Revisada
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
      {data && <Pager pagination={data.pagination} onPage={(p) => setParams({ reviewed, page: String(p) })} />}
    </div>
  )
}
