# PLATIA-DEV

Reproducción de la Plataforma descrita en *El Arquitecto y la Máquina*
(Carlos Pérez González y Juan C. Montes, 2026), construida por fases con Claude Code.

Estado actual: **fase 7b, pruebas del frontal**. La plataforma está completa; falta la
fase 7c (pruebas de calidad de la IA). Son 11 contenedores en desarrollo; en
producción se añaden Flower y, si usas Let's Encrypt, certbot.

- http://localhost:8080: operaciones (oportunidades, documentos, propuestas, copiloto,
  búsqueda, clientes, talento y avisos).
- `/analytics/`: cuadro de mando con comparación y objetivos, mapa de oportunidad,
  competidores, importación desde Excel, preguntas a la IA sobre los datos y valor de la IA.
- `/admin/`: usuarios y roles, modelos y costes de IA, prompts, agentes, búsqueda, tareas y
  auditoría.

Cada persona ve solo las aplicaciones y funciones que su rol permite.

## Documentación

| Para | Documento |
| --- | --- |
| Usar la plataforma | [Manual de usuario](docs/manual-usuario.md) |
| Ponerla en producción | [Despliegue y operación](docs/despliegue.md) |
| Resolver incidencias | [Guía de incidencias](docs/incidencias.md) |
| Protección de datos | [Borrador de DPIA](docs/dpia.md) (lo revisa el DPD) |
| Integrarse con la API | [API](docs/api.md) (comprobada contra el código en cada test) |
| Entender el diseño | [Requisitos](docs/requisitos.md), [arquitectura](docs/arquitectura.md), [ADR](docs/adr/README.md), [seguridad](docs/seguridad.md), [migraciones](docs/migraciones.md) |
| Lanzar las pruebas | [Pruebas](docs/pruebas.md) |
| Saber qué falta | [Plan por fases](docs/plan-fases.md) |

## Arranque rápido

Requisitos: Docker Desktop (o Docker Engine + Compose v2), Python 3 y unos 8 GB de RAM libres.

```bash
python scripts/generate_env.py      # crea .env con secretos aleatorios
# edita .env y pon tu ANTHROPIC_API_KEY (sin ella todo funciona salvo la IA)
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
docker compose up -d --build --force-recreate --remove-orphans
```

`--remove-orphans` borra los contenedores que ya no existen en esta fase (en la fase 4,
`celery_worker` se divide en `celery_default`, `celery_ai` y `celery_beat`).

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

## Probar la API de negocio y la IA

```bash
python scripts/demo_fase4.py --email tu@empresa.com
python scripts/demo_fase5.py --email tu@empresa.com
python scripts/demo_fase5c.py --email tu@empresa.com
```

La primera recorre el flujo de negocio (cliente, oportunidad, documento, propuesta con
revisiones y paquete DOCX). La segunda hace llamadas reales a Claude: sube un pliego de
ejemplo, pregunta sobre él, lo analiza, redacta una propuesta y muestra el coste (unos
céntimos; entre 0,30 y 0,80 USD con la propuesta, o unos 0,05 USD con `--sin-propuesta`).
La tercera conversa con el copiloto: busca oportunidades y, cuando quiere crear una
propuesta, se para y te pregunta en el terminal si lo apruebas (unos céntimos).
Referencia de la API en [docs/api.md](docs/api.md).

La primera vez que se construye `ai_service` descarga el modelo de embeddings (unos
220 MB) dentro de la imagen: tarda unos minutos más.

## Contenedores

| Servicio | Imagen | Red | Función |
| --- | --- | --- | --- |
| mysql | mysql:8.0 | data | 3 esquemas: platform_core, operations_db, analytics_db |
| redis | redis:7 | data | Caché, sesiones y broker de Celery |
| qdrant | qdrant/qdrant | data | Vectores para RAG |
| backend | build `backend/` | backend + data | API Flask |
| ai_service | build `ai_service/` | backend + data | Pasarela de IA: Claude con modelos de reserva, embeddings locales y Qdrant |
| celery_default | build `backend/` | backend + data | Colas rápidas: alertas, tareas generales y sincronización |
| celery_ai | build `backend/` | backend + data | Colas lentas: documentos e IA |
| celery_beat | build `backend/` | data | Tareas programadas (alertas, limpieza RGPD, salud) |
| frontend | build `frontend/` | frontend | App React principal |
| nginx | nginx:1.27 | frontend + backend | Proxy inverso, único puerto publicado |
| migrations | build `backend/` | data | Un solo uso: migraciones Alembic y datos iniciales |
| flower (producción) | imagen del backend | backend + data | Estado de las colas en `/flower/`, con contraseña |
| certbot (producción, opcional) | certbot/certbot | frontend | Renueva el certificado de Let's Encrypt |

## Seguridad

- Los secretos solo viven en `.env`, que nunca se sube al repositorio.
- Nunca pegues contraseñas ni claves en chats, issues o PRs.
- Solo Nginx publica un puerto; las bases de datos y el servicio de IA no son accesibles desde fuera.

## Origen

La arquitectura sigue el libro. Algunos patrones se basan en los fragmentos MIT de
[machinebooks/machinebooks.ai](https://github.com/machinebooks/machinebooks.ai)
(`ES/architect/`). El texto del libro no se incluye en este repositorio.
