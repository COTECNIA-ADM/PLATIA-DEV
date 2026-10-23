# ADR-009: Autenticación y autorización propias con JWT, MFA TOTP y roles por aplicación

**Fecha:** 2026-10-23 · **Estado:** Aceptado

## Contexto
La plataforma tiene cuatro aplicaciones (operations, analytics, admin, security) y un
mismo usuario puede tener un rol distinto en cada una (capítulo 6). Hay que decidir cómo
se autentica, dónde se guardan los tokens, cómo se comprueban los permisos y qué segundo
factor se usa.

## Decisión
- **IAM propio** sobre las tablas `apps`, `app_roles` y `user_app_memberships`, en lugar
  de Keycloak/Auth0: el modelo de roles por aplicación con permisos JSON es específico.
- **JWT**: acceso de 30 minutos en la cabecera `Authorization`; refresco de 8 horas en una
  cookie `HttpOnly`, `SameSite=Strict`, limitada a `/api/auth`. El token de acceso vive en
  memoria del navegador, nunca en `localStorage`.
- **Refresco rotatorio** con tabla `user_sessions`: cada uso revoca la sesión y crea otra
  de la misma familia. Reutilizar un token ya rotado revoca toda la familia (posible robo)
  y se audita como CRITICAL.
- **Permisos siempre desde la BD**: del token solo se usa el id de usuario. El rol y
  `is_admin` se leen de `user_app_memberships`/`app_roles`, con caché en Redis de 5 minutos
  que se invalida al cambiar roles o desactivar usuarios.
- **Default-deny**: un módulo o acción que no aparece en los permisos del rol está
  denegado; una app desconocida también. `is_admin` en un rol solo vale dentro de su app.
- **MFA con TOTP** (app de autenticación) en lugar de OTP por correo como en el libro: no
  necesita servidor de correo, funciona sin conexión y es más seguro. Secreto cifrado con
  Fernet; 10 códigos de respaldo con SHA-256 y sal propia, de un solo uso.
- **Contraseñas** con bcrypt (12 rondas), mínimo 12 caracteres con mayúsculas, minúsculas
  y números. Bloqueo de 15 minutos tras 5 fallos (contraseña o código MFA).
- **Límite de peticiones** con ventana deslizante en Redis: 5/min en login y MFA (por IP),
  30/min por usuario en el resto. Responde 429 con `Retry-After`.
- **Disponibilidad frente a seguridad cuando Redis falla**: la lista de tokens revocados
  falla cerrada (sin Redis no se aceptan tokens); el límite de peticiones falla abierto
  (el login sigue protegido por el bloqueo de cuenta en la BD).
- **El primer superadministrador** se crea con `flask create-admin`, que pide la
  contraseña por teclado: nunca va en argumentos, variables de entorno ni chats.
- Sin protección CSRF de doble envío en la cookie: `SameSite=Strict` y la ruta limitada
  impiden que otro sitio la envíe, y el refresco solo devuelve un token en el cuerpo.

## Alternativas
- **Keycloak/Auth0:** auditados y completos, pero habría que traducir el modelo multi-app.
- **Permisos dentro del JWT:** más rápido, pero un rol retirado seguiría valiendo hasta que
  caduque el token, y un token manipulado daría los privilegios que declarase.
- **OTP por correo (libro):** cómodo con correo corporativo, pero exige SMTP y depende de
  la seguridad del buzón.

## Consecuencias
- Una consulta extra por petición (rol), mitigada con la caché de Redis.
- Redis pasa a ser imprescindible para iniciar sesión y usar la API.
- Pendiente para fases posteriores: guardrails de IA, control de acceso RAG por colección
  (fase 5), Credential Vault AES-256-GCM y alertas automáticas de eventos CRITICAL (fase 4).
