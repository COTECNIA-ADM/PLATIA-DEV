// Alta y edición de un perfil de talento: lo que se envía a la API.
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ProfileForm from './ProfileForm'
import type { Profile } from '../lib/types'
import { mockApi, renderWithProviders, sessionRoutes } from '../test/utils'

const PERMS = { talent: ['read', 'write'] }

describe('ProfileForm', () => {
  it('crea un perfil con competencias y experiencias, sin filas vacías', async () => {
    const saved = { id: 5, full_name: 'Luis Gómez' }
    const { calls } = mockApi({ ...sessionRoutes(PERMS), 'POST /api/talent/profiles': { status: 201, body: saved } })
    const onSaved = vi.fn()
    renderWithProviders(<ProfileForm onClose={() => undefined} onSaved={onSaved} />)
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Nombre completo'), '  Luis Gómez ')
    await user.type(screen.getByLabelText('Años de experiencia'), '12')
    await user.click(screen.getByRole('button', { name: 'Añadir competencia' }))
    await user.type(screen.getByLabelText('Competencia'), 'Kubernetes')
    await user.selectOptions(screen.getByLabelText('Nivel de la competencia'), '4')
    await user.click(screen.getByRole('button', { name: 'Añadir competencia' })) // se queda vacía
    await user.click(screen.getByRole('button', { name: 'Añadir experiencia' }))
    await user.type(screen.getByLabelText('Empresa o cliente'), 'Banco Norte')
    await user.type(screen.getByLabelText(/^Tecnologías/), 'AWS, , Terraform ')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(onSaved.mock.calls[0][0]).toEqual(saved)
    const body = calls.find((c) => c.method === 'POST' && c.url === '/api/talent/profiles')?.body
    expect(body).toMatchObject({
      full_name: 'Luis Gómez',
      email: null,
      years_experience: 12,
      family: null,
      is_available: true,
      skills: [{ name: 'Kubernetes', level: 4, years: null }],
      experiences: [{ company: 'Banco Norte', role: null, start_date: null, technologies: ['AWS', 'Terraform'] }],
    })
  })

  it('al editar manda PATCH con la versión (bloqueo optimista) y muestra el 409', async () => {
    const profile = {
      id: 9,
      version: 3,
      full_name: 'Marta Ruiz',
      email: 'marta@example.com',
      headline: null,
      family: null,
      seniority: null,
      years_experience: 8,
      summary: null,
      is_available: false,
      skills: [{ name: 'Python', level: 5, years: 8 }],
      experiences: [],
    } as unknown as Profile
    const { calls } = mockApi({
      ...sessionRoutes(PERMS),
      'PATCH /api/talent/profiles/9': { status: 409, body: { error: 'Otra persona ha cambiado este perfil. Recarga.' } },
    })
    renderWithProviders(<ProfileForm profile={profile} onClose={() => undefined} onSaved={() => undefined} />)
    expect(await screen.findByLabelText('Competencia')).toHaveValue('Python')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByText('Otra persona ha cambiado este perfil. Recarga.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ version: 3, is_available: false, email: 'marta@example.com' })
  })
})
