import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { HealthResponse, Status } from '../lib/types'
import { ErrorBox, Spinner } from '../components/ui'

const STATUS_TEXT: Record<Status, string> = { healthy: 'OK', degraded: 'Aviso', unhealthy: 'Caído' }
const LABELS: Record<string, string> = {
  database_platform: 'MySQL · platform_core',
  database_operations: 'MySQL · operations_db',
  database_analytics: 'MySQL · analytics_db',
  redis: 'Redis',
  qdrant: 'Qdrant',
  meilisearch: 'Meilisearch',
  ai_service: 'Servicio de IA',
  workers: 'Workers de Celery',
}

export default function Health() {
  const { user } = useAuth()
  // El estado completo solo lo ve quien tiene acceso a la aplicación de administración
  const full = !!user?.apps.some((a) => a.code === 'admin')
  const { data, error, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['health', full],
    queryFn: async () => {
      if (full) return api<HealthResponse>('/api/health/full', { app: 'admin' })
      const resp = await fetch('/api/health')
      return (await resp.json()) as HealthResponse
    },
  })

  return (
    <div className="page page-narrow">
      <header className="page-head">
        <div>
          <h1>Estado de la plataforma</h1>
          <p className="muted">{full ? 'Estado completo de los servicios' : 'Estado básico'}</p>
        </div>
        <button className="btn" onClick={() => void refetch()} disabled={isFetching}>
          Comprobar de nuevo
        </button>
      </header>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} />}
      {data && (
        <ul className="services">
          {data.services.map((s) => (
            <li key={s.name} className={`service service-${s.status}`}>
              <span>
                {LABELS[s.name] ?? s.name}
                {s.detail && <small>{s.detail}</small>}
                {s.error && <small>Error: {s.error}. Revisa: docker compose logs</small>}
              </span>
              <strong>{STATUS_TEXT[s.status]}</strong>
            </li>
          ))}
        </ul>
      )}
      {!user && (
        <p>
          <Link to="/">Volver a iniciar sesión</Link>
        </p>
      )}
    </div>
  )
}
