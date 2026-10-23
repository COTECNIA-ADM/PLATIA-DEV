# PLATIA-DEV

Reproducción de la Plataforma descrita en *El Arquitecto y la Máquina*
(Carlos Pérez González y Juan C. Montes, 2026), construida por fases con Claude Code.

Estado actual: **fase 0, núcleo mínimo** (8 contenedores). El plan completo está en
[`docs/plan-fases.md`](docs/plan-fases.md).

## Arranque rápido

Requisitos: Docker Desktop (o Docker Engine + Compose v2), Python 3 y unos 8 GB de RAM libres.

```bash
python scripts/generate_env.py      # crea .env con secretos aleatorios
# edita .env y pon tu ANTHROPIC_API_KEY (opcional en la fase 0)
docker compose up -d --build
```

Abre http://localhost:8080: verás el estado básico de los servicios; el completo, al
iniciar sesión como administrador. Sin `ANTHROPIC_API_KEY`
el servicio de IA aparece en **Aviso**; el resto debe estar en **OK**.

- Comprobación rápida: `curl http://localhost:8080/api/health`
- Comprobación completa: `curl http://localhost:8080/api/health/full`
- Parar: `docker compose down` (añade `-v` para borrar también los datos)

La primera vez, crea tu usuario administrador (la contraseña se pide por teclado y no
se muestra) y entra en http://localhost:8080:

```bash
docker compose run --rm migrations flask create-admin --email tu@empresa.com --name "Tu Nombre"
```

Más en [docs/seguridad.md](docs/seguridad.md).

### Al actualizar a una fase nueva

```bash
git checkout main
git pull
python scripts/generate_env.py --actualizar   # añade a .env las variables nuevas
docker compose up -d --build --force-recreate
```

Al arrancar, el contenedor `migrations` crea las tablas de los tres esquemas y carga los
datos iniciales; después termina (es normal verlo como «Exited (0)»). Guía en
[docs/migraciones.md](docs/migraciones.md).

## Si algo sale «Caído»

1. `docker compose ps` y `docker compose logs mysql` (o el servicio que falle).
2. Si `backend` no arranca, mira `docker compose logs migrations`: el backend espera a que
   las migraciones terminen bien.
3. MySQL solo ejecuta `database/init/` la primera vez, con el volumen vacío. Si cambias
   ese script o falló al arrancar, recrea el volumen: `docker compose down -v` y vuelve a
   levantar (borra los datos de MySQL, Redis y Qdrant).
4. En Windows, el repositorio fuerza finales de línea LF (`.gitattributes`). Si clonaste
   antes de que existiera ese fichero, clona de nuevo.

## Contenedores del núcleo

| Servicio | Imagen | Red | Función |
| --- | --- | --- | --- |
| mysql | mysql:8.0 | data | 3 esquemas: platform_core, operations_db, analytics_db |
| redis | redis:7 | data | Caché, sesiones y broker de Celery |
| qdrant | qdrant/qdrant | data | Vectores para RAG |
| backend | build `backend/` | backend + data | API Flask |
| ai_service | build `ai_service/` | backend + data | Servicio de IA (FastAPI + Claude) |
| celery_worker | build `backend/` | backend + data | Tareas en segundo plano |
| frontend | build `frontend/` | frontend | App React principal |
| nginx | nginx:1.27 | frontend + backend | Proxy inverso, único puerto publicado |
| migrations | build `backend/` | data | Un solo uso: migraciones Alembic y datos iniciales |

## Seguridad

- Los secretos solo viven en `.env`, que nunca se sube al repositorio.
- Nunca pegues contraseñas ni claves en chats, issues o PRs.
- Solo Nginx publica un puerto; las bases de datos y el servicio de IA no son accesibles desde fuera.

## Origen

La arquitectura sigue el libro. Algunos patrones se basan en los fragmentos MIT de
[machinebooks/machinebooks.ai](https://github.com/machinebooks/machinebooks.ai)
(`ES/architect/`). El texto del libro no se incluye en este repositorio.
