// Solicitudes del formulario web: listado con filtro en la URL y decisión de comercial.
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import Leads from './Leads'
import LeadDetail from './LeadDetail'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const PERMS = { leads: ['read', 'manage'], clients: ['read', 'write'], opportunities: ['read', 'write'] }
const PAGE = { page: 1, per_page: 20, total: 1, pages: 1 }
const SUMMARY = {
  id: 3,
  source: 'formulario_web',
  status: 'new',
  resolution: null,
  full_name: 'Lucía Pérez',
  email: 'lucia@cliente.example',
  company: 'Construcciones Ejemplo',
  subject: 'Mantenimiento de edificios',
  created_at: '2026-11-13T09:00:00Z',
  resolved_at: null,
  version: 1,
}
const LEAD = {
  ...SUMMARY,
  phone: '600000000',
  tax_id: null,
  message: 'Queremos una oferta.\nSon tres edificios.',
  ack_sent: true,
  workflow_id: 'platiaSolWeb01',
  client_id: null,
  contact_id: null,
  opportunity_id: null,
  resolved_by: null,
  resolution_note: null,
  matches: [{ id: 8, name: 'Construcciones Ejemplo', tax_id: 'B00000000' }],
}

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/leads/:id" element={<LeadDetail />} />
    </Routes>,
    { route: '/leads/3' },
  )
}

describe('Leads', () => {
  it('lista las pendientes y pasa el filtro de la URL', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/leads': { body: { items: [SUMMARY], pagination: PAGE } },
    })
    renderWithProviders(<Leads />, { route: '/leads?status=new' })
    expect(await screen.findByRole('link', { name: 'Lucía Pérez' })).toHaveAttribute('href', '/leads/3')
    expect(screen.getByText('Pendiente')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Estado' }), 'converted')
    await waitFor(() => expect(calls.some((c) => c.url.includes('status=converted'))).toBe(true))
  })
})

describe('LeadDetail', () => {
  it('convierte en oportunidad del cliente que ya existe', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/leads/3': { body: LEAD },
      'POST /api/leads/3/resolve': {
        body: { ...LEAD, status: 'converted', resolution: 'opportunity', client_id: 8, opportunity_id: 21, matches: [] },
      },
    })
    renderDetail()
    expect(await screen.findByText(/Son tres edificios/)).toBeInTheDocument()
    expect(screen.getByText('Acuse enviado')).toBeInTheDocument()
    const user = userEvent.setup()
    expect(screen.getByRole('radio', { name: /Construcciones Ejemplo/ })).toBeChecked()
    await user.clear(screen.getByRole('textbox', { name: /Título de la oportunidad/ }))
    await user.type(screen.getByRole('textbox', { name: /Título de la oportunidad/ }), 'Tres edificios')
    await user.click(screen.getByRole('button', { name: 'Convertir' }))
    expect(await screen.findByRole('link', { name: 'Ver la oportunidad' })).toHaveAttribute('href', '/opportunities/21')
    const post = calls.find((c) => c.method === 'POST' && c.url === '/api/leads/3/resolve')!
    expect(post.body).toEqual({ version: 1, action: 'opportunity', note: null, client_id: 8, opportunity_title: 'Tres edificios' })
  })

  it('descarta con una nota', async () => {
    const { calls } = mockApi({
      ...sessionRoutes(PERMS),
      'GET /api/leads/3': { body: { ...LEAD, matches: [] } },
      'POST /api/leads/3/resolve': { body: { ...LEAD, status: 'discarded', resolution_note: 'Spam', matches: [] } },
    })
    renderDetail()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('radio', { name: 'Descartar' }))
    expect(screen.queryByRole('group', { name: 'Cliente' })).not.toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: /Nota/ }), 'Spam')
    await user.click(screen.getByRole('button', { name: 'Descartar' }))
    expect(await screen.findByText('Spam')).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.url === '/api/leads/3/resolve')!
    expect(post.body).toEqual({ version: 1, action: 'discard', note: 'Spam' })
  })

  it('sin permiso de escritura solo deja descartar', async () => {
    mockApi({ ...sessionRoutes({ leads: ['read', 'manage'] }), 'GET /api/leads/3': { body: LEAD } })
    renderDetail()
    expect(await screen.findByRole('radio', { name: 'Crear contacto y oportunidad' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'Solo crear el contacto' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'Descartar' })).toBeChecked()
  })

  it('quien solo consulta no ve la decisión', async () => {
    mockApi({ ...sessionRoutes({ leads: ['read'] }), 'GET /api/leads/3': { body: LEAD } })
    renderDetail()
    expect(await screen.findByText(/Son tres edificios/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Convertir' })).not.toBeInTheDocument()
  })
})
