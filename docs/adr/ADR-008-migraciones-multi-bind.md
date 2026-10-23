# ADR-008: Modelos y migraciones en tres esquemas

**Fecha:** 2026-10-23 · **Estado:** Aceptado

## Contexto
La fase 2 crea las tablas de `platform_core`, `operations_db` y `analytics_db` (ADR-002).
Alembic, por defecto, solo conoce una base de datos, y SQLAlchemy no puede declarar
claves foráneas entre tablas de binds distintos.

## Decisión
- **Cada modelo declara `__bind_key__`** (`core`, `operations` o `analytics`). El bind por
  defecto no se usa para tablas.
- **Una sola cadena de migraciones** (plantilla `--multidb` de Flask-Migrate). Cada revisión
  tiene `upgrade_core()`, `upgrade_operations()` y `upgrade_analytics()`.
- **Una tabla de versión por esquema** (`alembic_version_core`, `_operations`, `_analytics`),
  como recomienda el capítulo 5, para que cada esquema sepa en qué versión está.
- **Sin claves foráneas entre esquemas.** `created_by`, `owner_user_id` o `user_id` en
  `operations_db` guardan el id de `platform_core.users` como entero. La integridad la
  garantiza el backend (fase 3/4), no MySQL.
- **Nombres de restricciones fijos** (`pk_`, `fk_`, `uq_`, `ix_`) para poder modificarlas
  en migraciones futuras.
- **Precios de modelos en USD por millón de tokens**, la unidad y moneda que publica el
  proveedor; el coste de cada llamada se guarda en `cost_usd`. La conversión a euros, si
  hace falta, se hará en los informes (fase 9).
- Las migraciones y los datos iniciales los aplica un contenedor de un solo uso
  (`migrations`) antes de arrancar el backend y Celery.

## Alternativas
- **Un Alembic independiente por esquema:** tres historiales que hay que coordinar a mano.
- **Claves foráneas entre esquemas con SQL a mano:** MySQL lo permite, pero rompe la
  independencia de backups y permisos que justificó ADR-002.
- **Precios en EUR por 1K tokens (como el libro):** obliga a convertir cada vez que el
  proveedor cambia precios.

## Consecuencias
- MySQL no hace transaccional el DDL: una migración que falle a mitad deja el esquema a
  medias. Por eso cada migración se revisa y se prueba (upgrade, downgrade, upgrade) antes
  de fusionarla; la CI lo hace en un MySQL real.
- Multi-tenancy queda fuera por ahora: la plataforma es para una sola empresa. Si hiciera
  falta, se añadirá con una migración y un ADR nuevo.
