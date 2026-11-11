// Catálogo del portal Low-Code: lista, filtros en la URL y aviso cuando n8n no responde.
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import Catalog from './Catalog'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const PERMS = { automations: ['read', 'run'] }
const PAGE = { page: 1, per_page: 20, total: 2, pages: 1 }
const OK = { enabled: true, reachable: true, problem: null }

describe('Catalog', () => {
  it('muestra las automatizaciones publicadas con su estado', async () => {
    mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/automation/catalog': {
        body: {
          items: [
            { id: 'b2', name: 'Aviso de oportunidad', active: true, launchable: true, tags: ['comercial', 'platia'], updated_at: null },
            { id: 'a1', name: 'Buzón de pliegos', active: false, tags: [], updated_at: null },
          ],
          pagination: PAGE,
          source: OK,
        },
      },
    })
    renderWithProviders(<Catalog />)
    expect(await screen.findByText('Aviso de oportunidad')).toBeInTheDocument()
    expect(screen.getByText('Activa')).toBeInTheDocument()
    expect(screen.getByText('En pausa', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByText('comercial, platia')).toBeInTheDocument()
  })

  it('pasa los filtros de la URL a la API', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/automation/catalog': { body: { items: [], pagination: { ...PAGE, total: 0, pages: 0 }, source: OK } },
    })
    renderWithProviders(<Catalog />, { route: '/catalog?q=pliego&active=true' })
    expect(await screen.findByText('No hay automatizaciones publicadas')).toBeInTheDocument()
    const call = calls.find((c) => c.url.startsWith('/api/automation/catalog'))!
    expect(call.url).toContain('q=pliego')
    expect(call.url).toContain('active=true')
    expect(screen.getByRole('searchbox', { name: 'Buscar' })).toHaveValue('pliego')

    const user = userEvent.setup()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Estado' }), 'false')
    await waitFor(() => expect(calls.some((c) => c.url.includes('active=false'))).toBe(true))
  })

  it('explica por qué no hay catálogo cuando n8n no responde', async () => {
    mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/automation/catalog': {
        body: {
          items: [],
          pagination: { ...PAGE, total: 0, pages: 0 },
          source: { enabled: true, reachable: false, problem: 'No se puede conectar con n8n.' },
        },
      },
    })
    renderWithProviders(<Catalog />)
    expect(await screen.findByText('No se puede conectar con n8n.')).toHaveAttribute('role', 'status')
    expect(screen.queryByText('No hay automatizaciones publicadas')).not.toBeInTheDocument()
  })
})
