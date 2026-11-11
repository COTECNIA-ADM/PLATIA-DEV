// Inicio del portal Low-Code: cifras del motor y enlace al editor solo para quien construye.
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Home from './Home'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const STATUS = { enabled: true, reachable: true, problem: null, published: 3, active: 2 }

describe('Home', () => {
  it('quien construye ve el enlace al editor de n8n', async () => {
    mockApi({
      ...sessionRoutes({ automations: ['read', 'run', 'build'] }),
      'GET /api/automation/status': { body: { ...STATUS, editor_url: 'http://localhost:5679/' } },
    })
    renderWithProviders(<Home />)
    const link = await screen.findByRole('link', { name: 'Abrir el editor de n8n' })
    expect(link).toHaveAttribute('href', 'http://localhost:5679/')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByText('Conectado')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('quien solo usa no ve el editor', async () => {
    mockApi({
      ...sessionRoutes({ automations: ['read', 'run'] }),
      'GET /api/automation/status': { body: { ...STATUS, editor_url: null } },
    })
    renderWithProviders(<Home />)
    expect(await screen.findByText('Conectado')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Abrir el editor de n8n' })).not.toBeInTheDocument()
  })

  it('avisa si n8n no está activado', async () => {
    mockApi({
      ...sessionRoutes({ automations: ['read'] }),
      'GET /api/automation/status': {
        body: { enabled: false, reachable: false, problem: 'n8n no está activado en esta instalación.', published: 0, active: 0, editor_url: null },
      },
    })
    renderWithProviders(<Home />)
    expect(await screen.findByText('n8n no está activado en esta instalación.')).toHaveAttribute('role', 'status')
    expect(screen.getByText('Sin conexión')).toBeInTheDocument()
  })
})
