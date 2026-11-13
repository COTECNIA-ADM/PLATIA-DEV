# Flujos de n8n para el portal Low-Code

Flujos de n8n que se importan en el editor (**Import from File**). Ninguno lleva secretos:
las claves van en credenciales de n8n que se crean a mano (ADR-020 y `docs/despliegue.md`,
apartado 11). Los tests (`backend/tests/test_automation_workshop.py`) pasan a todos las
mismas comprobaciones que el taller de PLATIA antes de publicar.

Credenciales que usan:

| Credencial en n8n | Tipo | Para qué |
| --- | --- | --- |
| PLATIA · clave del webhook | Header Auth (`X-Platia-Webhook-Key`) | El Webhook solo acepta llamadas de PLATIA |
| PLATIA · clave de integración | Header Auth (`X-Platia-Integration-Key`) | La respuesta del flujo a PLATIA |
| PLATIA · correo SMTP | SMTP | Enviar correos (plantillas P1, P6 y el acuse de P2) |

## Ejemplo

- `ejemplos/prueba-ida-y-vuelta.json`: devuelve a PLATIA los datos que recibe. Sirve para
  comprobar la conexión en las dos direcciones. Ficha sin campos o con los que quieras.

## Plantillas de los primeros casos

Antes de publicarlas, cambia el remitente (`avisos@tu-empresa.es`) del nodo «Enviar correo».
Si el correo falla, el flujo avisa a PLATIA y la ejecución queda como fallida con el motivo.

**P1 · Aviso de oportunidad por correo** (`plantillas/p1-aviso-oportunidad-correo.json`).
Campos de la ficha:

| Nombre | Etiqueta | Tipo | Obligatorio |
| --- | --- | --- | --- |
| `destinatario` | Correo de quien recibe el aviso | texto | sí |
| `titulo` | Título de la oportunidad | texto | sí |
| `organismo` | Organismo | texto | no |
| `importe` | Importe (€) | número | no |
| `plazo` | Plazo de presentación | fecha | no |
| `enlace` | Enlace a la licitación | texto | no |

**P6 · Recordatorio de plazo por correo** (`plantillas/p6-recordatorio-plazo-correo.json`).
Campos de la ficha:

| Nombre | Etiqueta | Tipo | Obligatorio |
| --- | --- | --- | --- |
| `destinatario` | Correo de quien recibe el recordatorio | texto | sí |
| `tarea` | Tarea | texto | sí |
| `fecha_limite` | Fecha límite | fecha | sí |
| `notas` | Notas | texto largo | no |

Al crear la ficha en *Automatizaciones → Taller*, PLATIA propone los nombres de los datos
que usa el flujo; solo hay que ponerles etiqueta y tipo.

## Flujo de errores

`errores/platia-flujo-de-errores.json` (id `platiaErrores01`): empieza por un «Error Trigger» y
avisa a PLATIA de cada fallo (flujo, ejecución, paso y mensaje) con la clave de integración.
Todas las plantillas de esta carpeta lo tienen puesto en *Settings → Error workflow*; si
importas un flujo con otro id, vuelve a elegirlo ahí. Los fallos aparecen en
*Automatizaciones → Monitorización* y, si el flujo se había lanzado desde PLATIA, la
ejecución se cierra como fallida en el momento.

## Flujos de entrada

No se lanzan desde PLATIA ni pasan por el Taller: recogen algo de fuera y lo entregan a
PLATIA con la clave de integración. Llevan la etiqueta `platia-entrada`, no `platia`, para
que no salgan como candidatos del catálogo. Los tests les pasan sus propias comprobaciones.

**P2 · Solicitudes del formulario web** (`entradas/p2-solicitudes-formulario-web.json`).
Formulario de n8n en `/form/platia-solicitud` (nombre, correo, teléfono, empresa, CIF,
asunto, mensaje y casilla de privacidad obligatoria). Envía el acuse a quien escribe y
entrega la solicitud en `http://backend:5000/api/leads/inbound` con `ack_sent` según haya
ido el correo; si PLATIA no responde, reintenta tres veces. La solicitud aparece en
*Operaciones → Solicitudes* y una persona decide si la convierte en contacto u oportunidad
o la descarta. Antes de publicarlo, cambia el remitente (`comercial@tu-empresa.es`) del nodo
«Enviar acuse» y, si quieres, los textos del formulario.
