// Reglas de reparto de oportunidades (P18): listado con criterios legibles, alta y borrado en dos pasos.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import RoutingRules from './RoutingRules'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const PERMS = { opportunities: ['read', 'write', 'manage'] }
const RULE = {
  id: 4,
  name: 'Ciber grandes',
  position: 10,
  is_enabled: true,
  sources: ['ted'],
  service_lines: ['ciber'],
  sectors: [],
  min_value_eur: '100000.00',
  max_value_eur: null,
  max_days_to_deadline: 30,
  owner_user_id: 9,
  owner_name: 'Luis Gómez',
  created_at: '2026-11-13T09:00:00Z',
  updated_at: '2026-11-13T09:00:00Z',
  version: 2,
}
const PAGE = { page: 1, per_page: 1, total: 1, pages: 1 }
const LINES = { items: [{ code: 'ciber', name: 'Ciberseguridad' }], pagination: PAGE }
const CANDIDATES = [
  { id: 9, name: 'Luis Gómez' },
  { id: 11, name: 'Marta Ruiz' },
]

describe('RoutingRules', () => {
  it('enseña cada regla con sus criterios y su responsable', async () => {
    mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/opportunities/routing-rules': { body: { items: [RULE], pagination: PAGE, candidates: CANDIDATES } },
      'GET /api/portfolio/service-lines': { body: LINES },
    })
    renderWithProviders(<RoutingRules />)
    expect(await screen.findByText('Ciber grandes')).toBeInTheDocument()
    expect(screen.getByText('Luis Gómez')).toBeInTheDocument()
    expect(screen.getByText('Activa')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/Fuente: TED · Línea: Ciberseguridad · Desde/)).toBeInTheDocument())
    expect(screen.getByText(/Plazo en 30 días o menos/)).toBeInTheDocument()
  })

  it('crea una regla con los criterios marcados', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/opportunities/routing-rules': { body: { items: [], pagination: { ...PAGE, total: 0 }, candidates: CANDIDATES } },
      'GET /api/portfolio/service-lines': { body: LINES },
      'POST /api/opportunities/routing-rules': { status: 201, body: RULE },
    })
    renderWithProviders(<RoutingRules />)
    expect(await screen.findByText('No hay reglas de reparto')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Nueva regla' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Nombre'), 'Buzón a Marta')
    await user.selectOptions(within(dialog).getByLabelText('Responsable'), '11')
    await user.click(within(dialog).getByLabelText('Buzón de pliegos'))
    await user.type(within(dialog).getByLabelText(/Sectores/), 'Sanidad, Educación')
    await user.click(within(dialog).getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/opportunities/routing-rules')).toBe(true))
    const body = calls.find((c) => c.method === 'POST' && c.url === '/api/opportunities/routing-rules')!.body as Record<string, unknown>
    expect(body).toMatchObject({
      name: 'Buzón a Marta',
      owner_user_id: 11,
      sources: ['buzon_pliegos'],
      sectors: ['Sanidad', 'Educación'],
      max_days_to_deadline: null,
      min_value_eur: null,
    })
  })

  it('pide confirmación antes de borrar', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/opportunities/routing-rules': { body: { items: [RULE], pagination: PAGE, candidates: CANDIDATES } },
      'GET /api/portfolio/service-lines': { body: LINES },
      'DELETE /api/opportunities/routing-rules/4': { status: 204 },
    })
    renderWithProviders(<RoutingRules />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Borrar' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Confirmar borrado' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
  })
})
