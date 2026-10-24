# ADR-014: Frontal de operaciones con sesión en memoria, React Query y permisos desde `/me`

**Fecha:** 2026-10-24 · **Estado:** Aceptado

## Contexto
La fase 6 construye los capítulos 16 y 17: la aplicación web con la que el equipo trabaja
cada día (oportunidades, documentos, propuestas, copiloto, búsqueda, clientes y talento) y,
después, los paneles de analítica y administración. El backend ya hace cumplir la
seguridad; el frontal tiene que guardar la sesión sin exponerla, mostrar solo lo que el rol
permite, hablar con el streaming del copiloto y pintar texto de la IA sin abrir una puerta
a inyección de HTML.

## Decisión

**Dos entregas**
- 6a: la aplicación de operaciones (este ADR). 6b: analítica y administración, que usan
  otras cabeceras de aplicación (`X-App-Code`) y otros roles.

**Sesión**
- El token de acceso vive solo en memoria. Diferencia con el libro: **nunca en
  `localStorage`**, donde cualquier script inyectado podría leerlo.
- El refresco usa la cookie `HttpOnly` del backend (ADR-009). Una sola petición de
  refresco a la vez aunque fallen varias llamadas; si el refresco falla, la aplicación
  vuelve al acceso con un aviso de sesión caducada.
- Todas las peticiones llevan `X-App-Code: operations`.

**Permisos**
- Salen de `GET /api/auth/me` (`active_app.permissions`, `is_admin`, `ai_modules_access`),
  no del JWT. La interfaz solo oculta lo que el rol no puede hacer; quien decide es siempre
  el backend (default-deny). Modificar un objeto exige `manage` o ser su responsable, igual
  que `ensure_can_modify`.

**Datos**
- `@tanstack/react-query` para caché, reintentos (nunca en 4xx) y sondeo de tareas
  asíncronas (análisis, indexado, redacción) con `refetchInterval`.
- `react-router` en modo librería. Las rutas usan los mismos nombres que la API
  (`/opportunities/8`, `/proposals/3`), así los enlaces de las notificaciones funcionan tal
  cual. Los filtros de los listados viven en la URL.
- Cliente de API propio sobre `fetch` (sin axios). Los `PATCH` envían `version` y un 409 se
  explica a la persona.

**Copiloto**
- El streaming SSE se lee con `fetch` y `ReadableStream`, porque `EventSource` no admite
  `POST` ni cabeceras. La aprobación humana es una tarjeta con aprobar/rechazar y
  comentario opcional.

**Texto de la IA**
- Nunca `dangerouslySetInnerHTML`. Un intérprete de Markdown mínimo (títulos, listas,
  negrita, cursiva, código, citas `[n]` y enlaces internos) construye nodos React. El
  resaltado de la búsqueda solo reconoce `<mark>`.

**Estilos**
- CSS propio con variables y modo oscuro automático, sin framework. Dos dependencias
  nuevas en total, fijadas a versión exacta.

## Consecuencias
- Recargar la página cuesta una llamada de refresco, a cambio de no dejar el token al
  alcance de scripts.
- Un permiso nuevo en el backend no necesita cambios en el frontal salvo para mostrar la
  función nueva.
- Endpoint añadido para el frontal: `POST /api/proposals/{id}/cv` (CV a medida desde la
  pantalla de la propuesta, con los mismos permisos que la herramienta del copiloto).
