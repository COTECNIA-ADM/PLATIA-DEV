// Catálogo del portal Low-Code: fichas publicadas, filtros en la URL y formulario para lanzar.
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import Catalog from './Catalog'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const PERMS = { automations: ['read', 'run'] }
const PAGE = { page: 1, per_page: 20, total: 2, pages: 1 }
const OK = { enabled: true, reachable: true, problem: null }
const AVISO = {
  id: 1,
  title: 'Aviso de oportunidad',
  description: 'Avisa por correo de una licitación.',
  category: 'ciclo_comercial',
  fields: [
    { name: 'destinatario', label: 'Correo', type: 'text', required: true },
    { name: 'importe', label: 'Importe', type: 'number' },
    { name: 'plazo', label: 'Plazo', type: 'date' },
    { name: 'canal', label: 'Canal', type: 'select', options: ['correo', 'teams'] },
    { name: 'urgente', label: 'Urgente', type: 'boolean' },
  ],
  active: true,
  launchable: true,
  updated_at: null,
}
const PAUSADA = { ...AVISO, id: 2, title: 'Buzón de pliegos', description: null, fields: [], active: false, launchable: false }
const CATALOG = { items: [AVISO, PAUSADA], pagination: PAGE, source: OK }

describe('Catalog', () => {
  it('muestra las automatizaciones publicadas con su estado', async () => {
    mockApi({ ...sessionRoutes(PERMS), 'GET /api/automation/catalog': { body: CATALOG } })
    renderWithProviders(<Catalog />)
    expect(await screen.findByText('Aviso de oportunidad')).toBeInTheDocument()
    expect(screen.getByText('Avisa por correo de una licitación.')).toBeInTheDocument()
    expect(screen.getByText('Activa')).toBeInTheDocument()
    expect(screen.getByText('En pausa', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByText('No disponible')).toBeInTheDocument()
  })

  it('pasa los filtros de la URL a la API', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/automation/catalog': { body: { items: [], pagination: { ...PAGE, total: 0, pages: 0 }, source: OK } },
    })
    renderWithProviders(<Catalog />, { route: '/catalog?q=pliego&active=true&category=back_office' })
    expect(await screen.findByText('No hay automatizaciones publicadas')).toBeInTheDocument()
    const call = calls.find((c) => c.url.startsWith('/api/automation/catalog'))!
    expect(call.url).toContain('q=pliego')
    expect(call.url).toContain('active=true')
    expect(call.url).toContain('category=back_office')
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
  })
})

describe('Lanzar desde el catálogo', () => {
  it('rellena el formulario de la ficha y abre la ejecución', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/automation/catalog': { body: CATALOG },
      'POST /api/automation/runs': { status: 202, body: { id: 7, status: 'queued', input: {}, result: null } },
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
    await user.type(screen.getByRole('textbox', { name: 'Correo *' }), 'ana@example.com')
    await user.type(screen.getByRole('spinbutton', { name: 'Importe' }), '1200')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Canal' }), 'teams')
    await user.click(screen.getByRole('checkbox', { name: 'Urgente' }))
    await user.click(screen.getAllByRole('button', { name: 'Lanzar' }).at(-1)!)
    expect(await screen.findByText('Detalle abierto')).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.url === '/api/automation/runs')!
    expect(post.body).toEqual({
      entry_id: 1,
      input: { destinatario: 'ana@example.com', importe: 1200, canal: 'teams', urgente: true },
    })
  })

  it('enseña el error de la API', async () => {
    mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/automation/catalog': { body: { ...CATALOG, items: [{ ...AVISO, fields: [] }] } },
      'POST /api/automation/runs': { status: 422, body: { error: 'El flujo está desactivado en n8n.' } },
    })
    renderWithProviders(<Catalog />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Lanzar' }))
    expect(screen.getByText('Esta automatización no necesita datos.')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Lanzar' }).at(-1)!)
    expect(await screen.findByRole('alert')).toHaveTextContent('El flujo está desactivado en n8n.')
  })

  it('sin permiso para lanzar no enseña el botón', async () => {
    mockApi({ ...sessionRoutes({ automations: ['read'] }), 'GET /api/automation/catalog': { body: CATALOG } })
    renderWithProviders(<Catalog />)
    expect(await screen.findByText('Aviso de oportunidad')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Lanzar' })).not.toBeInTheDocument()
  })
})
