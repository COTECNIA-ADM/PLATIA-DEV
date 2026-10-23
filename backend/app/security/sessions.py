"""Ciclo de vida de los tokens (Capítulo 6, ADR-009).

- Acceso: 30 minutos, en la cabecera Authorization.
- Refresco: 8 horas, en cookie HttpOnly. Cada uso lo rota: la sesión anterior se
  revoca y se crea otra de la misma "familia".
- Si alguien reutiliza un token de refresco ya rotado, se asume robo: se revoca
  toda la familia y se audita como CRITICAL.
- Al revocar, la familia y el token de acceso se anotan en Redis durante lo que
  le queda de vida al token, y platform_guard los rechaza.
"""
import uuid
from datetime import timedelta

from flask import current_app, request
from flask_jwt_extended import create_access_token, create_refresh_token

from ..extensions import db
from ..models import AuditAction, User, UserSession, utcnow
from .audit import audit
from .redis_store import get_redis


def _ttl() -> int:
    return int(current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds())


def _issue(user: User, family_id: str) -> tuple[str, str]:
    claims = {"fid": family_id}
    refresh_jti = str(uuid.uuid4())
    refresh = create_refresh_token(identity=str(user.id), additional_claims={**claims, "jti": refresh_jti})
    access = create_access_token(identity=str(user.id), additional_claims=claims)
    db.session.add(
        UserSession(
            user_id=user.id,
            refresh_jti=refresh_jti,
            family_id=family_id,
            ip_address=request.remote_addr,
            user_agent=(request.user_agent.string or "")[:500] or None,
            expires_at=utcnow() + current_app.config["JWT_REFRESH_TOKEN_EXPIRES"],
        )
    )
    return access, refresh


def start_session(user: User) -> tuple[str, str]:
    tokens = _issue(user, str(uuid.uuid4()))
    db.session.commit()
    return tokens


def rotate(user_id: int, refresh_jti: str) -> tuple[str, str] | None:
    session = db.session.scalar(db.select(UserSession).filter_by(refresh_jti=refresh_jti))
    if session is None or session.user_id != user_id:
        return None
    if not session.is_active:
        if session.revocation_reason == "rotated":
            revoke_family(session.family_id, "refresh_reuse")
            audit(AuditAction.REFRESH_TOKEN_REUSE, "CRITICAL", user_id=user_id,
                  details={"family_id": session.family_id})
        return None
    if session.expires_at <= utcnow():
        return None
    user = db.session.get(User, user_id)
    if user is None or not user.is_active or user.status != "active":
        return None
    session.is_active = False
    session.revoked_at = utcnow()
    session.revocation_reason = "rotated"
    tokens = _issue(user, session.family_id)
    db.session.commit()
    return tokens


def revoke_family(family_id: str, reason: str) -> None:
    rows = db.session.scalars(db.select(UserSession).filter_by(family_id=family_id, is_active=True))
    for row in rows:
        row.is_active, row.revoked_at, row.revocation_reason = False, utcnow(), reason
    db.session.commit()
    get_redis().setex(f"revoked_family:{family_id}", _ttl(), "1")


def revoke_user_sessions(user_id: int, reason: str) -> None:
    """Cierra todas las sesiones: logout global, cambio de contraseña, desactivación."""
    families = set(
        db.session.scalars(
            db.select(UserSession.family_id).filter_by(user_id=user_id, is_active=True)
        )
    )
    for family_id in families:
        revoke_family(family_id, reason)
    if families:
        audit(AuditAction.SESSION_INVALIDATED, user_id=user_id, details={"reason": reason})


def revoke_access_token(jti: str) -> None:
    get_redis().setex(f"revoked_token:{jti}", _ttl(), "1")


def is_revoked(jwt_payload: dict) -> bool:
    """Para flask-jwt-extended. Si Redis no responde, se considera revocado (default-deny)."""
    try:
        r = get_redis()
        if jwt_payload.get("type") == "access" and r.exists(f"revoked_token:{jwt_payload['jti']}"):
            return True
        fid = jwt_payload.get("fid")
        return bool(fid and jwt_payload.get("type") == "access" and r.exists(f"revoked_family:{fid}"))
    except Exception:  # noqa: BLE001
        return True


def mfa_pending_token(user: User) -> str:
    """Token de 5 minutos que solo sirve para completar el segundo factor."""
    return create_access_token(
        identity=str(user.id),
        additional_claims={"mfa_pending": True},
        expires_delta=timedelta(minutes=5),
    )
