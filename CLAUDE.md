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
- **Datos**: MySQL 8.0 con 3 esquemas (`platform_core`, `operations_db`, `analytics_db`), Redis, Qdrant
- **Proxy**: Nginx, único servicio con puerto publicado — `nginx/nginx.conf`
- **Redes Docker**: `frontend_net`, `backend_net`, `data_net` (mínimo privilegio)

## Comandos
- Crear `.env`: `python scripts/generate_env.py` (luego poner `ANTHROPIC_API_KEY` a mano)
- Levantar: `docker compose up -d --build` → http://localhost:8080
- Tests backend: `cd backend && pip install -r requirements-dev.txt && pytest`
- Tests IA: `cd ai_service && pip install -r requirements-dev.txt && pytest`
- Frontal: `cd frontend && npm ci && npm run build`

## Convenciones obligatorias
- Logs con `structlog`, nunca `print()`.
- Toda configuración y secreto sale de variables de entorno; plantilla en `.env.example`.
- Cada modelo declara `__bind_key__` (`core`, `operations` o `analytics`).
- Datos de negocio con borrado lógico (`is_active`, `deleted_at`) y auditoría
  (`created_at`, `updated_at`, `created_by`).
- Cambios de esquema siempre con migraciones Alembic (desde la fase 2).
- Todo endpoint nuevo lleva autenticación y comprobación de permisos (desde la fase 3).
- Cada llamada a un LLM se registra con modelo, tokens, coste y latencia (desde la fase 5).
- Los prompts viven en base de datos y se versionan, no en el código (desde la fase 5).

## Lo que NO hacer
- No hardcodear IDs de tenant, API keys, contraseñas ni secretos.
- No subir `.env` ni pegar secretos en issues, PRs o chats.
- No hacer `ALTER TABLE` a mano.
- No exponer `ai_service`, MySQL, Redis ni Qdrant fuera de las redes internas.
- No hacer commit sin que pasen los tests y compile TypeScript.
- No copiar texto del libro al repositorio: es contenido con copyright. Los fragmentos
  de código del repositorio machinebooks.ai son MIT y se pueden reutilizar citando su origen.
