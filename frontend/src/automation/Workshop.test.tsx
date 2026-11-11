// Taller del portal Low-Code: crear una ficha, editar sus campos, comprobar, enviar y publicar.
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import EntryDetail from './EntryDetail'
import Workshop from './Workshop'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const BUILD = { automations: ['read', 'run', 'build'] }
const MANAGE = { automations: ['read', 'run', 'build', 'manage'] }
const OK = { enabled: true, reachable: true, problem: null }
const ENTRY = {
  id: 3,
  workflow_id: 'w1',
  title: 'Aviso de oportunidad',
  description: null,
  category: 'ciclo_comercial',
  fields: [],
  status: 'draft',
  checks: [],
  checked_at: null,
  submitted_at: null,
  reviewed_at: null,
  review_note: null,
  published_at: null,
  created_at: '2026-11-11T10:00:00Z',
  version: 1,
  input_names: ['cliente'],
}

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/workshop/:id" element={<EntryDetail />} />
    </Routes>,
    { route: '/workshop/3' },
  )
}

describe('Workshop', () => {
  it('crea una ficha a partir de un flujo libre de n8n', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(BUILD),
      'GET /api/automation/entries': { body: { items: [], pagination: { page: 1, per_page: 20, total: 0, pages: 0 } } },
      'GET /api/automation/workflows': {
        body: {
          items: [
            { id: 'w1', name: 'Aviso', active: true, launchable: true, tags: ['platia'], updated_at: null, entry_id: null },
            { id: 'w2', name: 'Ya usada', active: true, launchable: true, tags: ['platia'], updated_at: null, entry_id: 9 },
          ],
          source: OK,
        },
      },
      'POST /api/automation/entries': { status: 201, body: ENTRY },
    })
    renderWithProviders(
      <Routes>
        <Route path="/workshop" element={<Workshop />} />
        <Route path="/workshop/:id" element={<p>Ficha abierta</p>} />
      </Routes>,
      { route: '/workshop' },
    )
    const user = userEvent.setup()
    expect(await screen.findByText('No hay fichas')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Nueva ficha' }))
    const select = await screen.findByRole('combobox', { name: /Flujo de n8n/ })
    expect(screen.queryByRole('option', { name: 'Ya usada' })).not.toBeInTheDocument()
    await user.selectOptions(select, 'w1')
    expect(screen.getByRole('textbox', { name: 'Título' })).toHaveValue('Aviso')
    await user.click(screen.getByRole('button', { name: 'Crear ficha' }))
    expect(await screen.findByText('Ficha abierta')).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.url === '/api/automation/entries')!
    expect(post.body).toMatchObject({ workflow_id: 'w1', title: 'Aviso', category: 'ciclo_comercial', fields: [] })
  })
})

describe('EntryDetail', () => {
  it('propone los datos del flujo como campos y los guarda', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(BUILD),
      'GET /api/automation/entries/3': { body: ENTRY },
      'PATCH /api/automation/entries/3': (call) => ({ body: { ...ENTRY, ...(call.body as object), version: 2 } }),
    })
    renderDetail()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Añadirlos como campos' }))
    const label = screen.getByRole('textbox', { name: 'Etiqueta del campo 1' })
    await user.clear(label)
    await user.type(label, 'Cliente')
    await user.click(screen.getByRole('checkbox', { name: 'Obligatorio' }))
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.body).toMatchObject({
      version: 1,
      fields: [{ name: 'cliente', label: 'Cliente', type: 'text', required: true, options: [] }],
    })
  })

  it('enseña las comprobaciones y el motivo cuando no deja enviarla', async () => {
    mockApi({
      ...sessionRoutes(BUILD),
      'GET /api/automation/entries/3': {
        body: {
          ...ENTRY,
          checked_at: '2026-11-11T10:05:00Z',
          checks: [{ code: 'webhook_auth', level: 'error', message: 'El Webhook debe pedir la clave de PLATIA.', node: 'Webhook PLATIA' }],
        },
      },
      'POST /api/automation/entries/3/submit': { status: 422, body: { error: 'La ficha no pasa las comprobaciones.' } },
    })
    renderDetail()
    expect(await screen.findByText(/El Webhook debe pedir la clave de PLATIA/)).toBeInTheDocument()
    expect(screen.getByText('Error')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Enviar a revisión' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('La ficha no pasa las comprobaciones.')
  })

  it('quien administra publica una ficha en revisión', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(MANAGE),
      'GET /api/automation/entries/3': { body: { ...ENTRY, status: 'in_review', version: 4 } },
      'POST /api/automation/entries/3/review': { body: { ...ENTRY, status: 'published', version: 5 } },
    })
    renderDetail()
    const user = userEvent.setup()
    await user.type(await screen.findByRole('textbox', { name: /Nota/ }), 'Revisada')
    await user.click(screen.getByRole('button', { name: 'Publicar' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/automation/entries/3/review')).toBe(true))
    expect(calls.find((c) => c.url === '/api/automation/entries/3/review')!.body).toEqual({
      version: 4,
      decision: 'approve',
      note: 'Revisada',
    })
  })

  it('quien construye no ve los botones de revisión', async () => {
    mockApi({ ...sessionRoutes(BUILD), 'GET /api/automation/entries/3': { body: { ...ENTRY, status: 'in_review' } } })
    renderDetail()
    expect(await screen.findByText('Pendiente de que quien administra la revise y la publique.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Publicar' })).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Título' })).toBeDisabled()
  })
})
