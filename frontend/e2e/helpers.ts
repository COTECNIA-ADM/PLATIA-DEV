// Utilidades de las pruebas de navegador.
import { expect, test, type Browser, type Page } from '@playwright/test'

export const EMAIL = process.env.E2E_EMAIL ?? ''
const PASSWORD = process.env.E2E_PASSWORD ?? ''

/** Salta el fichero entero si no hay credenciales de prueba. */
export function requireCredentials() {
  test.skip(!EMAIL || !PASSWORD, 'Define E2E_EMAIL y E2E_PASSWORD (ver docs/pruebas.md)')
}

export type Problems = string[]

/**
 * Apunta lo que no debería pasar nunca en una pantalla: errores de JavaScript,
 * errores en la consola y respuestas 5xx de la API.
 */
export function watchProblems(page: Page): Problems {
  const problems: Problems = []
  page.on('pageerror', (err) => problems.push(`Error de JavaScript: ${err.message}`))
  page.on('console', (msg) => {
    // Un 4xx esperado (p. ej. 404 de un mapa sin datos) sale en consola como recurso fallido
    if (msg.type() === 'error' && !/the server responded with a status of 4\d\d/.test(msg.text())) {
      problems.push(`Consola: ${msg.text()}`)
    }
  })
  page.on('response', (resp) => {
    if (resp.url().includes('/api/') && resp.status() >= 500) problems.push(`${resp.status()} en ${resp.url()}`)
  })
  return problems
}

/** Abre una página nueva, entra con el usuario de pruebas y espera al menú. */
export async function signIn(browser: Browser, path = '/'): Promise<{ page: Page; problems: Problems }> {
  const page = await browser.newPage()
  const problems = watchProblems(page)
  await page.goto(path)
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Contraseña').fill(PASSWORD)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page.locator('.sidebar')).toBeVisible()
  return { page, problems }
}

/** Recorre todas las opciones del menú lateral y comprueba que cada pantalla carga. */
export async function visitEveryMenuItem(page: Page, problems: Problems) {
  const links = page.locator('.sidebar nav a')
  const count = await links.count()
  expect(count).toBeGreaterThan(2)
  for (let i = 0; i < count; i++) {
    const link = links.nth(i)
    const name = (await link.innerText()).trim()
    await link.click()
    await expect(link, `menú: ${name}`).toHaveClass(/active/)
    await expect(page.locator('.main').getByRole('heading').first(), `título de ${name}`).toBeVisible()
    await expect(page.getByText('Esta página no existe')).toHaveCount(0)
    // Hay consultas periódicas (avisos), así que no se espera a la red: se espera a que no quede nada cargando
    await expect(page.locator('.spinner'), `carga de ${name}`).toHaveCount(0)
  }
  expect(problems, problems.join('\n')).toEqual([])
}
