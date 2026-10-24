# Versiones iniciales de los prompts

Estos ficheros solo se usan para **sembrar** la base de datos (`flask seed`) la
primera vez: si ya existe alguna versión de un prompt, no se toca. A partir de
ahí los prompts se editan y versionan desde Admin → IA → Prompts (o la API
`/api/admin/ai/prompts`), nunca aquí.

Cada prompt son dos ficheros: `<nombre>.system.md` (instrucciones estables, se
cachean) y `<nombre>.user.md` (plantilla con variables `{{variable}}`).

Redacción propia del proyecto, con la estructura que recomienda el libro
(rol, contexto, tarea, formato y restricciones); no es texto del libro.
