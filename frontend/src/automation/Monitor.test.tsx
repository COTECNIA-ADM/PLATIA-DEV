// Monitorización del portal Low-Code: salud por flujo, incidencias con filtros en la URL y resolver.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import Monitor from './Monitor'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const PAGE = { page: 1, per_page: 20, total: 1, pages: 1 }
const HEALTH = {
  days: 30,
  open_incidents: 1,
  items: [
    {
      workflow_id: 'w1',
      workflow_name: 'Aviso de oportunidad',
      runs: 4,
      succeeded: 3,
      failed: 1,
      open: 0,
      success_rate: 75,
      avg_seconds: 12.5,
      last_run_at: '2026-11-13T09:00:00Z',
      open_incidents: 1,
    },
  ],
}
const INCIDENT = {
  id: 9,
  workflow_id: 'w1',
  workflow_name: 'Aviso de oportunidad',
  execution_id: '77',
  mode: 'webhook',
  node: 'Enviar correo',
  message: 'Connection refused',
  run_id: 5,
  status: 'open',
  created_at: '2026-11-13T09:01:00Z',
  resolved_by: null,
  resolved_at: null,
  resolution_note: null,
  version: 1,
}

function routes(perms: string[]) {
  return {
    ...sessionRoutes({ automations: perms }),
    'GET /api/automation/health': { body: HEALTH },
    'GET /api/automation/incidents': { body: { items: [INCIDENT], pagination: PAGE } },
    'POST /api/automation/incidents/9/resolve': { body: { ...INCIDENT, status: 'resolved', version: 2 } },
  }
}

describe('Monitor', () => {
  it('enseña la salud por flujo como tabla', async () => {
    mockApi(routes(['read', 'build']))
    renderWithProviders(<Monitor />)
    const table = await screen.findByRole('table', { name: 'Salud por automatización' })
    expect(within(table).getByText('Aviso de oportunidad')).toBeInTheDocument()
    expect(within(table).getByText('75 %')).toBeInTheDocument()
    expect(within(table).getByText('13 s')).toBeInTheDocument()
  })

  it('filtra las incidencias por flujo y estado desde la URL', async () => {
    const { calls } = mockApi(routes(['read', 'build']))
    renderWithProviders(<Monitor />, { route: '/monitor?status=resolved&days=7' })
    await screen.findByText('Connection refused')
    expect(calls.some((c) => c.url.startsWith('/api/automation/health') && c.url.includes('days=7'))).toBe(true)
    expect(calls.some((c) => c.url.startsWith('/api/automation/incidents') && c.url.includes('status=resolved'))).toBe(true)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Ver/ }))
    await waitFor(() => expect(calls.some((c) => c.url.includes('workflow_id=w1'))).toBe(true))
    expect(screen.getByRole('button', { name: /Quitar filtro/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ejecución de PLATIA' })).toHaveAttribute('href', '/runs/5')
  })

  it('quien administra resuelve con una nota', async () => {
    const { calls } = mockApi(routes(['read', 'build', 'manage']))
    renderWithProviders(<Monitor />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Resolver' }))
    await user.type(screen.getByRole('textbox', { name: /Qué se ha hecho/ }), 'SMTP reiniciado')
    await user.click(screen.getByRole('button', { name: 'Marcar como resuelta' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const post = calls.find((c) => c.method === 'POST' && c.url === '/api/automation/incidents/9/resolve')!
    expect(post.body).toEqual({ version: 1, note: 'SMTP reiniciado' })
  })

  it('quien construye no puede resolver', async () => {
    mockApi(routes(['read', 'build']))
    renderWithProviders(<Monitor />)
    await screen.findByText('Connection refused')
    expect(screen.queryByRole('button', { name: 'Resolver' })).not.toBeInTheDocument()
  })
})
