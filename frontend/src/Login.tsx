import { FormEvent, useState } from 'react'
import { api, setAccessToken } from './api'
import type { User } from './types'

type LoginResponse = { access_token?: string; user?: User; mfa_required?: boolean; mfa_token?: string }

export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function finish(resp: LoginResponse) {
    if (resp.access_token && resp.user) {
      setAccessToken(resp.access_token)
      onLogin(resp.user)
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (mfaToken) {
        finish(await api<LoginResponse>('/api/auth/mfa/verify', { method: 'POST', body: { mfa_token: mfaToken, code } }))
      } else {
        const resp = await api<LoginResponse>('/api/auth/login', { method: 'POST', body: { email, password } })
        if (resp.mfa_required && resp.mfa_token) setMfaToken(resp.mfa_token)
        else finish(resp)
      }
    } catch (err) {
      setError((err as Error).message)
      if (mfaToken) setCode('')
    } finally {
      setBusy(false)
      setPassword('')
    }
  }

  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h2>Iniciar sesión</h2>
      {mfaToken ? (
        <label>
          Código de tu app de autenticación (o un código de respaldo)
          <input value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" autoFocus required />
        </label>
      ) : (
        <>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
          </label>
          <label>
            Contraseña
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </label>
        </>
      )}
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>
        {mfaToken ? 'Verificar' : 'Entrar'}
      </button>
    </form>
  )
}
