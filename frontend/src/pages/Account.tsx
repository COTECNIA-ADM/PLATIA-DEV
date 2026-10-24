import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Badge, Field, errorMessage, useToast } from '../components/ui'

function MfaSetup({ onDone }: { onDone: () => void }) {
  const [secret, setSecret] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function start() {
    setError(null)
    try {
      setSecret((await api<{ secret: string }>('/api/auth/mfa/setup', { method: 'POST' })).secret)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      setBackupCodes((await api<{ backup_codes: string[] }>('/api/auth/mfa/enable', { body: { code: code.trim() } })).backup_codes)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  if (backupCodes) {
    return (
      <div>
        <p>Guarda estos códigos de respaldo en un sitio seguro. Cada uno sirve una vez y no se volverán a mostrar.</p>
        <pre className="codes">{backupCodes.join('\n')}</pre>
        <button className="btn btn-primary" onClick={onDone}>
          Ya los he guardado
        </button>
      </div>
    )
  }
  return (
    <div>
      {!secret ? (
        <button className="btn btn-primary" onClick={() => void start()}>
          Activar MFA
        </button>
      ) : (
        <form onSubmit={(e) => void confirm(e)} className="stack">
          <p>
            En tu app de autenticación (Google Authenticator, Microsoft Authenticator…) añade una cuenta con esta clave y
            escribe el código de 6 dígitos que muestre:
          </p>
          <pre className="codes">{secret}</pre>
          <Field label="Código">
            <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" placeholder="123456" required />
          </Field>
          <button className="btn btn-primary">Confirmar</button>
        </form>
      )}
      {error && <p className="notice notice-error">{error}</p>}
    </div>
  )
}

function PasswordChange() {
  const { logout } = useAuth()
  const toast = useToast()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await api('/api/auth/password', { body: { current_password: current, new_password: next } })
      toast('Contraseña cambiada. Vuelve a iniciar sesión.')
      await logout()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setCurrent('')
      setNext('')
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="stack">
      <Field label="Contraseña actual">
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
      </Field>
      <Field label="Contraseña nueva" hint="Mezcla mayúsculas, minúsculas y números. Se cerrarán tus otras sesiones.">
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
      </Field>
      {error && <p className="notice notice-error">{error}</p>}
      <div>
        <button className="btn">Cambiar contraseña</button>
      </div>
    </form>
  )
}

export default function Account() {
  const { user, app, reload } = useAuth()
  if (!user) return null
  return (
    <div className="page page-narrow">
      <header className="page-head">
        <div>
          <h1>Mi cuenta</h1>
          <p className="muted">{user.email}</p>
        </div>
      </header>
      <section className="card">
        <h2>Tus accesos</h2>
        <ul className="plain-list">
          {user.is_superadmin && <li>Superadministrador: acceso total</li>}
          {user.apps.map((a) => (
            <li key={a.code}>
              {a.name}: <strong>{a.role}</strong> {a.code === app?.code && <Badge tone="accent">esta aplicación</Badge>}
            </li>
          ))}
        </ul>
        <p className="muted">
          <Link to="/status">Estado de la plataforma</Link> · Las preferencias que recuerda el copiloto están en{' '}
          <Link to="/copilot?tab=memories">Copiloto → Lo que recuerdo</Link>.
        </p>
      </section>
      <section className="card">
        <h2>Verificación en dos pasos (MFA)</h2>
        {user.mfa_enabled ? <p>MFA activado ✔</p> : <MfaSetup onDone={() => void reload()} />}
      </section>
      <section className="card">
        <h2>Contraseña</h2>
        <PasswordChange />
      </section>
    </div>
  )
}
