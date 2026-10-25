// Utilidades de las pruebas: una API falsa (fetch simulado por rutas) y el árbol de
// proveedores que monta mount() en lib/bootstrap.tsx.
import type { ReactNode } from 'react'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { AuthProvider } from '../lib/auth'
import { ToastProvider } from '../components/ui'
import type { ActiveApp, User } from '../lib/types'

export type Call = { method: string; url: string; headers: Record<string, string>; body: unknown }
type Reply = { status?: number; body?: unknown; headers?: Record<string, string> } | Response
type Handler = (call: Call) => Reply | Promise<Reply>

/**
 * Sustituye fetch por una tabla de rutas: «MÉTODO /ruta» → respuesta. La ruta se compara
 * sin la query. Una petición sin ruta responde 404 y queda apuntada en `calls`.
 */
export function mockApi(routes: Record<string, Handler | Reply>) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = (init.method ?? 'GET').toUpperCase()
    const headers = { ...(init.headers as Record<string, string> | undefined) }
    let body: unknown = init.body
    if (typeof body === 'string') body = JSON.parse(body)
    const call = { method, url, headers, body }
    calls.push(call)
    const route = routes[`${method} ${url.split('?')[0]}`]
    const reply = typeof route === 'function' ? await route(call) : (route ?? { status: 404, body: { error: 'No existe' } })
    if (reply instanceof Response) return reply
    return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'Content-Type': 'application/json', ...reply.headers },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export const TEST_USER: User = {
  id: 7,
  email: 'ana@example.com',
  full_name: 'Ana Prueba',
  mfa_enabled: false,
  is_superadmin: false,
  apps: [],
}

/** Respuesta de /api/auth/me para un rol con estos permisos. */
export function meResponse(permissions: Record<string, string[]>, opts: { isAdmin?: boolean; user?: Partial<User> } = {}) {
  const active_app: ActiveApp = { code: 'operations', role: 'prueba', is_admin: opts.isAdmin ?? false, permissions }
  return { user: { ...TEST_USER, ...opts.user }, active_app, settings: { currency: 'EUR', usd_eur_rate: 0.9 } }
}

/** Rutas para una sesión ya abierta (refresco correcto y /me con esos permisos). */
export function sessionRoutes(permissions: Record<string, string[]>, opts: Parameters<typeof meResponse>[1] = {}) {
  return {
    'POST /api/auth/refresh': { body: { access_token: 'token-de-prueba' } },
    'GET /api/auth/me': { body: meResponse(permissions, opts) },
  }
}

export function renderWithProviders(ui: ReactNode, { route = '/' }: { route?: string } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <ToastProvider>
          <AuthProvider>{ui}</AuthProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
