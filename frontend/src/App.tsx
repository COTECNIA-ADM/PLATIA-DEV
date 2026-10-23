import { useEffect, useState } from 'react'

type Status = 'healthy' | 'degraded' | 'unhealthy'

type ServiceStatus = {
  name: string
  status: Status
  detail?: string
  error?: string
}

type HealthResponse = {
  status: Status
  services: ServiceStatus[]
}

const STATUS_TEXT: Record<Status, string> = {
  healthy: 'OK',
  degraded: 'Aviso',
  unhealthy: 'Caído',
}

const LABELS: Record<string, string> = {
  database_platform: 'MySQL · platform_core',
  database_operations: 'MySQL · operations_db',
  database_analytics: 'MySQL · analytics_db',
  redis: 'Redis',
  qdrant: 'Qdrant',
  ai_service: 'Servicio de IA',
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setError(null)
    try {
      const resp = await fetch('/api/health/full')
      setHealth((await resp.json()) as HealthResponse)
    } catch {
      setError('No se pudo contactar con el backend.')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <main>
      <h1>PLATIA</h1>
      <p className="subtitle">Estado del núcleo de la plataforma</p>
      {error && <p className="error">{error}</p>}
      {health && (
        <ul className="services">
          {health.services.map((s) => (
            <li key={s.name} className={s.status}>
              <span>
                {LABELS[s.name] ?? s.name}
                {s.detail && <small>{s.detail}</small>}
              </span>
              <strong>{STATUS_TEXT[s.status]}</strong>
            </li>
          ))}
        </ul>
      )}
      <button onClick={() => void load()}>Comprobar de nuevo</button>
    </main>
  )
}
