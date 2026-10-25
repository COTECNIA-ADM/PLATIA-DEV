// Cliente de la API: cabeceras, query, errores, refresco único del token y SSE.
import { describe, expect, it, vi } from 'vitest'
import { ApiError, api, setAccessToken, setAppCode, stream } from './api'
import { mockApi } from '../test/utils'

describe('api()', () => {
  it('envía el token, la aplicación y el cuerpo en JSON', async () => {
    const { calls } = mockApi({ 'POST /api/opportunities': { status: 201, body: { id: 1 } } })
    setAccessToken('abc')
    setAppCode('analytics')
    await expect(api('/api/opportunities', { body: { title: 'X' } })).resolves.toEqual({ id: 1 })
    expect(calls[0].headers).toMatchObject({
      Authorization: 'Bearer abc',
      'X-App-Code': 'analytics',
      'Content-Type': 'application/json',
    })
    expect(calls[0].body).toEqual({ title: 'X' })
  })

  it('quita de la query los valores vacíos', async () => {
    const { calls } = mockApi({ 'GET /api/opportunities': { body: { items: [] } } })
    await api('/api/opportunities', { query: { q: 'nube', status: '', owner: null, page: 2, mine: undefined } })
    expect(calls[0].url).toBe('/api/opportunities?q=nube&page=2')
  })

  it('devuelve undefined en un 204', async () => {
    mockApi({ 'DELETE /api/opportunities/1': () => new Response(null, { status: 204 }) })
    await expect(api('/api/opportunities/1', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('convierte los errores en ApiError con el mensaje del backend', async () => {
    mockApi({ 'GET /api/x': { status: 409, body: { error: 'Alguien lo ha cambiado antes.' } } })
    const err = await api('/api/x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 409, message: 'Alguien lo ha cambiado antes.' })
  })

  it('explica el 429 aunque el backend no mande mensaje', async () => {
    mockApi({ 'GET /api/x': { status: 429, body: {} } })
    await expect(api('/api/x')).rejects.toThrow('Demasiadas peticiones seguidas')
  })
})

describe('renovación del token', () => {
  it('con varias peticiones caducadas a la vez, refresca una sola vez y las repite', async () => {
    let refreshes = 0
    const { calls } = mockApi({
      'POST /api/auth/refresh': () => {
        refreshes += 1
        return { body: { access_token: 'nuevo' } }
      },
      'GET /api/a': ({ headers }) => (headers.Authorization === 'Bearer nuevo' ? { body: 'a' } : { status: 401 }),
      'GET /api/b': ({ headers }) => (headers.Authorization === 'Bearer nuevo' ? { body: 'b' } : { status: 401 }),
    })
    setAccessToken('viejo')
    await expect(Promise.all([api('/api/a'), api('/api/b')])).resolves.toEqual(['a', 'b'])
    expect(refreshes).toBe(1)
    expect(calls.filter((c) => c.url === '/api/a')).toHaveLength(2)
  })

  it('si el refresco falla, avisa de que la sesión ha caducado', async () => {
    mockApi({ 'POST /api/auth/refresh': { status: 401 }, 'GET /api/a': { status: 401, body: { error: 'Token no válido.' } } })
    const expired = vi.fn()
    window.addEventListener('auth:expired', expired)
    setAccessToken('viejo')
    await expect(api('/api/a')).rejects.toMatchObject({ status: 401 })
    expect(expired).toHaveBeenCalledOnce()
    window.removeEventListener('auth:expired', expired)
  })

  it('sin token no intenta refrescar (pantalla de entrada)', async () => {
    const { calls } = mockApi({ 'POST /api/auth/login': { status: 401, body: { error: 'Credenciales no válidas.' } } })
    await expect(api('/api/auth/login', { body: {} })).rejects.toThrow('Credenciales no válidas.')
    expect(calls.map((c) => c.url)).toEqual(['/api/auth/login'])
  })
})

describe('stream()', () => {
  it('lee los eventos SSE aunque lleguen partidos y salta los mal formados', async () => {
    const chunks = ['event: delta\ndata: {"text":"Ho', 'la"}\n\n', 'data: {roto\n\n', 'event: done\r\ndata: {"ok":true}\r\n\r\n']
    mockApi({
      'POST /api/copilot/chat': () =>
        new Response(
          new ReadableStream({
            start(controller) {
              for (const c of chunks) controller.enqueue(new TextEncoder().encode(c))
              controller.close()
            },
          }),
          { headers: { 'Content-Type': 'text/event-stream' } },
        ),
    })
    const events = []
    for await (const e of stream('/api/copilot/chat', { message: 'hola' })) events.push(e)
    expect(events).toEqual([
      { event: 'delta', data: { text: 'Hola' } },
      { event: 'done', data: { ok: true } },
    ])
  })

  it('un error antes de abrir el stream se lanza como ApiError', async () => {
    mockApi({ 'POST /api/copilot/chat': { status: 403, body: { error: 'Sin acceso al copiloto.' } } })
    const run = async () => {
      for await (const _ of stream('/api/copilot/chat', {})) void _
    }
    await expect(run()).rejects.toMatchObject({ status: 403, message: 'Sin acceso al copiloto.' })
  })
})
