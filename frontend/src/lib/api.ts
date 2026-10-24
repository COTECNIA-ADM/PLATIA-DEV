// Cliente de la API (Capítulo 17).
// - El token de acceso vive en memoria, nunca en localStorage: un script inyectado no
//   puede leerlo de ahí. El de refresco va en una cookie HttpOnly que JavaScript no ve.
// - Si varias peticiones reciben 401 a la vez, se hace un solo refresco y todas esperan.
// - Las respuestas en streaming (SSE) se leen con fetch + ReadableStream, porque
//   EventSource no permite POST ni la cabecera Authorization.

let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null
export const APP_CODE = 'operations'

export function setAccessToken(token: string | null) {
  accessToken = token
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body: Record<string, unknown> = {},
  ) {
    super(message)
  }
}

/** Avisa a la app de que la sesión se ha perdido (el refresco ha fallado). */
function sessionExpired() {
  accessToken = null
  window.dispatchEvent(new CustomEvent('auth:expired'))
}

export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const resp = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' })
      if (!resp.ok) return false
      const body = (await resp.json()) as { access_token: string }
      accessToken = body.access_token
      return true
    } catch {
      return false
    } finally {
      // Se libera en la siguiente vuelta para que las peticiones que esperan lo vean resuelto
      setTimeout(() => (refreshing = null), 0)
    }
  })()
  return refreshing
}

type Options = {
  method?: string
  body?: unknown
  form?: FormData
  app?: string
  query?: Record<string, string | number | boolean | null | undefined>
  signal?: AbortSignal
}

function buildUrl(path: string, query?: Options['query']) {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

async function send(path: string, options: Options): Promise<Response> {
  const headers: Record<string, string> = { 'X-App-Code': options.app ?? APP_CODE }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  return fetch(buildUrl(path, options.query), {
    method: options.method ?? (options.body !== undefined || options.form ? 'POST' : 'GET'),
    headers,
    credentials: 'same-origin',
    signal: options.signal,
    body: options.form ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
  })
}

/** Hace la petición y, si el token ha caducado, lo renueva una vez y la repite. */
async function request(path: string, options: Options): Promise<Response> {
  let resp = await send(path, options)
  if (resp.status === 401 && accessToken !== null) {
    if (await refreshSession()) resp = await send(path, options)
    else sessionExpired()
  }
  return resp
}

async function fail(resp: Response): Promise<never> {
  const body = (await resp.json().catch(() => ({}))) as Record<string, unknown>
  const message =
    typeof body.error === 'string'
      ? body.error
      : resp.status === 429
        ? 'Demasiadas peticiones seguidas. Espera un momento.'
        : `Error ${resp.status}`
  throw new ApiError(resp.status, message, body)
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const resp = await request(path, options)
  if (!resp.ok) return fail(resp)
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

/** Descarga un fichero protegido (con el token) y lo guarda con su nombre. */
export async function download(path: string, fallbackName = 'descarga') {
  const resp = await request(path, {})
  if (!resp.ok) return fail(resp)
  const disposition = resp.headers.get('Content-Disposition') ?? ''
  const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disposition)
  const name = match ? decodeURIComponent(match[1] ?? match[2]) : fallbackName
  const url = URL.createObjectURL(await resp.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export type StreamEvent = { event: string; data: Record<string, unknown> }

/**
 * Lee una respuesta SSE de un POST. Devuelve los eventos según llegan.
 * Un error antes de abrir el stream (422, 403…) se lanza como ApiError.
 */
export async function* stream(path: string, body: unknown, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const resp = await request(path, { method: 'POST', body, signal })
  if (!resp.ok) await fail(resp)
  if (!resp.body) return
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let event = 'message'
  let data: string[] = []
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let newline: number
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline).replace(/\r$/, '')
      buffer = buffer.slice(newline + 1)
      if (line === '') {
        if (data.length) {
          try {
            yield { event, data: JSON.parse(data.join('\n')) as Record<string, unknown> }
          } catch {
            // Un evento mal formado no rompe la conversación
          }
        }
        event = 'message'
        data = []
      } else if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        data.push(line.slice(5).trimStart())
      }
    }
  }
}
