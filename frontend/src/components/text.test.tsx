// El texto de la IA y del buscador nunca se interpreta como HTML (sin dangerouslySetInnerHTML).
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { Highlight, Markdown } from './text'

const renderMd = (text: string, onCite?: (n: number) => void) =>
  render(
    <MemoryRouter>
      <Markdown text={text} onCite={onCite} />
    </MemoryRouter>,
  )

describe('Markdown', () => {
  it('pinta el subconjunto previsto: títulos, listas, negrita, código', () => {
    const { container } = renderMd('# Resumen\n\n- **Plazo**: 3 meses\n- Usa `Kubernetes`\n\n1. Uno\n2. Dos')
    expect(screen.getByRole('heading', { name: 'Resumen' })).toBeInTheDocument()
    expect(container.querySelectorAll('ul > li')).toHaveLength(2)
    expect(container.querySelectorAll('ol > li')).toHaveLength(2)
    expect(container.querySelector('strong')).toHaveTextContent('Plazo')
    expect(container.querySelector('code')).toHaveTextContent('Kubernetes')
  })

  it('un intento de inyectar HTML se muestra como texto', () => {
    const attack = '<img src=x onerror="alert(1)"><script>alert(2)</script><a href="javascript:alert(3)">x</a>'
    const { container } = renderMd(attack)
    expect(container.querySelector('img, script, a')).toBeNull()
    expect(container).toHaveTextContent('<script>alert(2)</script>')
  })

  it('solo enlaza rutas internas; un enlace externo queda como texto', () => {
    renderMd('Mira [la propuesta](/proposals/3) y [esto](https://malicioso.example) o [esto](javascript:alert(1))')
    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', '/proposals/3')
  })

  it('las citas [n] llaman a onCite', async () => {
    const onCite = vi.fn()
    renderMd('Según el pliego [2].', onCite)
    await userEvent.click(screen.getByRole('button', { name: '2' }))
    expect(onCite).toHaveBeenCalledWith(2)
  })
})

describe('Highlight', () => {
  it('solo convierte <mark>; el resto del HTML queda como texto', () => {
    const { container } = render(<Highlight html={'Pliego de <mark>nube</mark> &lt;b&gt;x&lt;/b&gt; <img src=x>'} />)
    expect(container.querySelectorAll('mark')).toHaveLength(1)
    expect(container.querySelector('img, b')).toBeNull()
    expect(container).toHaveTextContent('Pliego de nube <b>x</b> <img src=x>')
  })
})
