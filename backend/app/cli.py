"""Comandos de línea de órdenes: seed, create-admin, reset-mfa y reindex."""
import click
from flask import Flask


def register_cli(app: Flask) -> None:
    @app.cli.command("seed")
    def seed_command() -> None:
        """Carga los datos iniciales (idempotente)."""
        from .seeds import run_seeds

        created = run_seeds()
        click.echo(f"Datos iniciales aplicados: {created}")

    @app.cli.command("create-admin")
    @click.option("--email", required=True, help="Email del administrador")
    @click.option("--name", "full_name", required=True, help="Nombre completo")
    def create_admin_command(email: str, full_name: str) -> None:
        """Crea el primer superadministrador. La contraseña se pide por teclado
        y no se muestra; nunca se pasa como argumento ni se guarda en claro."""
        from .extensions import db
        from .models import AuditAction, User
        from .security.audit import audit
        from .security.passwords import WeakPasswordError, hash_password, validate_password_policy

        email = email.strip().lower()
        if db.session.scalar(db.select(User).filter_by(email=email)):
            raise click.ClickException(f"Ya existe un usuario con el email {email}.")
        password = click.prompt("Contraseña", hide_input=True, confirmation_prompt="Repite la contraseña")
        try:
            validate_password_policy(password)
        except WeakPasswordError as exc:
            raise click.ClickException(str(exc)) from exc
        user = User(email=email, full_name=full_name.strip(), password_hash=hash_password(password),
                    is_superadmin=True)
        db.session.add(user)
        db.session.commit()
        audit(AuditAction.USER_CREATED, user_id=user.id, resource_type="user", resource_id=user.id,
              details={"via": "cli", "superadmin": True})
        click.echo(f"Superadministrador {email} creado. Activa el MFA tras el primer login.")

    @app.cli.command("reset-mfa")
    @click.option("--email", required=True)
    def reset_mfa_command(email: str) -> None:
        """Desactiva el MFA de un usuario que ha perdido el móvil y los códigos de respaldo.
        Queda auditado; el usuario debe volver a activarlo al entrar."""
        from .extensions import db
        from .models import AuditAction, User
        from .security.audit import audit
        from .security.sessions import revoke_user_sessions

        user = db.session.scalar(db.select(User).filter_by(email=email.strip().lower()))
        if user is None:
            raise click.ClickException("No existe ese usuario.")
        user.mfa_enabled, user.mfa_secret_encrypted, user.mfa_backup_codes = False, None, None
        db.session.commit()
        revoke_user_sessions(user.id, "mfa_reset")
        audit(AuditAction.MFA_DISABLED, "CRITICAL", user_id=user.id, details={"via": "cli"})
        click.echo(f"MFA desactivado para {user.email}. Pídele que lo active de nuevo.")

    @app.cli.command("reindex")
    def reindex_command() -> None:
        """Reconstruye los índices de búsqueda (Meilisearch) y de documentos (Qdrant) desde
        MySQL. Se usa tras restaurar una copia de seguridad: los índices no se copian
        porque se pueden regenerar. El trabajo lo hacen los workers en segundo plano."""
        from .extensions import db
        from .models import Document
        from .queue import PRIORITY_MAINTENANCE, enqueue
        from .search.indexes import SPECS
        from .tasks.ai import index_document
        from .tasks.search import rebuild_index

        for name in SPECS:
            enqueue(rebuild_index, name, priority=PRIORITY_MAINTENANCE)
        ids = db.session.scalars(db.select(Document.id).where(
            Document.is_active.is_(True), Document.extracted_text.is_not(None))).all()
        for doc_id in ids:
            enqueue(index_document, doc_id, priority=PRIORITY_MAINTENANCE)
        click.echo(f"En cola: {len(SPECS)} índices de búsqueda y {len(ids)} documentos para el RAG.")
