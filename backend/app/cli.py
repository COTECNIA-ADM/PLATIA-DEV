"""Comandos de línea de órdenes: ``flask seed``."""
import click
from flask import Flask


def register_cli(app: Flask) -> None:
    @app.cli.command("seed")
    def seed_command() -> None:
        """Carga los datos iniciales (idempotente)."""
        from .seeds import run_seeds

        created = run_seeds()
        click.echo(f"Datos iniciales aplicados: {created}")
