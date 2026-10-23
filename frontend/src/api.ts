// Cliente de la API con el token de acceso en memoria (nunca en localStorage).
// El token de refresco vive en una cookie HttpOnly que JavaScript no puede leer.

let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function parse<T>(resp: Response): Promise<T> {
  const body = (await resp.json().catch(() => ({}))) as { error?: string }
  if (!resp.ok) throw new ApiError(resp.status, body.error ?? `Error ${resp.status}`)
  return body as T
}

export async function refreshSession(): Promise<boolean> {
  const resp = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' })
  if (!resp.ok) return false
  const body = (await resp.json()) as { access_token: string }
  setAccessToken(body.access_token)
  return true
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; app?: string } = {},
  retry = true,
): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  if (options.app) headers['X-App-Code'] = options.app
  const resp = await fetch(path, {
    method: options.method ?? 'GET',
    headers,
    credentials: 'same-origin',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  // Token de acceso caducado: se renueva una vez con la cookie y se reintenta
  if (resp.status === 401 && retry && accessToken && (await refreshSession())) {
    return api<T>(path, options, false)
  }
  return parse<T>(resp)
}
