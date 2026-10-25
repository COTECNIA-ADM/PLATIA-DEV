// Analítica y administración con la misma sesión, y salida.
import { expect, test, type Page } from '@playwright/test'
import { requireCredentials, signIn, visitEveryMenuItem, type Problems } from './helpers'

test.describe.configure({ mode: 'serial' })
requireCredentials()

let page: Page
let problems: Problems

test.beforeAll(async ({ browser }) => {
  ;({ page, problems } = await signIn(browser, '/analytics/'))
})
test.afterAll(async () => page?.close())

test('analítica: todas las pantallas cargan', async () => {
  await expect(page.locator('.brand-app')).toHaveText('Analítica')
  await visitEveryMenuItem(page, problems)
})

test('administración: entra con la misma sesión y sus pantallas cargan', async () => {
  await page.goto('/admin/')
  await expect(page.locator('.brand-app')).toHaveText('Administración')
  await visitEveryMenuItem(page, problems)
})

test('cerrar sesión vuelve a la pantalla de acceso y no deja la sesión recuperable', async () => {
  // Desde una pantalla privada (la última del menú, Estado, también es pública)
  await page.locator('.sidebar nav a').first().click()
  await page.getByRole('button', { name: 'Cerrar sesión' }).click()
  await expect(page.getByLabel('Contraseña')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Contraseña')).toBeVisible()
  await expect(page.locator('.sidebar')).toHaveCount(0)
})
