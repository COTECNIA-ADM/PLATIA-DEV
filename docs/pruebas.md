# Pruebas

Cómo se prueba la plataforma y cómo lanzar cada batería. La estrategia está en
[ADR-018](adr/ADR-018-estrategia-de-pruebas.md). La CI (`.github/workflows/ci.yml`) las
pasa todas en cada PR.

| Batería | Dónde | Qué comprueba | Cómo se lanza |
| --- | --- | --- | --- |
| Backend | `backend/tests/` | Servicios, rutas, migraciones, búsqueda, IA simulada y la [matriz de autorización](seguridad.md#la-matriz-de-autorización-lo-comprueba-sola) | `cd backend && pytest` |
| Servicio de IA | `ai_service/tests/` | Pasarela, proveedores simulados, embeddings y vectores | `cd ai_service && pytest` |
| Estilo | `ruff.toml` | Errores de Python (E9, F, B) | `ruff check backend ai_service` |
| Pantallas | `frontend/src/**/*.test.tsx` | Cliente de la API, sesión y permisos, entrada con MFA, formularios, texto de la IA sin HTML y convenciones del frontal | `cd frontend && npm test` |
| Recorrido completo (E2E) | `frontend/e2e/` | La plataforma levantada en un navegador real: menús de las tres aplicaciones, alta de cliente y oportunidad, salida, cookies y cabeceras | ver abajo |

La CI exige además una cobertura mínima en el backend y en el servicio de IA. Para verla en
local: `pytest --cov=app --cov-report=term-missing`.

## Pruebas de pantallas (Vitest)

```bash
cd frontend
npm ci
npm test            # una vez
npx vitest          # en modo vigilancia mientras programas
```

No necesitan la plataforma levantada: `src/test/utils.tsx` simula la API con una tabla de
rutas (`mockApi`) y monta los mismos proveedores que la aplicación (`renderWithProviders`).

## Recorrido completo en navegador (Playwright)

Necesita la plataforma levantada (`docker compose up -d --build`) y un superadministrador.
Usa uno solo para pruebas, no tu cuenta: las pruebas crean clientes y oportunidades con
«E2E» en el nombre.

1. Crea el usuario de pruebas (la contraseña se teclea, no va en la orden):

   ```powershell
   docker compose run --rm migrations flask create-admin --email e2e@example.com --name "Prueba E2E"
   ```

2. Instala Chromium para Playwright (solo la primera vez):

   ```powershell
   cd frontend
   npm ci
   npx playwright install chromium
   ```

3. Lanza las pruebas. La contraseña va en una variable de la sesión de PowerShell; no la
   guardes en ningún fichero:

   ```powershell
   $env:E2E_EMAIL = "e2e@example.com"
   $env:E2E_PASSWORD = Read-Host "Contraseña del usuario de pruebas"
   npx playwright test
   ```

   En Linux o macOS: `E2E_EMAIL=e2e@example.com E2E_PASSWORD=... npx playwright test`.
   Sin esas variables, las pruebas se saltan. Para apuntar a otra dirección:
   `E2E_BASE_URL` (por defecto `http://localhost:8080`).

Si algo falla, `npx playwright show-report` abre el informe con capturas y la traza de
cada paso. En la CI, el informe se adjunta a la ejecución como `playwright-report`.

El usuario de pruebas no tiene MFA. No lo crees en producción; si lo necesitas allí,
dalo de baja al terminar.

## Escribir una prueba nueva

- **Ruta nueva del backend**: si lleva los tres decoradores, la matriz ya la cubre. Añade
  pruebas de su lógica en `backend/tests/` y la ruta en `docs/api.md`.
- **Pantalla nueva**: una prueba en `*.test.tsx` junto al componente cuando tenga lógica
  (formularios, permisos, estados de error). Busca por rol y texto visible
  (`getByRole`, `getByLabelText`), como lo haría una persona.
- **Flujo importante de punta a punta**: un paso más en `frontend/e2e/`. Mantenlos pocos y
  sin esperas fijas: `expect(...).toBeVisible()` ya reintenta.
