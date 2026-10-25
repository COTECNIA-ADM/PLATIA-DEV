"""Comandos de línea de órdenes: seed, create-admin, reset-mfa, reset-password, reindex y eval-ai."""
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

    @app.cli.command("reset-password")
    @click.option("--email", required=True)
    def reset_password_command(email: str) -> None:
        """Pone una contraseña provisional a quien ha olvidado la suya (fase 9b).
        Se teclea sin mostrarse; cierra sus sesiones y queda auditado como CRITICAL.
        La persona debe cambiarla en «Mi cuenta» al entrar."""
        from .extensions import db
        from .models import AuditAction, User
        from .security.audit import audit
        from .security.passwords import WeakPasswordError, hash_password, validate_password_policy
        from .security.sessions import revoke_user_sessions

        user = db.session.scalar(db.select(User).filter_by(email=email.strip().lower()))
        if user is None:
            raise click.ClickException("No existe ese usuario.")
        password = click.prompt("Contraseña provisional", hide_input=True,
                                confirmation_prompt="Repite la contraseña")
        try:
            validate_password_policy(password)
        except WeakPasswordError as exc:
            raise click.ClickException(str(exc)) from exc
        user.password_hash = hash_password(password)
        user.failed_login_count, user.locked_until = 0, None  # y la desbloquea
        db.session.commit()
        revoke_user_sessions(user.id, "password_reset")
        audit(AuditAction.PASSWORD_CHANGED, "CRITICAL", user_id=user.id, details={"via": "cli"})
        click.echo(f"Contraseña provisional puesta a {user.email}. Dásela por un canal seguro "
                   "y pídele que la cambie al entrar.")

    @app.cli.command("eval-ai")
    @click.option("--suite", "suites", multiple=True,
                  type=click.Choice(["prompts", "guardarrailes", "intencion", "rag"]),
                  help="Suites a pasar (se puede repetir). Por defecto, todas.")
    @click.option("--max-usd", default=0.5, show_default=True, type=click.FloatRange(min=0),
                  help="Gasto máximo en IA de esta evaluación, en dólares.")
    @click.option("--juez", is_flag=True, help="Puntúa además las respuestas del RAG con el modelo (rag.evaluate).")
    @click.option("--salida", type=click.Path(dir_okay=False, writable=True),
                  help="Guarda el informe completo en JSON en este fichero.")
    def eval_ai_command(suites: tuple[str, ...], max_usd: float, juez: bool, salida: str | None) -> None:
        """Evalúa la IA con el modelo real: intención, RAG e inyección (fase 7c).

        Las suites prompts y guardarrailes no cuestan nada. Cada llamada queda en el
        registro de uso con su coste. Sale con código 1 si algo queda bajo el umbral."""
        import json

        from .evals.runner import SUITES, evaluate

        run = evaluate(suites or SUITES, max_usd=max_usd, judge=juez)
        report = run.to_dict()
        for name, suite in report["suites"].items():
            mark = "OK " if suite.get("ok") else "MAL"
            figures = {k: v for k, v in suite.items() if k in (
                "aciertos", "inyecciones_resistidas", "juez_faithfulness", "juez_hallucination", "revisados", "error")}
            click.echo(f"[{mark}] {name}: {figures}")
            for problem in suite.get("problemas", []) + suite.get("fallos", []):
                click.echo(f"      - {problem}")
            for case in suite.get("casos", []):
                if not case.get("ok"):
                    detail = case.get("problemas") or f"{case.get('obtenido')} en vez de {case.get('esperado')}"
                    click.echo(f"      - {case['id']}: {detail}")
        if run.stopped:
            click.echo(run.stopped)
        click.echo(f"Coste: {report['coste_usd']:.4f} USD en {report['llamadas']} llamadas.")
        if salida:
            with open(salida, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
            click.echo(f"Informe completo en {salida}")
        if not run.passed:
            raise SystemExit(1)

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
