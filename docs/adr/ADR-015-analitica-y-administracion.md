# ADR-015: Analítica y administración como tres aplicaciones en un solo frontal

**Fecha:** 2026-10-24 · **Estado:** Aceptado

## Contexto
La fase 6b completa los capítulos 16 y 17 con dos aplicaciones más: **Analítica** (cartera,
embudo, resultados y valor de la IA para dirección) y **Administración** (usuarios, roles,
modelos y costes de IA, prompts, agentes, búsqueda, tareas y auditoría). Cada una tiene sus
roles (`X-App-Code: analytics` y `admin`, ADR-009). `arquitectura.md` preveía dos
contenedores nuevos (`analytics_frontend`, `admin_frontend`). Además, el embudo real y la
fecha de cierre necesitan saber cuándo cambió de estado cada oportunidad, y hasta ahora
solo se guardaba el estado actual.

## Decisión

**Un frontal, tres aplicaciones**
- Un solo proyecto Vite con tres entradas (`/`, `/analytics/`, `/admin/`). Cada entrada fija
  su `X-App-Code` (`setAppCode`), su `basename` y su menú, y comparte el cliente de API, la
  sesión, los componentes y los estilos (`Shell`, `AccessGate`).
- Lo sirve el mismo contenedor `frontend`; su nginx devuelve el `index.html` de cada
  aplicación según la ruta. **Diferencia con `arquitectura.md`**: no hay contenedores
  `analytics_frontend` ni `admin_frontend`. Separar despliegues no aporta nada con un solo
  equipo, y duplicaría dependencias, estilos y la lógica de sesión, que es la parte delicada.
  Si un día hacen falta despliegues separados, cada entrada ya se construye por su cuenta.
- Cambiar de aplicación recarga la página: la sesión se recupera con la cookie de refresco y
  los permisos se leen de nuevo para la aplicación nueva. Sin rol en una aplicación, la
  persona ve una pantalla de «sin acceso» con enlaces a las que sí tiene.

**Historial de estados**
- Tabla `opportunity_status_changes` en `operations_db` (con auditoría y borrado lógico):
  estado de origen, de destino, quién y cuándo. Se escribe en el servicio de oportunidades
  (al crear y en cada cambio, también los que provoca una propuesta).
- La migración 0007 crea una fila por oportunidad existente con su estado actual, para que
  los datos antiguos cuenten.

**Analítica calculada al vuelo**
- `GET /api/analytics/overview` y `/ai` calculan en Python sobre MySQL, sin tablas
  agregadas ni tareas nocturnas. Con el volumen previsto (miles de oportunidades) responde
  en milisegundos. `analytics_db` se reserva para cuando el volumen lo pida.
- Definiciones: tasa de éxito = ganadas / (ganadas + perdidas) cerradas en el periodo;
  embudo = fase más alta que alcanzó cada oportunidad creada en el periodo (F5 = ganada).

**Gráficos**
- SVG propio, sin librería: columnas, barras horizontales, mapa de calor y medidores.
  Paleta categórica validada para contraste y daltonismo en claro y oscuro, rampa secuencial
  de un solo tono, tooltip con ratón y teclado, y siempre una vista de tabla con los mismos
  datos (ningún dato depende solo del color).

**Editor de roles**
- `PATCH /api/admin/roles/{id}` con bloqueo optimista (`app_roles.row_version`). Solo admite
  módulos y acciones del registro que pertenezcan a esa aplicación (`APP_MODULES`); los roles
  de administrador no se editan. Al guardar se invalida la caché de permisos de cada miembro,
  así el cambio se aplica en su siguiente petición, y queda auditado con el antes y el después.

## Consecuencias
- Un solo `npm run build` genera las tres aplicaciones; el código común se descarga una vez.
- Un permiso nuevo en `registry.py` aparece solo en la matriz de roles si se añade a
  `APP_MODULES`.
- Los listados de usuarios y auditoría pasan a `items` + `pagination` (contrato común),
  lo que cambia su forma respecto a la fase 3.
