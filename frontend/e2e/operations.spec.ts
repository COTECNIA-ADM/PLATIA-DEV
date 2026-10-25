// Aplicación de operaciones: entrar, recorrer el menú y el ciclo cliente → oportunidad.
import { expect, test, type Page } from '@playwright/test'
import { requireCredentials, signIn, visitEveryMenuItem, type Problems } from './helpers'

test.describe.configure({ mode: 'serial' })
requireCredentials()

let page: Page
let problems: Problems
const stamp = Date.now().toString(36)

test.beforeAll(async ({ browser }) => {
  ;({ page, problems } = await signIn(browser))
})
test.afterAll(async () => page?.close())

test('todas las pantallas del menú cargan sin errores', async () => {
  await visitEveryMenuItem(page, problems)
})

test('crear un cliente y editarlo', async () => {
  await page.goto('/clients')
  await page.getByRole('button', { name: 'Nuevo cliente' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Nombre').fill(`Cliente E2E ${stamp}`)
  await dialog.getByLabel('Sector').selectOption({ index: 1 })
  await dialog.getByRole('button', { name: 'Guardar' }).click()
  await expect(page.getByRole('heading', { name: `Cliente E2E ${stamp}` })).toBeVisible()

  await page.getByRole('button', { name: 'Editar' }).click()
  await page.getByRole('dialog').getByLabel('Nombre').fill(`Cliente E2E ${stamp} (editado)`)
  await page.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click()
  await expect(page.getByRole('heading', { name: `Cliente E2E ${stamp} (editado)` })).toBeVisible()
})

test('crear una oportunidad para ese cliente y encontrarla en el listado', async () => {
  const title = `Oportunidad E2E ${stamp}`
  await page.goto('/opportunities')
  await page.getByRole('button', { name: 'Nueva oportunidad' }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Título').fill(title)
  await dialog.getByLabel('Descripción').fill('Migración de la plataforma de expedientes a la nube con Kubernetes.')
  await dialog.getByLabel('Cliente').selectOption({ label: `Cliente E2E ${stamp} (editado)` })
  await dialog.getByLabel('Importe estimado (€)').fill('150000')
  await dialog.getByRole('button', { name: /crear|guardar/i }).click()

  await expect(page).toHaveURL(/\/opportunities\/\d+$/)
  await expect(page.getByRole('heading', { name: title })).toBeVisible()

  // Los filtros del listado viven en la URL. El buscador indexa en segundo plano
  // (Celery → Meilisearch), así que se reintenta unos segundos.
  await expect(async () => {
    await page.goto(`/opportunities?q=${encodeURIComponent(stamp)}`)
    await expect(page.getByRole('link', { name: title })).toBeVisible({ timeout: 2_000 })
  }).toPass({ timeout: 30_000 })
  expect(problems, problems.join('\n')).toEqual([])
})

test('una ruta desconocida muestra la página de no encontrado', async () => {
  await page.goto('/no-existe-esta-ruta')
  await expect(page.getByText('Esta página no existe')).toBeVisible()
})
