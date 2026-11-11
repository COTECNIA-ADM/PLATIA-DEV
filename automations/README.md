# Flujos de n8n para el portal Low-Code

Flujos de n8n que se pueden importar en el editor (**Import from File**). Ninguno lleva
secretos: las claves van en credenciales de n8n que se crean a mano (ADR-020 y
`docs/despliegue.md`, apartado 11).

- `ejemplos/prueba-ida-y-vuelta.json`: recibe la llamada de PLATIA y le devuelve los datos de
  entrada. Sirve para comprobar la conexión en las dos direcciones.

En la fase L3 se añadirán aquí las plantillas de los casos del catálogo, versionadas y con
comprobaciones automáticas.
