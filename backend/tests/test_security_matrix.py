"""Matriz de autorización (fase 7a): se recorren TODAS las rutas de Flask.

Comprueba con el código real, no con una lista escrita a mano, que:
- toda ruta lleva ``@platform_guard``, ``@require_permission`` y ``@rate_limit``, salvo las
  excepciones de abajo, cada una con su motivo;
- sin token, toda ruta protegida responde 401;
- con un rol sin permisos, toda ruta protegida responde 403 (denegación por defecto);
- con todos los permisos pero sin módulos de IA, las rutas de IA responden 403.

Una ruta nueva que se olvide un decorador hace fallar estos tests.
"""
import pytest
from werkzeug.routing.converters import IntegerConverter

from app.extensions import db
from app.models import App, AppRole, UserAppMembership
from app.security.registry import MODULES

# Rutas sin sesión: entrar, completar el MFA, renovar con la cookie y la salud básica
PUBLIC = {"auth.login", "auth.mfa_verify", "auth.refresh", "health.quick"}
# Rutas de la propia cuenta: basta con la sesión (no dependen de un permiso del rol)
SESSION_ONLY = {"auth.me", "auth.logout", "auth.change_password", "auth.mfa_setup", "auth.mfa_enable",
                "auth.mfa_disable"}
# Sin límite por minuto, con motivo
NO_RATE_LIMIT = {
    "auth.refresh": "token de refresco firmado y de un solo uso (la reutilización revoca la familia)",
    "auth.logout": "solo cierra la sesión que presenta el token",
    "health.quick": "lo consulta el balanceador cada pocos segundos y no devuelve datos",
}


def _protected(app):
    return {e for e in app.view_functions if e != "static"} - PUBLIC - SESSION_ONLY


def _app_for(path: str) -> str:
    if path.startswith("/api/admin/"):
        return "admin"
    if path.startswith("/api/analytics/"):
        return "analytics"
    return "operations"


def _calls(app, endpoints):
    """(método, url, app) de cada ruta, con valores de ejemplo en los parámetros."""
    out = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint not in endpoints:
            continue
        values = {name: 1 if isinstance(conv, IntegerConverter) else "x"
                  for name, conv in rule._converters.items()}
        url = app.url_map.bind("localhost").build(rule.endpoint, values)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            out.append((method, url, _app_for(rule.rule)))
    return out


def _send(client, method, url, headers):
    return client.open(url, method=method, headers=headers, json={} if method != "GET" else None)


def _role(app_code: str, code: str, permissions: dict, ai_modules: list | None = None) -> None:
    app_row = db.session.scalar(db.select(App).filter_by(code=app_code))
    perms = {**permissions, "ai_modules_access": ai_modules or []}
    db.session.add(AppRole(app_id=app_row.id, code=code, name=code, permissions=perms, is_admin=False))
    db.session.commit()


def _member(user_id: int, app_code: str, role_code: str) -> None:
    app_row = db.session.scalar(db.select(App).filter_by(code=app_code))
    role = db.session.scalar(db.select(AppRole).filter_by(app_id=app_row.id, code=role_code))
    db.session.add(UserAppMembership(user_id=user_id, app_id=app_row.id, role_id=role.id))
    db.session.commit()


# ---------------------------------------------------------------- Decoradores
def test_every_route_has_guard_permission_and_rate_limit(app):
    missing = []
    for endpoint in sorted(_protected(app)):
        fn = app.view_functions[endpoint]
        if not getattr(fn, "platform_guard", False):
            missing.append(f"{endpoint}: falta @platform_guard")
        if not getattr(fn, "required_permission", None):
            missing.append(f"{endpoint}: falta @require_permission")
        if not getattr(fn, "rate_limit", None):
            missing.append(f"{endpoint}: falta @rate_limit")
    assert not missing, "\n".join(missing)


def test_exceptions_are_still_what_they_say(app):
    for endpoint in SESSION_ONLY:
        assert getattr(app.view_functions[endpoint], "platform_guard", False) or endpoint == "auth.logout", endpoint
    for endpoint in sorted(PUBLIC | SESSION_ONLY):
        has_limit = getattr(app.view_functions[endpoint], "rate_limit", None) is not None
        assert has_limit or endpoint in NO_RATE_LIMIT, f"{endpoint}: sin @rate_limit y sin motivo"
    assert set(NO_RATE_LIMIT) <= PUBLIC | SESSION_ONLY


# ---------------------------------------------------------------- Sin sesión
def test_without_token_every_protected_route_is_401(app, client):
    wrong = []
    for method, url, app_code in _calls(app, _protected(app) | (SESSION_ONLY - {"auth.logout"})):
        resp = _send(client, method, url, {"X-App-Code": app_code})
        if resp.status_code != 401:
            wrong.append(f"{method} {url}: {resp.status_code}")
    assert not wrong, "Responden sin sesión:\n" + "\n".join(wrong)


def test_garbage_token_is_401_everywhere(app, client):
    headers = {"Authorization": "Bearer no-es-un-jwt"}
    wrong = [f"{m} {u}: {r.status_code}" for m, u, a in _calls(app, _protected(app))
             if (r := _send(client, m, u, {**headers, "X-App-Code": a})).status_code != 401]
    assert not wrong, "\n".join(wrong)


# ---------------------------------------------------------------- Denegación por defecto
@pytest.fixture()
def no_permissions(make_user, login):
    """Persona con un rol vacío en las tres aplicaciones."""
    user = make_user("vacio@example.com")
    for app_code in ("operations", "analytics", "admin"):
        _role(app_code, "sin_permisos", {})
        _member(user.id, app_code, "sin_permisos")
    return login("vacio@example.com")


def test_role_without_permissions_gets_403_everywhere(app, client, no_permissions):
    wrong = []
    for method, url, app_code in _calls(app, _protected(app)):
        resp = _send(client, method, url, {**no_permissions, "X-App-Code": app_code})
        if resp.status_code != 403:
            wrong.append(f"{method} {url}: {resp.status_code}")
    assert not wrong, "Responden a un rol sin permisos:\n" + "\n".join(wrong)


def test_role_without_permissions_can_still_use_its_account(client, no_permissions):
    assert client.get("/api/auth/me", headers=no_permissions).status_code == 200


def test_ai_routes_need_the_ai_module_even_with_every_permission(app, client, make_user, login):
    every = {module: sorted(actions) for module, actions in MODULES.items()}
    user = make_user("sin-ia@example.com")
    for app_code in ("operations", "analytics", "admin"):
        _role(app_code, "todo_sin_ia", every, ai_modules=[])
        _member(user.id, app_code, "todo_sin_ia")
    headers = login("sin-ia@example.com")
    ai_routes = {e for e in _protected(app) if getattr(app.view_functions[e], "required_ai_module", None)}
    assert len(ai_routes) >= 10  # documentos, oportunidades, propuestas, copiloto, asistente, analítica…
    wrong = []
    for method, url, app_code in _calls(app, ai_routes):
        resp = _send(client, method, url, {**headers, "X-App-Code": app_code})
        if resp.status_code != 403:
            wrong.append(f"{method} {url}: {resp.status_code}")
    assert not wrong, "Rutas de IA sin el módulo de IA:\n" + "\n".join(wrong)
