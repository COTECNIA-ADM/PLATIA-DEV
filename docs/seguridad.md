# Seguridad e IAM

Decisiones en [ADR-009](adr/ADR-009-seguridad-iam.md). Basado en el capítulo 6 del libro.

## Primer arranque

1. Crea el primer superadministrador (te pedirá la contraseña dos veces, sin mostrarla):

   ```bash
   docker compose run --rm migrations flask create-admin --email tu@empresa.com --name "Tu Nombre"
   ```

2. Entra en http://localhost:8080 con ese email y activa el MFA desde «Tus accesos».
   Guarda los 10 códigos de respaldo: se muestran una sola vez.

La contraseña nunca se escribe en `.env`, en argumentos de comandos ni en chats.

## Aplicaciones y roles

Cada usuario tiene, como mucho, un rol por aplicación. La app activa se indica en la
cabecera `X-App-Code` (por defecto `operations`).

| App | Roles |
| --- | --- |
| operations | admin, manager, analyst, viewer |
| analytics | admin, analyst, viewer |
| admin | superadmin, admin, auditor |
| security | security_admin, security_analyst, viewer |

Los permisos de cada rol están en `backend/app/seeds.py` con la forma
`{"módulo": ["acción", ...]}`. Lo que no aparece está denegado. Los roles marcados como
administrador tienen todos los permisos, pero solo dentro de su aplicación.

## Cómo proteger un endpoint nuevo

```python
@bp.post("/api/proposals")
@platform_guard                               # 1. sesión válida, rol leído de la BD
@require_permission("proposals", "write")     # 2. el rol lo permite
@rate_limit("RATE_LIMIT_WRITE")               # 3. 20 escrituras/min por usuario
def create_proposal():
    ctx = g.security                          # SecurityContext: user_id, app_code, rol...
```

Límites por tipo de operación: `RATE_LIMIT_READ` (60/min), `RATE_LIMIT_WRITE` (20/min),
`RATE_LIMIT_UPLOAD` (10/min), `RATE_LIMIT_EXPORT` (5/min) y `RATE_LIMIT_AI` (10/min).

El módulo y la acción tienen que estar en `backend/app/security/registry.py`; si no, el
backend no arranca. Para modificar un registro concreto, además, `ensure_can_modify()`
comprueba que es tuyo o que tienes la acción `manage` (autorización por objeto).

## API de autenticación

| Ruta | Qué hace |
| --- | --- |
| `POST /api/auth/login` | Email y contraseña. Devuelve token de acceso o `mfa_required` |
| `POST /api/auth/mfa/verify` | Completa el login con el código TOTP o uno de respaldo |
| `POST /api/auth/refresh` | Renueva el token de acceso con la cookie (y la rota) |
| `POST /api/auth/logout` | Cierra la sesión |
| `GET /api/auth/me` | Usuario, sus apps y los permisos en la app activa |
| `POST /api/auth/password` | Cambia la contraseña y cierra todas las sesiones |
| `POST /api/auth/mfa/setup` · `enable` · `disable` | Gestión del MFA |
| `GET/POST /api/admin/users`, `PUT …/memberships/<app>`, `POST …/deactivate` | Usuarios (app admin) |
| `GET /api/admin/audit` | Últimas entradas de auditoría (app admin) |

## Qué se audita

Login correcto y fallido, bloqueo de cuenta, logout, reutilización de refresco (CRITICAL),
cambios de contraseña y MFA, accesos denegados, límites superados, altas, roles y bajas.
Todo en `platform_core.audit_log` con IP, navegador y `request_id`.

## Si te quedas fuera

- **Cuenta bloqueada** tras 5 fallos: espera 15 minutos.
- **Sin móvil para el MFA:** usa uno de los códigos de respaldo.
- **Sin códigos de respaldo:** quien administre el servidor ejecuta
  `docker compose run --rm migrations flask reset-mfa --email usuario@empresa.com`.
  Queda auditado como CRITICAL y cierra sus sesiones.
