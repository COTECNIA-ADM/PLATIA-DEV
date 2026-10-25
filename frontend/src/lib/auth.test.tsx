// Permisos en pantalla: salen de /api/auth/me (nunca del token) y se deniegan por defecto.
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useAuth } from './auth'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

function Probe() {
  const { user, loading, denied, can, hasAI, canModify } = useAuth()
  if (loading) return <p>cargando</p>
  return (
    <ul>
      <li>usuario: {user?.email ?? 'ninguno'}</li>
      <li>denegado: {String(denied)}</li>
      <li>leer: {String(can('opportunities', 'read'))}</li>
      <li>borrar: {String(can('opportunities', 'delete'))}</li>
      <li>otro módulo: {String(can('proposals', 'read'))}</li>
      <li>ia: {String(hasAI('documents'))}</li>
      <li>mío: {String(canModify('opportunities', 7))}</li>
      <li>ajeno: {String(canModify('opportunities', 99))}</li>
    </ul>
  )
}

const shown = async () => {
  await waitFor(() => expect(screen.queryByText('cargando')).not.toBeInTheDocument())
  return Object.fromEntries(screen.getAllByRole('listitem').map((li) => li.textContent!.split(': ')))
}

describe('useAuth', () => {
  it('aplica los permisos del rol y nada más', async () => {
    mockApi(sessionRoutes({ opportunities: ['read', 'write'], ai_modules_access: ['documents'] }))
    renderWithProviders(<Probe />)
    expect(await shown()).toEqual({
      usuario: 'ana@example.com',
      denegado: 'false',
      leer: 'true',
      borrar: 'false',
      'otro módulo': 'false',
      ia: 'true',
      mío: 'true',
      ajeno: 'false',
    })
  })

  it('con manage puede modificar lo de otra persona', async () => {
    mockApi(sessionRoutes({ opportunities: ['read', 'manage'] }))
    renderWithProviders(<Probe />)
    expect((await shown()).ajeno).toBe('true')
  })

  it('el rol de administración de la aplicación lo puede todo', async () => {
    mockApi(sessionRoutes({}, { isAdmin: true }))
    renderWithProviders(<Probe />)
    expect(await shown()).toMatchObject({ borrar: 'true', ia: 'true', ajeno: 'true' })
  })

  it('sin sesión (el refresco falla) no hay usuario ni permisos', async () => {
    mockApi({ 'POST /api/auth/refresh': { status: 401 } })
    renderWithProviders(<Probe />)
    expect(await shown()).toMatchObject({ usuario: 'ninguno', leer: 'false', ia: 'false' })
  })

  it('un 403 en /me marca la sesión como válida pero sin acceso a esta aplicación', async () => {
    mockApi({
      'POST /api/auth/refresh': { body: { access_token: 't' } },
      'GET /api/auth/me': { status: 403, body: { error: 'Sin acceso a esta aplicación.' } },
    })
    renderWithProviders(<Probe />)
    expect(await shown()).toMatchObject({ usuario: 'ninguno', denegado: 'true' })
  })
})
