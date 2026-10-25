# Manual de usuario

Guía de uso de la plataforma para quien trabaja con ella cada día. Para instalarla y
operarla, mira [despliegue.md](despliegue.md) e [incidencias.md](incidencias.md).

## 1. Entrar y moverse

**Dirección:** la de tu empresa (en local, http://localhost:8080). Hay tres aplicaciones y
cada persona ve solo las que su rol permite:

| Aplicación | Dirección | Para qué |
| --- | --- | --- |
| Operaciones | `/` | Oportunidades, documentos, propuestas, copiloto, clientes y talento |
| Analítica | `/analytics/` | Cuadro de mando, mapa de oportunidad, competidores, objetivos y valor de la IA |
| Administración | `/admin/` | Usuarios, roles, modelos y costes de IA, prompts, agentes, búsqueda, tareas y auditoría |

Se cambia de aplicación en el selector de abajo a la izquierda. Debajo está **Mi cuenta**
y **Cerrar sesión**.

**Primer acceso.** Entra con tu email y la contraseña que te hayan dado. Después, en
**Mi cuenta**:

1. Cambia la contraseña (mínimo 12 caracteres; al cambiarla se cierran tus otras sesiones).
2. Activa la verificación en dos pasos (MFA): escanea el código QR con una aplicación de
   autenticación (Google Authenticator, Microsoft Authenticator, 1Password…) y escribe el
   código de 6 cifras.
3. Guarda los 10 **códigos de respaldo** en un sitio seguro. Se muestran una sola vez y
   sirven para entrar si pierdes el móvil.

**Si no puedes entrar:**
- Tras 5 intentos fallidos la cuenta se bloquea 15 minutos.
- Sin el móvil, usa un código de respaldo en lugar del código de 6 cifras.
- Sin móvil ni códigos, pide a quien administre la plataforma que te restablezca el MFA.
- Si olvidaste la contraseña, pide una provisional a administración y cámbiala al entrar.

Nunca compartas tu contraseña ni la escribas en un chat o un correo: nadie de soporte te
la pedirá.

**La sesión** dura como mucho 8 horas; después hay que entrar de nuevo. En un ordenador
compartido, usa siempre **Cerrar sesión** al terminar.

## 2. Operaciones

### Inicio
Resumen de tu día: oportunidades que **cierran pronto**, las **nuevas más relevantes**,
**tus propuestas en curso** (y las que **esperan tu revisión**) y tus **avisos**.

### Barra de búsqueda
Arriba en todas las pantallas. Admite dos tipos de frase:
- **Búsqueda:** «licitaciones de ciberseguridad que cierran este mes», «cliente Ayuntamiento».
  Entiende filtros (estado, línea, sector, fechas, importe) y te lleva a los resultados.
- **Pregunta:** «¿qué certificaciones pide el pliego de…?». Responde con los documentos que
  puedes ver y cita de dónde lo saca.
- **Acción:** «crea una propuesta para…». Te propone la acción con un botón; **nunca la hace
  sola**.

### Oportunidades
Cada oportunidad avanza por cinco fases:

| Fase | Estados |
| --- | --- |
| F1 · Detección | Detectada, cualificando |
| F2 · Cualificación | Cualificada, analizando |
| F3 · Decisión | GO/NO-GO |
| F4 · Propuesta | Preparando propuesta, en revisión, enviada, negociación |
| F5 · Cierre | Ganada o perdida |

Además se puede **descartar** en casi cualquier momento (con motivo) y reabrir después.

En el listado puedes filtrar por estado, fase, responsable, cliente, línea, puntuación y
plazo; los filtros quedan en la dirección, así que puedes guardarla o compartirla.

En la ficha de una oportunidad:
- **Cambiar estado** con los botones (solo aparecen los pasos permitidos).
- **Relevancia:** puntuación de 0 a 10 y de dónde sale. «Recalcular» la vuelve a calcular.
- **Análisis GO/NO-GO con IA:** lee los documentos vinculados y propone ir o no ir, con
  requisitos, riesgos y una recomendación. Tarda unos minutos y te llega un aviso al terminar.
- **Documentos** vinculados (pliegos, anexos) y **propuestas** creadas desde ella.
- **Oportunidades parecidas**, para reutilizar lo aprendido.

Solo el responsable (o quien tenga permiso de gestión) puede modificarla. Si otra persona la
ha cambiado mientras la editabas, verás un aviso de conflicto: recarga y vuelve a guardar.

### Documentos
Sube PDF, DOCX, TXT, MD o CSV. Al subirlo se extrae el texto y la IA lo resume y lo
cataloga (palabras clave y entidades). Si ya existe un fichero idéntico, te lleva al que hay.

En la ficha: texto extraído, **resumen de la IA**, **pregunta sobre este documento**,
versiones y oportunidades vinculadas. Un documento puede restringirse a ciertos roles; para
el resto no existe, tampoco en búsquedas ni en respuestas de la IA.

### Propuestas
Flujo: **borrador → en revisión → aprobada → enviada → ganada o perdida → archivada**.

1. Créala desde la oportunidad, eligiendo el tipo (base, premium, ejecutiva, a medida o
   competitiva) y la plantilla.
2. **Redactar con IA:** elige las secciones y, si quieres, añade instrucciones. La IA solo
   rellena lo que no has editado a mano, salvo que marques esa sección.
3. Edita las secciones. Lo que redacta la IA lleva la marca «Generado con IA»: revísalo.
4. **Revisiones:** según el tipo, hace falta la técnica, la ejecutiva o la de área. Quien
   revisa aprueba o rechaza con comentario.
5. Al aprobarse se genera el **paquete final** (DOCX, PDF y presentación PPTX). Te llega un
   aviso cuando está listo.
6. **Enviar** la marca un gestor, con el importe total.

**CV a medida:** desde la propuesta, elige un perfil de Talento y la IA adapta su CV a la
oportunidad (DOCX y PDF).

### Copiloto
Un chat que conoce tus oportunidades, documentos, clientes y propuestas. Puedes mencionar
registros con `@oportunidad:12`, `@documento:5`, `@cliente:3` o `@propuesta:7`.

- Las consultas (buscar, resumir, comparar) las hace directamente.
- Lo que cambia datos o cuesta dinero (analizar, crear o redactar una propuesta, CV a medida,
  exportar el paquete) se **detiene y te pide aprobación**. Tienes 15 minutos para aprobar
  o rechazar.
- **Lo que el copiloto recuerda de ti:** preferencias que guarda para próximas
  conversaciones. Puedes editarlas o borrarlas cuando quieras.
- Tus conversaciones son solo tuyas. Puedes exportarlas o borrarlas.

### Clientes y talento
- **Clientes:** ficha con sector, segmento (A, B, C), riesgo, contactos y proyectos.
- **Talento:** perfiles profesionales con familia, seniority, habilidades y disponibilidad,
  que se usan para los CV a medida.

### Avisos
La campana muestra los avisos sin leer: análisis terminados, paquetes listos, plazos que se
acercan y alertas. Los de prioridad alta o urgente también llegan por correo si tu empresa
lo tiene configurado.

## 3. Analítica

Todas las cifras se calculan con los datos de Operaciones. Los filtros (periodo, línea,
sector) se guardan en la dirección. Cada gráfico tiene **Ver tabla** y muchos, **Descargar CSV**.

- **Cuadro de mando:** cartera abierta y ponderada, oportunidades nuevas, ganado y tasa de
  éxito, con la **variación frente al periodo anterior** (▲ ▼). Además: objetivos frente a lo
  real, evolución semanal de la cartera, embudo por fases, evolución mensual, desglose por
  línea y sector, clientes con más cartera y propuestas.
- **Pregunta a tus datos** (al final del cuadro de mando, si tu rol lo tiene): pregunta en
  lenguaje normal, por ejemplo «¿qué línea ha crecido más?». La IA solo ve las cifras de la
  pantalla, el mapa de oportunidad y los competidores; no ve datos personales.
- **Mapa de oportunidad:** puntuación de 0 a 100 por sector y línea de servicio. Combina
  demanda, tracción (si crece), valor económico y capacidad de ganar. **Es relativa:** 100 es
  el mejor cruce del mes, no una nota absoluta. Pulsa una celda para ver de dónde sale.
  Con permiso, puedes cambiar los **pesos** (deben sumar 100) y **recalcular**.
- **Competidores:** ficha con tipo, web, líneas y sectores en los que compite, precio frente
  al nuestro y su DAFO (fortalezas, debilidades, oportunidades y amenazas).
- **Objetivos:** objetivos mensuales de oportunidades nuevas, importe nuevo, oportunidades
  ganadas e importe ganado, para el total o por línea.
- **Importar desde Excel** (en Objetivos): descarga la plantilla, rellénala, pulsa
  **Comprobar** y revisa los errores por hoja y fila. Si no hay errores, pulsa **Importar**:
  se guarda todo o nada.
- **Valor de la IA:** tiempo ahorrado y coste de la IA por tipo de tarea y por mes (en euros).

## 4. Administración

Solo para perfiles de administración. Cada sección aparece según tus permisos.

| Sección | Qué se hace |
| --- | --- |
| Usuarios | Altas, acceso a cada aplicación con su rol, bajas y reactivaciones, restablecer el MFA |
| Roles y permisos | Qué puede hacer cada rol en cada módulo y qué funciones de IA tiene |
| Modelos y costes | Modelo de cada tarea de IA, precios, presupuestos y alertas de gasto, uso y calidad |
| Prompts | Versiones de las instrucciones de la IA: probar, publicar y volver a una anterior |
| Agentes | Agentes del copiloto: herramientas, pruebas, versiones y métricas |
| Búsqueda | Estado de los índices, reindexar, patrones de intención y calidad de la búsqueda |
| Tareas | Colas en segundo plano y tareas fallidas (reintentar o marcar como revisadas) |
| Auditoría | Registro de accesos, cambios y acciones sensibles |
| Estado | Salud de cada servicio de la plataforma |

**Buenas prácticas:**
- Da a cada persona el rol mínimo que necesite; el resto está denegado.
- Antes de activar un prompt nuevo, pruébalo con la vista previa.
- Revisa cada semana las tareas fallidas y las alertas de presupuesto.
- Las bajas son lógicas: la persona deja de entrar, pero su historial se conserva.

## 5. La IA en la plataforma

- Todo lo generado con IA lleva la marca **«Generado con IA · revísalo antes de usarlo»** en
  pantalla y en los ficheros. Tú eres responsable de lo que envías.
- La IA solo recibe los documentos que **tú** puedes ver.
- Lo que escribes se revisa antes de enviarlo: se bloquean intentos de manipular a la IA y
  se ocultan datos personales que no hacen falta.
- Cada uso queda registrado con su coste. Si se agota un presupuesto, la función se pausa
  hasta que un administrador lo amplíe.
- Puedes valorar las respuestas (1 a 5). Ayuda a mejorar los prompts.

## 6. Preguntas frecuentes

**No veo una opción que usa un compañero.** Tu rol no la incluye. Pídelo a administración.

**«Otra persona ha modificado este registro».** Alguien guardó antes que tú. Recarga la
página, revisa sus cambios y vuelve a aplicar los tuyos.

**«Demasiadas peticiones seguidas».** Hay un límite por minuto para proteger la plataforma.
Espera unos segundos.

**La IA dice que no tiene información suficiente.** No ha encontrado nada en los documentos
que puedes ver. Sube o vincula el documento que contiene la respuesta.

**El análisis o el paquete no llega.** Van en segundo plano y avisan al terminar. Si pasan
más de 15 minutos, avisa a administración (Tareas → fallidas).

**Veo cifras antiguas tras una actualización.** Recarga con Ctrl+F5.
