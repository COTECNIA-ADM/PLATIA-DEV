# Migraciones de base de datos

Las tablas se crean y cambian **solo** con migraciones Alembic (nunca `ALTER TABLE` a mano).
Hay una única cadena de migraciones para los tres esquemas; ver
[ADR-008](adr/ADR-008-migraciones-multi-bind.md).

## Qué pasa al levantar el sistema

`docker compose up` arranca el contenedor `migrations`, que ejecuta
`flask db upgrade && flask seed` y termina. El backend y Celery esperan a que acabe bien.
Los datos iniciales (`backend/app/seeds.py`) son idempotentes: solo crean lo que falta y
no pisan valores editados.

## Crear una migración nueva

1. Cambia los modelos en `backend/app/models/`.
2. Con el sistema levantado, genera la migración (el `-v` hace que el fichero aparezca
   en tu carpeta `backend/migrations/versions/`):

   ```bash
   docker compose build migrations
   docker compose run --rm -v ./backend/migrations:/app/migrations migrations flask db migrate -m "descripción corta"
   ```

3. **Revísala a mano.** Alembic propone, la persona decide. Puntos a mirar:
   - Cambios en el esquema correcto (`upgrade_core`, `upgrade_operations`, `upgrade_analytics`).
   - Columnas renombradas: Alembic las ve como borrar y crear (se perderían datos).
   - Columnas `NOT NULL` nuevas en tablas con filas: necesitan valor por defecto o un
     paso de relleno.
   - En los `downgrade`, MySQL no deja borrar un índice que usa una clave foránea
     (error 1553): borra la tabla o la clave antes.
4. Pruébala: `flask db upgrade`, `flask db downgrade -1`, `flask db upgrade`, y
   `flask db check` (no debe detectar cambios pendientes).
5. Súbela en el mismo PR que el cambio de modelos. La CI repite la prueba en MySQL 8.0.

## Comandos útiles

| Comando | Qué hace |
| --- | --- |
| `flask db current` | Versión aplicada en cada esquema |
| `flask db history` | Lista de migraciones |
| `flask db check` | Falla si los modelos y las migraciones no coinciden |
| `flask db upgrade --sql` | Genera el SQL (un fichero por esquema) sin ejecutarlo |
| `flask seed` | Aplica los datos iniciales |

Dentro de Docker: `docker compose run --rm migrations flask db current`.
