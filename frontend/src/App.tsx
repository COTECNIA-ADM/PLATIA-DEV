import { useCallback, useEffect, useState } from 'react'
import { api, refreshSession, setAccessToken } from './api'
import Login from './Login'
import MfaSetup from './MfaSetup'
import type { HealthResponse, Status, User } from './types'

const STATUS_TEXT: Record<Status, string> = { healthy: 'OK', degraded: 'Aviso', unhealthy: 'Caído' }

const LABELS: Record<string, string> = {
  database_platform: 'MySQL · platform_core',
  database_operations: 'MySQL · operations_db',
  database_analytics: 'MySQL · analytics_db',
  redis: 'Redis',
  qdrant: 'Qdrant',
  ai_service: 'Servicio de IA',
}

// El estado completo de la infraestructura solo lo ve quien tiene acceso a la app admin
function canSeeFullHealth(user: User | null) {
  return !!user && user.apps.some((a) => a.code === 'admin')
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showMfa, setShowMfa] = useState(false)

  const loadHealth = useCallback(async (current: User | null) => {
    setError(null)
    try {
      if (canSeeFullHealth(current)) {
        setHealth(await api<HealthResponse>('/api/health/full', { app: 'admin' }))
      } else {
        const resp = await fetch('/api/health')
        setHealth((await resp.json()) as HealthResponse)
      }
    } catch {
      setError('No se pudo contactar con el backend.')
    }
  }, [])

  const loadMe = useCallback(async () => {
    const me = await api<{ user: User }>('/api/auth/me')
    setUser(me.user)
    return me.user
  }, [])

  // Al abrir la página se intenta recuperar la sesión con la cookie de refresco
  useEffect(() => {
    void (async () => {
      let current: User | null = null
      if (await refreshSession()) {
        current = await loadMe().catch(() => null)
      }
      setCheckingSession(false)
      await loadHealth(current)
    })()
  }, [loadHealth, loadMe])

  async function logout() {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
    setAccessToken(null)
    setUser(null)
    await loadHealth(null)
  }

  return (
    <main>
      <header>
        <div>
          <h1>PLATIA</h1>
          <p className="subtitle">Estado de la plataforma</p>
        </div>
        {user && (
          <div className="session">
            <span>{user.full_name}</span>
            <button className="link" onClick={() => void logout()}>
              Cerrar sesión
            </button>
          </div>
        )}
      </header>

      {!checkingSession && !user && (
        <Login
          onLogin={(u) => {
            setUser(u)
            void loadHealth(u)
          }}
        />
      )}

      {user && (
        <section className="card">
          <h2>Tus accesos</h2>
          <ul className="apps">
            {user.is_superadmin && <li>Superadministrador: acceso total</li>}
            {user.apps.map((a) => (
              <li key={a.code}>
                {a.name}: <strong>{a.role}</strong>
              </li>
            ))}
          </ul>
          {user.mfa_enabled ? (
            <p>MFA activado ✔</p>
          ) : showMfa ? (
            <MfaSetup
              onDone={() => {
                setShowMfa(false)
                void loadMe()
              }}
            />
          ) : (
            <p className="warning">
              Tu cuenta no tiene MFA. <button className="link" onClick={() => setShowMfa(true)}>Activarlo</button>
            </p>
          )}
        </section>
      )}

      <h2>{canSeeFullHealth(user) ? 'Estado completo' : 'Estado básico'}</h2>
      {error && <p className="error">{error}</p>}
      {health && (
        <ul className="services">
          {health.services.map((s) => (
            <li key={s.name} className={s.status}>
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
      <button onClick={() => void loadHealth(user)}>Comprobar de nuevo</button>
    </main>
  )
}
