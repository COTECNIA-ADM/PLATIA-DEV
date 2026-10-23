# ADR-005: Redes Docker con mínimo privilegio

**Fecha:** 2026-10-23 · **Estado:** Aceptado

## Contexto
Si se compromete un componente expuesto (proxy, frontal, bot de automatización), no debe
poder llegar directamente a las bases de datos.

## Decisión
- `frontend_net`: nginx y frontales.
- `backend_net`: nginx, backend, servicio de IA y workers.
- `data_net`: MySQL, Redis y Qdrant, más los servicios que necesitan datos.
- `rpa_net` (futura): Selenium y el worker de automatización, **sin** `data_net`.
- Solo nginx publica un puerto.

## Alternativas
- **Una sola red:** más simple, pero cualquier contenedor alcanzaría la base de datos.

## Consecuencias
- Añadir un servicio obliga a decidir explícitamente a qué redes pertenece.
- Las herramientas de administración de base de datos se usan con `docker compose exec`, no por puerto publicado.
