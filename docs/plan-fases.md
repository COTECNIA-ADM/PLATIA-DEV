# Plan por fases

| # | Fase | Qué se construye | Capítulos del libro | Estado |
| --- | --- | --- | --- | --- |
| 0 | Preparación y núcleo | Estructura, `.env`, docker-compose de 8 contenedores, health checks | 1–3, Ap. F | Hecha |
| 1 | Requisitos y arquitectura | `docs/requisitos.md`, `docs/arquitectura.md` y `docs/adr/` | 4 | Hecha |
| 2 | Base de datos | Modelos SQLAlchemy en 3 esquemas, Alembic, borrado lógico y auditoría | 5, Ap. A | En curso |
| 3 | Seguridad e IAM | JWT con refresh, MFA, roles por aplicación, cabeceras OWASP, rate limiting | 6 | Pendiente |
| 4 | Backend | Blueprints de negocio, colas Celery, tareas programadas, servicios de negocio | 7–10, Ap. B | Pendiente |
| 5 | IA | Factoría multi-proveedor, prompts en BD, costes, RAG, agente con herramientas, chat SSE | 11–15, Ap. C y E | Pendiente |
| 6 | Frontend | App principal completa; después analytics y admin | 16–17 | Pendiente |
| 7 | Testing y calidad | Tests de integración, seguridad y calidad de IA | 18–20 | Pendiente |
| 8 | Despliegue y operación | CI/CD, `docker-compose.prod.yml`, TLS, observabilidad | 21–22, Ap. D | Pendiente |
| 9 | BI y documentación | Analytics (heatmap, embudo, ROI) y documentación | 23–24 | Pendiente |

## Del núcleo mínimo a los 17 servicios del libro

Se añadirán cuando la fase lo necesite: Meilisearch, `celery_beat`, workers separados
por cola (`celery_default`, `celery_ai`, `celery_automation`), frontales de analytics y
admin, y Selenium Grid con 3 nodos de Chrome en una red `rpa_net` aislada.

## Diferencias deliberadas con el libro

- Una sola instancia de MySQL con 3 esquemas (el libro usa 3 instancias en producción).
- Modelos de Claude actualizados a la generación vigente (`claude-sonnet-5-5`,
  `claude-opus-5-5`, `claude-haiku-5-5`); se cambian en `.env`.
