// Puerta de entrada: sin sesión, la pantalla de acceso; sin rol, el aviso; con rol, la app.
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import AccessGate from './AccessGate'
import { meResponse, mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const App = () => <AccessGate>contenido de la aplicación</AccessGate>

describe('AccessGate', () => {
  it('con sesión y rol muestra la aplicación', async () => {
    mockApi(sessionRoutes({ opportunities: ['read'] }))
    renderWithProviders(<App />)
    expect(await screen.findByText('contenido de la aplicación')).toBeInTheDocument()
  })

  it('sin sesión pide entrar y, al entrar, abre la aplicación', async () => {
    const { calls } = mockApi({
      'POST /api/auth/refresh': { status: 401 },
      'POST /api/auth/login': { body: { access_token: 'nuevo' } },
      'GET /api/auth/me': { body: meResponse({ opportunities: ['read'] }) },
    })
    renderWithProviders(<App />)
    await userEvent.type(await screen.findByLabelText('Email'), 'ana@example.com')
    await userEvent.type(screen.getByLabelText('Contraseña'), 'una-clave-de-prueba')
    await userEvent.click(screen.getByRole('button', { name: /entrar/i }))
    expect(await screen.findByText('contenido de la aplicación')).toBeInTheDocument()
    expect(calls.find((c) => c.url === '/api/auth/login')?.body).toEqual({
      email: 'ana@example.com',
      password: 'una-clave-de-prueba',
    })
    expect(calls.find((c) => c.url === '/api/auth/me')?.headers.Authorization).toBe('Bearer nuevo')
  })

  it('con MFA pide el código antes de abrir la sesión', async () => {
    const { calls } = mockApi({
      'POST /api/auth/refresh': { status: 401 },
      'POST /api/auth/login': { body: { mfa_required: true, mfa_token: 'mfa-1' } },
      'POST /api/auth/mfa/verify': { body: { access_token: 'nuevo' } },
      'GET /api/auth/me': { body: meResponse({}) },
    })
    renderWithProviders(<App />)
    await userEvent.type(await screen.findByLabelText('Email'), 'ana@example.com')
    await userEvent.type(screen.getByLabelText('Contraseña'), 'clave')
    await userEvent.click(screen.getByRole('button', { name: /entrar/i }))
    await userEvent.type(await screen.findByLabelText(/código/i), ' 123456 ')
    await userEvent.click(screen.getByRole('button', { name: /entrar|verificar|continuar/i }))
    expect(await screen.findByText('contenido de la aplicación')).toBeInTheDocument()
    expect(calls.find((c) => c.url === '/api/auth/mfa/verify')?.body).toEqual({ mfa_token: 'mfa-1', code: '123456' })
  })

  it('un error al entrar se muestra y no abre la aplicación', async () => {
    mockApi({
      'POST /api/auth/refresh': { status: 401 },
      'POST /api/auth/login': { status: 401, body: { error: 'Email o contraseña incorrectos.' } },
    })
    renderWithProviders(<App />)
    await userEvent.type(await screen.findByLabelText('Email'), 'ana@example.com')
    await userEvent.type(screen.getByLabelText('Contraseña'), 'mala')
    await userEvent.click(screen.getByRole('button', { name: /entrar/i }))
    expect(await screen.findByText('Email o contraseña incorrectos.')).toBeInTheDocument()
    expect(screen.queryByText('contenido de la aplicación')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Contraseña')).toHaveValue('')
  })

  it('sin rol en esta aplicación avisa y ofrece las demás', async () => {
    mockApi({
      'POST /api/auth/refresh': { body: { access_token: 't' } },
      'GET /api/auth/me': { status: 403, body: { error: 'Sin acceso.' } },
    })
    renderWithProviders(<App />)
    expect(await screen.findByText(/no tiene acceso a Operaciones/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Analítica' })).toHaveAttribute('href', '/analytics/')
    expect(screen.queryByText('contenido de la aplicación')).not.toBeInTheDocument()
  })
})
