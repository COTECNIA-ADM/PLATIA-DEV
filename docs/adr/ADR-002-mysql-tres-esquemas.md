# ADR-002: MySQL 8.0 con tres esquemas

**Fecha:** 2026-10-23 · **Estado:** Aceptado

## Contexto
El caso parte de una organización que ya opera MySQL 8.0, con copias de seguridad y
monitorización. Los datos tienen tres perfiles de uso: negocio, plataforma (usuarios,
auditoría, IA) y analítica.

## Decisión
- **MySQL 8.0** con tres esquemas: `operations_db`, `platform_core` y `analytics_db`.
- SQLAlchemy 2 con *multi-bind*: cada modelo declara `__bind_key__` (`operations`, `core`, `analytics`).
- En desarrollo, una sola instancia con los tres esquemas. En producción pueden ir en instancias separadas sin cambiar el código.

## Alternativas
- **PostgreSQL:** técnicamente más rico (JSON, pgvector), pero añadiría un segundo motor que operar.
- **Un único esquema:** más simple, pero mezcla copias de seguridad, cargas y permisos muy distintos.

## Consecuencias
- Copias de seguridad, permisos y carga se gestionan por separado para cada esquema.
- No hay claves foráneas reales entre esquemas: la integridad entre ellos se valida en la aplicación.
