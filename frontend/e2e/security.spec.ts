// Comprobaciones de seguridad que solo se ven en un navegador real.
import { expect, test } from '@playwright/test'
import { requireCredentials, signIn } from './helpers'

requireCredentials()

test('sin sesión, la API responde 401 y la página pide entrar', async ({ page, request }) => {
  const resp = await request.get('/api/opportunities', { headers: { 'X-App-Code': 'operations' } })
  expect(resp.status()).toBe(401)
  await page.goto('/opportunities')
  await expect(page.getByLabel('Contraseña')).toBeVisible()
})

test('el token no se guarda en el navegador y la cookie de refresco es HttpOnly', async ({ browser }) => {
  const { page } = await signIn(browser)
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }))
  expect(storage).not.toMatch(/eyJ/) // ningún JWT
  expect(await page.evaluate(() => document.cookie)).not.toMatch(/eyJ/)
  const cookies = await page.context().cookies()
  const sessionCookies = cookies.filter((c) => /refresh/i.test(c.name))
  expect(sessionCookies.length).toBeGreaterThan(0)
  for (const c of sessionCookies) {
    expect(c.httpOnly, c.name).toBe(true)
    expect(c.sameSite, c.name).not.toBe('None')
  }
  await page.close()
})

test('las cabeceras de seguridad llegan al navegador', async ({ request }) => {
  const resp = await request.get('/')
  const headers = resp.headers()
  expect(headers['content-security-policy']).toContain("default-src 'self'")
  expect(headers['x-content-type-options']).toBe('nosniff')
  expect(headers['x-frame-options'] ?? headers['content-security-policy']).toMatch(/DENY|frame-ancestors 'none'/)
})
