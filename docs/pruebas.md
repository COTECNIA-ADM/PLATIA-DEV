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
| Calidad de la IA (sin coste) | `backend/tests/test_eval_*.py` con los casos de `backend/app/evals/data/` | Ataques contra los guardarraíles, defensas de los prompts, intención por patrones y ataques de punta a punta al RAG con la IA simulada | dentro de `pytest` del backend |
| Calidad de la IA (modelo real) | `flask eval-ai` | Lo mismo con Claude: aciertos del RAG, resistencia a la inyección e intención | ver abajo; se lanza a mano |
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

## Calidad de la IA

### Sin coste, en cada PR

Los casos están en JSON en `backend/app/evals/data/` para que se puedan leer y ampliar sin
tocar código:

| Fichero | Qué contiene |
| --- | --- |
| `entradas.json` | Texto que alguien escribe a la IA: inyecciones en español e inglés, ofuscadas (tildes, letras de otros alfabetos, espacios invisibles), peticiones maliciosas, datos personales y preguntas legítimas que se parecen a un ataque |
| `salidas.json` | Respuestas del modelo con claves, trozos del prompt de sistema o rutas internas |
| `intencion.json` | Consultas del buscador con su intención esperada |
| `rag.json` | Un corpus ficticio de pliegos, preguntas con los datos que debe contener la respuesta y ataques de inyección con un «canario» |

Las pruebas exigen detectar todos los ataques del juego sin bloquear ninguna pregunta
legítima. Los ataques marcados `gap` (paráfrasis sin palabras clave, órdenes en base64)
no los paran los patrones: quedan documentados y los tiene que parar el modelo, que es lo
que mide el modo con Claude real. Además se comprueba que:

- un documento restringido nunca llega al modelo para quien no puede verlo;
- un documento no puede cerrar su bloque en el prompt ni hacerse pasar por otra fuente;
- una respuesta con claves o con trozos del prompt de sistema no se muestra;
- todos los prompts tienen el texto de fuera entre etiquetas y lo declaran como dato.

### Con Claude real (opcional, a mano)

Necesita la plataforma levantada con `ANTHROPIC_API_KEY`. Un pase completo cuesta unos
céntimos; el tope por defecto es 0,50 USD y se puede cambiar:

```powershell
docker compose run --rm migrations flask eval-ai --max-usd 0.5
docker compose run --rm migrations flask eval-ai --suite rag --juez
```

| Suite | Coste | Qué hace |
| --- | --- | --- |
| `prompts` | 0 | Revisa las defensas de los prompts **activos** en tu base de datos (una edición desde Admin puede quitarlas) |
| `guardarrailes` | 0 | Pasa el juego de ataques por los guardarraíles de tu instalación |
| `intencion` | muy bajo | Clasifica las consultas con las dos capas; el modelo rápido solo interviene cuando los patrones dudan |
| `rag` | bajo | Responde las preguntas del corpus y comprueba datos, «contexto suficiente», citas y que no obedece instrucciones inyectadas. Con `--juez`, el prompt `rag.evaluate` puntúa además fidelidad e invención |

Cada llamada queda en el registro de uso de IA (Admin → IA) con su coste, y cuenta para
los presupuestos. Si se llega al tope, la evaluación se para y lo dice. El comando sale con
error si algo queda por debajo del umbral de cada juego (`umbral` en su JSON), así que se
puede usar antes de cambiar de modelo o de activar una versión nueva de un prompt.

## Escribir una prueba nueva

- **Ruta nueva del backend**: si lleva los tres decoradores, la matriz ya la cubre. Añade
  pruebas de su lógica en `backend/tests/` y la ruta en `docs/api.md`.
- **Pantalla nueva**: una prueba en `*.test.tsx` junto al componente cuando tenga lógica
  (formularios, permisos, estados de error). Busca por rol y texto visible
  (`getByRole`, `getByLabelText`), como lo haría una persona.
- **Ataque o consulta nueva para la IA**: un caso más en el JSON que toque de
  `backend/app/evals/data/`. Si es un ataque que hoy no se para, márcalo con `gap` y el motivo.
- **Flujo importante de punta a punta**: un paso más en `frontend/e2e/`. Mantenlos pocos y
  sin esperas fijas: `expect(...).toBeVisible()` ya reintenta.
