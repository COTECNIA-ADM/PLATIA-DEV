import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { errorMessage } from '../components/ui'

type LoginResponse = { access_token?: string; mfa_required?: boolean; mfa_token?: string }

export default function Login() {
  const { signedIn, expired } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const resp = mfaToken
        ? await api<LoginResponse>('/api/auth/mfa/verify', { body: { mfa_token: mfaToken, code: code.trim() } })
        : await api<LoginResponse>('/api/auth/login', { body: { email, password } })
      if (resp.mfa_required && resp.mfa_token) setMfaToken(resp.mfa_token)
      else if (resp.access_token) await signedIn(resp.access_token)
    } catch (err) {
      setError(errorMessage(err))
      if (mfaToken) setCode('')
    } finally {
      setBusy(false)
      setPassword('') // la contraseña no se queda en memoria
    }
  }

  return (
    <div className="login">
      <form className="login-card" onSubmit={(e) => void submit(e)}>
        <div className="brand brand-large">
          <span className="brand-mark">P</span>
          <span>PLATIA</span>
        </div>
        <p className="muted">Oportunidades, documentos y propuestas con IA.</p>
        {expired && !error && <p className="notice notice-warning">Tu sesión ha caducado. Vuelve a entrar.</p>}
        {mfaToken ? (
          <label className="field">
            <span className="field-label">Código de tu app de autenticación (o uno de respaldo)</span>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="one-time-code"
              inputMode="numeric"
              autoFocus
              required
            />
          </label>
        ) : (
          <>
            <label className="field">
              <span className="field-label">Email</span>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" autoFocus required />
            </label>
            <label className="field">
              <span className="field-label">Contraseña</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
          </>
        )}
        {error && <p className="notice notice-error">{error}</p>}
        <button className="btn btn-primary btn-block" type="submit" disabled={busy}>
          {busy ? 'Comprobando…' : mfaToken ? 'Verificar' : 'Entrar'}
        </button>
        {mfaToken && (
          <button type="button" className="btn btn-ghost btn-block" onClick={() => setMfaToken(null)}>
            Volver
          </button>
        )}
        <Link to="/status" className="login-status">
          Estado de la plataforma
        </Link>
      </form>
    </div>
  )
}
