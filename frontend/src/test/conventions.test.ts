// Reglas del frontal que se pueden comprobar leyendo el código (CLAUDE.md, ADR-014/015).
import { describe, expect, it } from 'vitest'

const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../test/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

function offenders(pattern: RegExp, allowed: string[] = []) {
  return Object.entries(sources)
    .filter(([path, code]) => !allowed.some((a) => path.endsWith(a)) && pattern.test(code))
    .map(([path]) => path)
}

describe('convenciones del frontal', () => {
  it('lee todo el código fuente', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50)
  })

  it('el token no se guarda en localStorage ni sessionStorage', () => {
    expect(offenders(/\b(localStorage|sessionStorage)\s*[.[]/)).toEqual([])
  })

  it('no se inyecta HTML crudo', () => {
    expect(offenders(/dangerouslySetInnerHTML\s*=|\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write/)).toEqual([])
  })

  it('las llamadas a la API pasan por lib/api.ts', () => {
    // Health consulta /api/health, que es público, antes de que haya sesión
    expect(offenders(/(?<![\w.])fetch\(/, ['lib/api.ts', 'pages/Health.tsx'])).toEqual([])
  })

  it('no hay eval ni Function con texto', () => {
    expect(offenders(/\beval\(|new Function\(/)).toEqual([])
  })
})
