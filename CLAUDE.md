# PLATIA — Instrucciones del proyecto para Claude Code

Reproducción de la Plataforma de *El Arquitecto y la Máquina*: automatización de
operaciones B2B (oportunidades, análisis de documentos, propuestas) con IA.
Se construye por fases; el plan está en `docs/plan-fases.md`.
Antes de diseñar algo nuevo, lee `docs/requisitos.md`, `docs/arquitectura.md` y los ADR de
`docs/adr/`. Una decisión de arquitectura nueva se documenta con un ADR.

## Stack y arquitectura
- **Backend**: Flask 3 + SQLAlchemy 2 (multi-bind) — `backend/`
- **Servicio IA**: FastAPI + SDK de Anthropic — `ai_service/` (solo lo llama el backend, con `X-API-Key`)
- **Workers**: Celery con Redis como broker — `backend/celery_app.py`
- **Frontal principal**: React 18 + TypeScript + Vite — `frontend/`
- **Datos**: MySQL 8.0 con 3 esquemas (`platform_core`, `operations_db`, `analytics_db`), Redis, Qdrant, Meilisearch
- **Proxy**: Nginx, único servicio con puerto publicado — `nginx/nginx.conf`
- **Redes Docker**: `frontend_net`, `backend_net`, `data_net` (mínimo privilegio)

## Comandos
- Crear `.env`: `python scripts/generate_env.py` (luego poner `ANTHROPIC_API_KEY` a mano)
- Levantar: `docker compose up -d --build` → http://localhost:8080
- Tests backend: `cd backend && pip install -r requirements-dev.txt && pytest`
- Tests IA: `cd ai_service && pip install -r requirements-dev.txt && pytest`
- Estilo: `ruff check backend ai_service` (configuración en `ruff.toml`); la CI exige además
  una cobertura mínima (`--cov-fail-under`, ver `.github/workflows/ci.yml`)
- Frontal: `cd frontend && npm ci && npm run build`
- Migraciones: las aplica el contenedor `migrations` al levantar; guía en `docs/migraciones.md`
- Nueva migración: `flask db migrate -m "..."`, revisarla a mano y probar upgrade/downgrade/upgrade
- Primer administrador: `docker compose run --rm migrations flask create-admin --email ... --name ...`
- Contraseña olvidada: `flask reset-password --email ...`; MFA perdido: `flask reset-mfa --email ...`
- Variables nuevas tras un `git pull`: `python scripts/generate_env.py --actualizar`
- Producción (guía en `docs/despliegue.md`): `docker compose -f docker-compose.yml -f docker-compose.prod.yml ...`;
  desplegar con `scripts/deploy.sh sha-xxxxxxx`, copias con `scripts/backup.sh --prod` y `scripts/restore.sh`
- Reconstruir búsqueda y RAG desde MySQL: `flask reindex`

## Convenciones obligatorias
- Logs con `structlog`, nunca `print()`.
- Toda configuración y secreto sale de variables de entorno; plantilla en `.env.example`.
- Cada modelo declara `__bind_key__` (`core`, `operations` o `analytics`). Sin claves
  foráneas entre esquemas: los ids de usuario se guardan como enteros (ADR-008).
- Fechas por defecto con funciones (`default=utcnow`), nunca `default=datetime.now(...)`.
- Datos de negocio con borrado lógico (`is_active`, `deleted_at`) y auditoría
  (`created_at`, `updated_at`, `created_by`).
- Cambios de esquema siempre con migraciones Alembic (desde la fase 2).
- Todo endpoint nuevo lleva `@platform_guard`, `@require_permission(módulo, acción)` y
  `@rate_limit(<tipo>)` (guía en `docs/seguridad.md`). Permisos siempre desde la BD, nunca del JWT;
  default-deny.
- `tests/test_security_matrix.py` recorre todas las rutas: una ruta sin esos decoradores, o
  que no dé 401/403 cuando toca, hace fallar los tests. Una excepción nueva va allí con su motivo.
- Los permisos nuevos se registran en `backend/app/security/registry.py`: un módulo o acción
  sin registrar hace fallar el arranque.
- Blueprints por dominio en `app/routes/` y lógica de negocio en `app/services/`.
  Entrada validada con un esquema Pydantic de `app/api/schemas.py` (`extra="forbid"`).
- Toda ruta nueva se añade a la tabla de `docs/api.md`: `tests/test_api_docs.py` falla si
  falta una ruta o si la tabla documenta una que no existe.
- Contrato de API común (guía en `docs/api.md`): listados con `items` + `pagination`, fechas
  ISO UTC, errores con excepciones de `app/errors.py` (nunca detalles internos en un 500).
- Recursos compartidos con bloqueo optimista: el modelo usa `VersionedMixin` y el `PATCH`
  exige `version` (`check_version`, 409 si no coincide).
- Autorización por objeto: antes de modificar oportunidades, documentos o propuestas,
  `ensure_can_modify(módulo, obj)` (responsable o acción `manage`).
- Rate limit por tipo: `RATE_LIMIT_READ`, `_WRITE`, `_UPLOAD`, `_EXPORT`, `_SEARCH` o `_AI`.
- Búsqueda (ADR-012): la sincronización MySQL → Meilisearch es automática; un modelo nuevo que
  deba buscarse se registra en `app/search/indexes.py`. Los filtros se construyen con
  `app/search/filters.py`, nunca concatenando texto. Los resultados se releen de MySQL y
  los documentos se comprueban con `Viewer`.
- Tareas Celery en `app/tasks/`, nombre `tasks.<dominio>.<acción>`, base `PlatformTask`,
  idempotentes. Se encolan con `enqueue(tarea, ...)`; la cola la decide el routing de
  `app/queue.py`. Una tarea programada nueva va en `BEAT_SCHEDULE`.
- Toda llamada a un LLM pasa por `app/ai/gateway.run(tipo_de_tarea, ...)`: aplica
  presupuestos, carga el prompt activo y registra cada intento con modelo, tokens, coste y
  latencia (ADR-011). Nunca llamar al servicio de IA para generar texto por otra vía.
- Los prompts viven en base de datos y se versionan, no en el código. Las versiones
  iniciales están en `backend/app/prompt_seeds/` (solo para `flask seed`); las variables se
  escriben `{{variable}}` y van en la plantilla del usuario, no en la de sistema.
- Un endpoint de IA añade `@require_ai_module(<módulo>)` tras `@require_permission`.
- La IA solo recibe documentos que la persona puede ver: usar `app/ai/access.Viewer`
  (filtro en MySQL, en Qdrant y otra vez sobre los resultados).
- Texto libre del usuario hacia la IA: `guardrails.check_input`; respuesta mostrada:
  `guardrails.check_output`.
- Copiloto y agentes (ADR-013): las herramientas del agente están en `app/agents/tools.py`,
  llaman a servicios de negocio y declaran su nivel mínimo (`auto`, `notify`, `approve`);
  todo lo que cambia datos es `approve`. Nada de herramientas de terminal ni de ficheros.
  El prompt de un agente se llama `agent.<slug>` (slug con guion bajo).
- Endpoints SSE: la vista solo valida y pasa ids; el generador vuelve a cargar los
  registros (Flask cierra la sesión de BD antes de enviar el cuerpo).
- Campos que escriben las tareas en segundo plano (indexado, IA): `obj.set_system_fields(...)`,
  que no cambia `row_version`.
- Migraciones compatibles hacia atrás (ADR-016): primero se añade; lo que se deja de usar se
  borra en una versión posterior, para que la vuelta atrás automática funcione.
- Ficheros generados con IA: metadatos y aviso visible de `app/services/rendering.py`; en
  pantalla, `<AiNote>` junto a la respuesta de la IA.
- Costes de IA: se guardan en USD y se muestran en euros (`fmtAiCost`, `AI_USD_EUR_RATE`).
- Analítica (ADR-017): los cálculos (mapa de oportunidad, comparaciones, objetivos) van en
  `app/services/analytics.py` y `market.py`, nunca en el frontal. Lo que no se puede
  reconstruir hacia atrás (cartera abierta) sale de las fotos diarias de `analytics_snapshots`.
  Las importaciones de Excel comprueban primero (`dry_run`) y aplican todo o nada.

## Frontal (`frontend/`, ADR-014 y ADR-015)
- Tres aplicaciones en un solo build: operaciones (`src/`), analítica (`src/analytics/`) y
  administración (`src/admin/`). Cada una arranca con `mount(código, <App/>)`, que fija su
  `X-App-Code`; el menú va en `Shell` y el control de acceso en `AccessGate`.
- Gráficos con `src/components/charts.tsx` (colores `--series-*` y `--seq-*`), siempre con vista de tabla.
- Llamadas a la API solo con `src/lib/api.ts` (`api`, `download`, `stream`); datos con React Query.
- El token de acceso vive en memoria: nunca `localStorage` ni `sessionStorage`.
- Permisos con `useAuth()` (`can`, `hasAI`, `canModify`), que salen de `/api/auth/me`.
- Nada de `dangerouslySetInnerHTML`: texto de la IA con `<Markdown>` y resaltado con `<Highlight>`.
- Rutas con los mismos nombres que la API; filtros de listados en la URL.
- Estilos en `src/styles.css` con las variables de `:root`; textos de la interfaz en español.

## Lo que NO hacer
- No hardcodear IDs de tenant, API keys, contraseñas ni secretos.
- No subir `.env` ni pegar secretos en issues, PRs o chats.
- No hacer `ALTER TABLE` a mano.
- No exponer `ai_service`, MySQL, Redis, Qdrant ni Meilisearch fuera de las redes internas.
- No hacer commit sin que pasen los tests y compile TypeScript.
- No copiar texto del libro al repositorio: es contenido con copyright. Los fragmentos
  de código del repositorio machinebooks.ai son MIT y se pueden reutilizar citando su origen.
