import { Link, useNavigate, useSearchParams } from 'react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtRelative } from '../lib/format'
import type { Alert, Notification, Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Pager, Spinner, errorMessage, useToast } from '../components/ui'

const TYPES: Record<string, string> = {
  NEW_OPPORTUNITY: 'Oportunidad nueva',
  OPPORTUNITY_MATCH: 'Encaja contigo',
  DEAL_STALLED: 'Sin avances',
  ACCOUNT_RISK: 'Riesgo de cliente',
  REPORT_READY: 'Listo',
  SYSTEM: 'Sistema',
}

function Alerts() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['alerts', 'open'],
    queryFn: () => api<Page<Alert>>('/api/alerts', { query: { open: 'true', per_page: 20 } }),
    enabled: can('alerts', 'read'),
  })
  const resolve = useMutation({
    mutationFn: (id: number) => api(`/api/alerts/${id}/resolve`, { method: 'POST' }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['alerts'] }),
    onError: (err) => toast(errorMessage(err), 'danger'),
  })
  if (!data?.items.length) return null
  return (
    <section className="card">
      <h2>Alertas abiertas</h2>
      <ul className="plain-list">
        {data.items.map((a) => (
          <li key={a.id} className="row-between">
            <span>
              {a.opportunity_id ? <Link to={`/opportunities/${a.opportunity_id}`}>{a.message}</Link> : a.message}
              <div className="row-sub">{fmtRelative(a.created_at)}</div>
            </span>
            {can('alerts', 'write') && (
              <button className="btn btn-small" onClick={() => resolve.mutate(a.id)}>
                Resolver
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function Notifications() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const unread = params.get('unread') === 'true'
  const page = Number(params.get('page') ?? 1)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['notifications', 'list', unread, page],
    queryFn: () => api<Page<Notification>>('/api/notifications', { query: { unread: unread ? 'true' : undefined, page } }),
    placeholderData: keepPreviousData,
  })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['notifications'] })
    void queryClient.invalidateQueries({ queryKey: ['unread-count'] })
  }
  const read = useMutation({ mutationFn: (id: number) => api(`/api/notifications/${id}/read`, { method: 'POST' }), onSuccess: refresh })
  const readAll = useMutation({ mutationFn: () => api('/api/notifications/read-all', { method: 'POST' }), onSuccess: refresh })

  function open(n: Notification) {
    if (!n.read_at) read.mutate(n.id)
    if (n.link) navigate(n.link)
  }

  return (
    <div className="page page-narrow">
      <header className="page-head">
        <div>
          <h1>Avisos</h1>
        </div>
        <div className="btn-row">
          <button className={`chip${unread ? ' chip-on' : ''}`} onClick={() => setParams(unread ? {} : { unread: 'true' })}>
            Solo sin leer
          </button>
          <button className="btn" onClick={() => readAll.mutate()} disabled={readAll.isPending}>
            Marcar todo como leído
          </button>
        </div>
      </header>
      <Alerts />
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay avisos" />}
      <ul className="notification-list">
        {data?.items.map((n) => (
          <li key={n.id} className={n.read_at ? 'read' : 'unread'}>
            <button className="notification" onClick={() => open(n)}>
              <span className="row-between">
                <strong>{n.title}</strong>
                <span className="muted">{fmtRelative(n.created_at)}</span>
              </span>
              {n.body && <span>{n.body}</span>}
              <span>
                <Badge tone={n.priority === 'high' || n.priority === 'urgent' ? 'danger' : 'neutral'}>{TYPES[n.type] ?? n.type}</Badge>
              </span>
            </button>
          </li>
        ))}
      </ul>
      {data && <Pager pagination={data.pagination} onPage={(p) => setParams({ ...(unread ? { unread: 'true' } : {}), page: String(p) })} />}
    </div>
  )
}
