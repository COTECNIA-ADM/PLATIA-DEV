import { useState } from 'react'
import { api } from './api'

export default function MfaSetup({ onDone }: { onDone: () => void }) {
  const [secret, setSecret] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function start() {
    setError(null)
    try {
      setSecret((await api<{ secret: string }>('/api/auth/mfa/setup', { method: 'POST' })).secret)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function confirm() {
    setError(null)
    try {
      const resp = await api<{ backup_codes: string[] }>('/api/auth/mfa/enable', { method: 'POST', body: { code } })
      setBackupCodes(resp.backup_codes)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  if (backupCodes) {
    return (
      <div className="card">
        <h3>MFA activado</h3>
        <p>Guarda estos códigos de respaldo en un sitio seguro. Cada uno sirve una vez y no se volverán a mostrar.</p>
        <pre className="codes">{backupCodes.join('\n')}</pre>
        <button onClick={onDone}>Ya los he guardado</button>
      </div>
    )
  }

  return (
    <div className="card">
      <h3>Activar MFA</h3>
      {!secret ? (
        <button onClick={() => void start()}>Generar clave</button>
      ) : (
        <>
          <p>
            En tu app de autenticación (Google Authenticator, Microsoft Authenticator…) añade una cuenta
            con esta clave y escribe el código de 6 dígitos que muestre:
          </p>
          <pre className="codes">{secret}</pre>
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" />
          <button onClick={() => void confirm()}>Confirmar</button>
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}
