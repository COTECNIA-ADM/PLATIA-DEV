# Requisitos — caso de negocio B2B

Caso de estudio del libro (capítulos 1 y 4): automatizar el ciclo comercial B2B,
desde que llega un documento de requisitos de un cliente hasta que se entrega la
propuesta. Hoy ese ciclo consume entre 50 y 120 horas de trabajo por propuesta.

Este documento es la referencia funcional del proyecto. Cada componente del sistema
tiene que poder justificarse con uno de los pasos de abajo.

## 1. Proceso actual (manual)

| Paso | Qué hace hoy una persona | Tiempo de referencia |
| --- | --- | --- |
| P1 | Recibe un documento de requisitos (PDF o DOCX, a veces escaneado) de 100–300 páginas | — |
| P2 | Lo analiza: criterios ponderados, plazos, condiciones económicas, restricciones técnicas | ~8 h por documento |
| P3 | Decide GO/NO-GO según el análisis, la carga de trabajo y la probabilidad de éxito | incluido en P2 |
| P4 | Busca propuestas anteriores parecidas para reutilizar | 1–2 h |
| P5 | Selecciona profesionales cuyo perfil encaje con lo pedido | ~45 min por CV |
| P6 | Redacta la propuesta técnica con lo anterior y los precios | ~40 h |
| P7 | Carga la propuesta en portales externos mediante formularios web | variable |
| P8 | Busca nuevas oportunidades en fuentes públicas y portales | ~2 h al día |

## 2. Usuarios y roles

| Rol | Quién es | Qué necesita | Aplicación |
| --- | --- | --- | --- |
| Operativo | Consultores y analistas que preparan propuestas a diario | Rapidez: documentos, análisis, propuestas, chat con IA, oportunidades | Principal (`/`) |
| Analista de negocio | Dirección comercial y analistas | Métricas, embudo de ventas, cobertura de servicios, rentabilidad | Analytics (`/analytics`) |
| Administrador | Responsables de la plataforma | Usuarios y roles, configuración de IA, costes, auditoría, cumplimiento | Admin (`/admin`) |

## 3. Requisitos funcionales

| Id | Requisito | Paso | Fase |
| --- | --- | --- | --- |
| RF-01 | Subir documentos PDF/DOCX de hasta 300 páginas, con OCR para escaneados | P1 | 4 |
| RF-02 | Versionar documentos y guardar su estado de procesamiento (pendiente, procesando, procesado, fallido) | P1 | 2 |
| RF-03 | Analizar un documento con IA y guardar el resultado como un objeto propio, reutilizable y relanzable | P2 | 5 |
| RF-04 | Proponer GO/NO-GO con su justificación, que el usuario confirma o corrige | P3 | 5 |
| RF-05 | Buscar documentos y propuestas similares por significado (búsqueda semántica) | P4 | 5 |
| RF-06 | Buscar perfiles (CV) que encajen con los requisitos, con puntuación | P5 | 5 |
| RF-07 | Generar un borrador de propuesta (5 tipos) por secciones, editable y con revisión | P6 | 4–5 |
| RF-08 | Exportar propuestas e informes a PDF, DOCX y PPTX | P6 | 4 |
| RF-09 | Automatizar la carga en portales externos con credenciales cifradas | P7 | posterior |
| RF-10 | Detectar oportunidades nuevas de forma periódica y avisar cuando superen un umbral de relevancia | P8 | posterior |
| RF-11 | Chat con IA sobre la documentación propia, con respuesta en streaming | P2–P6 | 5 |
| RF-12 | Gestionar clientes, proyectos y oportunidades (embudo F1–F5) | todos | 4 |
| RF-13 | Panel de administración: usuarios, roles, prompts, modelos, costes y auditoría | todos | 3, 5, 6 |
| RF-14 | Paneles de negocio: embudo, heatmap sector × servicio, ROI de la IA | todos | 9 |

## 4. Requisitos no funcionales

| Id | Requisito |
| --- | --- |
| RNF-01 | Las operaciones de IA (de 2 a 60 s) nunca bloquean la API: se encolan y devuelven un identificador de tarea (HTTP 202) |
| RNF-02 | Las respuestas interactivas de Claude llegan en streaming (SSE) |
| RNF-03 | Cada llamada a un LLM queda registrada: modelo, tokens, coste, latencia, versión del prompt, usuario |
| RNF-04 | Presupuesto mensual de IA con aviso, limitación y bloqueo graduales |
| RNF-05 | Guardarraíles: detección de inyección de prompts a la entrada y filtrado de datos personales y secretos a la salida |
| RNF-06 | Autenticación con JWT de corta duración, MFA para administradores y permisos por rol en cada endpoint |
| RNF-07 | Auditoría de acciones relevantes; borrado lógico en datos de negocio; RGPD (acceso, borrado, portabilidad) |
| RNF-08 | Los datos sensibles no salen del perímetro: base vectorial y bases de datos alojadas por nosotros |
| RNF-09 | Credenciales de portales externos cifradas y accesibles solo por el worker de automatización, en red aislada |
| RNF-10 | Secretos solo en variables de entorno; nada en el código ni en el repositorio |
| RNF-11 | El proveedor de LLM se puede cambiar o tener de respaldo sin tocar la lógica de negocio |
| RNF-12 | Los prompts se editan desde el panel de administración sin redesplegar |

## 5. Objetivos medibles

Tomados de los resultados que el libro documenta; servirán para el ROI de la fase 9.

| Tarea | Antes | Objetivo |
| --- | --- | --- |
| Análisis de un documento complejo | ~8 h | menos de 30 min, incluida la revisión humana |
| Propuesta técnica | ~40 h | 4–6 h |
| Análisis de un CV | ~45 min | 2–3 min |
| Búsqueda de oportunidades | ~2 h al día | automática |

## 6. Decisiones que salen del análisis de requisitos

1. **El análisis es un objeto persistido.** P3 (GO/NO-GO) y P4 (similares) dependen de P2. Si el
   análisis se guarda como un registro propio, ambos flujos lo leen por separado y un fallo
   solo obliga a relanzar el análisis, no todo el proceso.
2. **La automatización vive aislada.** P7 maneja credenciales de terceros: worker propio, red
   Docker propia sin acceso a las bases de datos y un almacén de credenciales cifrado.
3. **La búsqueda de oportunidades es una tarea programada.** P8 no depende del usuario: la
   ejecuta Celery Beat, puntúa por relevancia y genera alertas.

## 7. Alcance de esta reproducción

- **Primero:** P1–P6 y el chat (RF-01 a RF-08, RF-11 a RF-13), que es donde está el mayor ahorro.
- **Después:** RF-09 (RPA con Selenium), RF-10 (alertas proactivas) y RF-14 (BI).
- **Datos:** se usarán documentos, clientes y CV ficticios; ningún dato real de terceros.
