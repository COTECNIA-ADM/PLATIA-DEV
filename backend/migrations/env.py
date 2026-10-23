"""Entorno de Alembic multi-bind (Capítulo 5, ADR-008).

Basado en la plantilla ``--multidb`` de Flask-Migrate (MIT), con dos cambios:

1. Solo migra los binds con nombre (core, operations, analytics). El bind por
   defecto apunta a platform_core, igual que "core"; si se migrara también,
   habría dos historiales compitiendo en la misma base de datos.
2. Cada esquema guarda su versión en su propia tabla ``alembic_version_<bind>``.

Una revisión contiene ``upgrade_core()``, ``upgrade_operations()`` y
``upgrade_analytics()``; Alembic las aplica en su base de datos correspondiente.
Ojo: MySQL confirma cada DDL al momento, así que una migración que falle a mitad
no se deshace sola. Por eso se revisan y se prueban antes (ver docs/migraciones.md).
"""
import logging
from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config
fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")

target_db = current_app.extensions["migrate"].db
BIND_NAMES = list(current_app.config["SQLALCHEMY_BINDS"].keys())


def get_engine(bind_key):
    return target_db.engines[bind_key]


def get_engine_url(bind_key):
    return get_engine(bind_key).url.render_as_string(hide_password=False).replace("%", "%%")


def version_table(bind_key: str) -> str:
    return f"alembic_version_{bind_key}"


def configure_args(bind_key: str) -> dict:
    return {
        "target_metadata": target_db.metadatas[bind_key],
        "version_table": version_table(bind_key),
        "compare_type": True,
        "compare_server_default": True,
    }


def run_migrations_offline():
    """Genera un .sql por esquema (``flask db upgrade --sql``)."""
    for name in BIND_NAMES:
        file_ = f"{name}.sql"
        logger.info("Escribiendo SQL de %s en %s", name, file_)
        with open(file_, "w") as buffer:
            context.configure(
                url=get_engine_url(name),
                output_buffer=buffer,
                literal_binds=True,
                **configure_args(name),
            )
            with context.begin_transaction():
                context.run_migrations(engine_name=name)


def run_migrations_online():
    def process_revision_directives(context, revision, directives):
        # No genera una revisión vacía si ningún esquema ha cambiado
        # Se llama una vez por esquema; solo se decide cuando están los tres
        if getattr(config.cmd_opts, "autogenerate", False) and directives:
            script = directives[0]
            if len(script.upgrade_ops_list) >= len(BIND_NAMES) and all(
                ops.is_empty() for ops in script.upgrade_ops_list
            ):
                directives[:] = []
                logger.info("No hay cambios en el esquema.")

    conf_args = dict(current_app.extensions["migrate"].configure_args)
    conf_args.setdefault("process_revision_directives", process_revision_directives)

    connections = {name: get_engine(name).connect() for name in BIND_NAMES}
    transactions = {name: conn.begin() for name, conn in connections.items()}
    try:
        for name in BIND_NAMES:
            logger.info("Migrando esquema %s", name)
            context.configure(
                connection=connections[name],
                upgrade_token=f"{name}_upgrades",
                downgrade_token=f"{name}_downgrades",
                **{**conf_args, **configure_args(name)},
            )
            context.run_migrations(engine_name=name)
        for tx in transactions.values():
            tx.commit()
    except Exception:
        for tx in transactions.values():
            tx.rollback()
        raise
    finally:
        for conn in connections.values():
            conn.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
