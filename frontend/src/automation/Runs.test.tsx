// Ejecuciones del portal Low-Code: lanzar desde el catálogo, lista con filtros y detalle.
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import Catalog from './Catalog'
import RunDetail from './RunDetail'
import Runs from './Runs'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const PAGE = { page: 1, per_page: 20, total: 1, pages: 1 }
const OK = { enabled: true, reachable: true, problem: null }
const RUN = {
  id: 7,
  workflow_id: 'w1',
  workflow_name: 'Aviso de oportunidad',
  status: 'succeeded',
  error: null,
  requested_by: 1,
  created_at: '2026-11-11T10:00:00Z',
  started_at: '2026-11-11T10:00:01Z',
  finished_at: '2026-11-11T10:00:05Z',
}
const CATALOG = {
  items: [
    { id: 'w1', name: 'Aviso de oportunidad', active: true, launchable: true, tags: ['platia'], updated_at: null },
    { id: 'w2', name: 'Solo manual', active: true, launchable: false, tags: ['platia'], updated_at: null },
  ],
  pagination: { ...PAGE, total: 2 },
  source: OK,
}

describe('Lanzar desde el catálogo', () => {
  it('lanza con los datos escritos y abre la ejecución', async () => {
    const { calls } = mockApi({
      ...sessionRoutes({ automations: ['read', 'run'] }),
      'GET /api/automation/catalog': { body: CATALOG },
      'POST /api/automation/runs': { status: 202, body: { ...RUN, status: 'queued', input: {}, result: null } },
    })
    renderWithProviders(
      <Routes>
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/runs/:id" element={<p>Detalle abierto</p>} />
      </Routes>,
      { route: '/catalog' },
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Lanzar' }))
    expect(screen.getByText('No se puede lanzar')).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: 'Dato 1' }), 'cliente')
    await user.type(screen.getByRole('textbox', { name: 'Valor 1' }), 'Ayto. de Ejemplo')
    await user.click(screen.getAllByRole('button', { name: 'Lanzar' }).at(-1)!)
    expect(await screen.findByText('Detalle abierto')).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.url === '/api/automation/runs')!
    expect(post.body).toEqual({ workflow_id: 'w1', input: { cliente: 'Ayto. de Ejemplo' } })
  })

  it('avisa de un nombre de dato no válido sin llamar a la API', async () => {
    const { calls } = mockApi({
      ...sessionRoutes({ automations: ['read', 'run'] }),
      'GET /api/automation/catalog': { body: CATALOG },
    })
    renderWithProviders(<Catalog />, { route: '/catalog' })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Lanzar' }))
    await user.type(screen.getByRole('textbox', { name: 'Dato 1' }), 'mal nombre')
    expect(screen.getByRole('alert')).toHaveTextContent('no vale como nombre de dato')
    expect(calls.some((c) => c.url === '/api/automation/runs')).toBe(false)
  })

  it('sin permiso para lanzar no enseña el botón', async () => {
    mockApi({ ...sessionRoutes({ automations: ['read'] }), 'GET /api/automation/catalog': { body: CATALOG } })
    renderWithProviders(<Catalog />, { route: '/catalog' })
    expect(await screen.findByText('Aviso de oportunidad')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Lanzar' })).not.toBeInTheDocument()
  })
})

describe('Runs', () => {
  it('lista las ejecuciones y pasa el filtro de la URL a la API', async () => {
    const { calls } = mockApi({
      ...sessionRoutes({ automations: ['read', 'run'] }),
      'GET /api/automation/runs': { body: { items: [RUN], pagination: PAGE } },
    })
    renderWithProviders(<Runs />, { route: '/runs?status=succeeded' })
    expect(await screen.findByRole('link', { name: 'Aviso de oportunidad' })).toHaveAttribute('href', '/runs/7')
    expect(screen.getByText('Terminada', { selector: 'span' })).toBeInTheDocument()
    expect(calls.find((c) => c.url.startsWith('/api/automation/runs'))!.url).toContain('status=succeeded')
    expect(screen.queryByRole('checkbox', { name: 'Solo las mías' })).not.toBeInTheDocument()
  })

  it('quien administra puede quedarse solo con las suyas', async () => {
    const { calls } = mockApi({
      ...sessionRoutes({ automations: ['read', 'run', 'manage'] }),
      'GET /api/automation/runs': { body: { items: [], pagination: { ...PAGE, total: 0, pages: 0 } } },
    })
    renderWithProviders(<Runs />, { route: '/runs' })
    expect(await screen.findByText('No hay ejecuciones')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('checkbox', { name: 'Solo las mías' }))
    await waitFor(() => expect(calls.some((c) => c.url.includes('mine=true'))).toBe(true))
  })
})

describe('RunDetail', () => {
  function renderDetail() {
    return renderWithProviders(
      <Routes>
        <Route path="/runs/:id" element={<RunDetail />} />
      </Routes>,
      { route: '/runs/7' },
    )
  }

  it('enseña la entrada y el resultado', async () => {
    mockApi({
      ...sessionRoutes({ automations: ['read'] }),
      'GET /api/automation/runs/7': {
        body: { ...RUN, input: { cliente: 'Ayto. de Ejemplo' }, result: { enviados: 3, detalle: { a: 1 } } },
      },
    })
    renderDetail()
    expect(await screen.findByRole('heading', { name: 'Aviso de oportunidad' })).toBeInTheDocument()
    expect(screen.getByText('Ayto. de Ejemplo')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('{"a":1}')).toBeInTheDocument()
  })

  it('explica una ejecución fallida y una en marcha', async () => {
    mockApi({
      ...sessionRoutes({ automations: ['read'] }),
      'GET /api/automation/runs/7': {
        body: { ...RUN, status: 'failed', error: 'n8n no ha respondido a tiempo.', input: {}, result: null },
      },
    })
    renderDetail()
    expect(await screen.findByRole('alert')).toHaveTextContent('n8n no ha respondido a tiempo.')
    expect(screen.getByText('Fallida')).toBeInTheDocument()
    expect(screen.getByText('Todavía no hay resultado.')).toBeInTheDocument()
  })
})
