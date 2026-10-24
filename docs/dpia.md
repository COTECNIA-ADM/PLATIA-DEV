# Evaluación de impacto en la protección de datos (DPIA): borrador

> **Borrador técnico, no es un documento legal.** Lo ha preparado el equipo que construye
> la plataforma a partir de lo que el software hace. Debe revisarlo y completarlo la
> persona responsable de protección de datos (DPD) antes de usar la plataforma con datos
> reales. Los puntos que necesitan una decisión o un dato de la organización están marcados
> **[REVISAR]**.

| | |
| --- | --- |
| Tratamiento | Plataforma PLATIA de operaciones comerciales B2B con asistencia de IA |
| Responsable del tratamiento | **[REVISAR]** razón social, CIF y contacto |
| DPD | **[REVISAR]** nombre y contacto |
| Versión | 0.1 · 2026-10-24 · borrador |
| Revisión prevista | Antes de la puesta en producción y, después, una vez al año o con cada cambio relevante |

## 1. ¿Hace falta una DPIA?

El art. 35 del RGPD la exige cuando un tratamiento puede suponer un alto riesgo. Aquí
concurren varios criterios de las directrices del CEPD y de la lista de la AEPD:

- **Tecnología nueva:** modelos de lenguaje que leen documentos, redactan textos y
  proponen acciones (copiloto con agentes).
- **Evaluación de personas:** la IA adapta CV de profesionales a oportunidades y el
  sistema ordena perfiles por habilidades y disponibilidad.
- **Datos de empleados** (perfiles de talento y uso de la plataforma), con desequilibrio
  de poder respecto a la empresa.
- **Transferencia internacional** al proveedor del modelo de IA.

**[REVISAR]** Confirmar la conclusión: se recomienda hacer la DPIA completa.

## 2. Descripción del tratamiento

### Finalidades
1. Gestionar oportunidades comerciales, clientes, documentos de licitación y propuestas.
2. Preparar propuestas con equipos y CV adecuados a cada oportunidad.
3. Asistir con IA: análisis de pliegos, redacción, búsqueda y preguntas sobre documentos.
4. Medir la actividad comercial (analítica agregada) y el valor de la IA.
5. Garantizar la seguridad de la plataforma (control de acceso, auditoría).

### Categorías de interesados y de datos

| Interesados | Datos | Dónde | Origen |
| --- | --- | --- | --- |
| Personas usuarias (empleados) | Nombre, email, hash de la contraseña, secreto MFA cifrado, roles; IP y navegador en auditoría y sesiones | `platform_core` | Alta por administración |
| Personas usuarias | Conversaciones con el copiloto, «recuerdos» del copiloto, consultas de búsqueda, valoraciones, registros de uso de la IA con una muestra de la respuesta | `platform_core`, `operations_db` | Uso de la plataforma |
| Profesionales (talento) | Nombre, email, titular, familia, seniority, años de experiencia, resumen, habilidades, experiencias, disponibilidad, CV | `operations_db` y documentos | RR. HH. o la propia persona **[REVISAR]** |
| Contactos de clientes | Nombre, email, teléfono y cargo | `operations_db` | Relación comercial |
| Terceros en documentos | Lo que contengan pliegos, anexos y propuestas (firmantes, equipos, referencias) | Ficheros, Qdrant, Meilisearch | Clientes y organismos licitadores |

No se buscan **categorías especiales** (art. 9) ni datos de menores. Pueden aparecer
de forma incidental en documentos o CV (salud, afiliación). **[REVISAR]** Instrucción a la
plantilla para no subir CV con foto, edad, estado civil u otros datos innecesarios.

### Bases jurídicas — [REVISAR]

| Tratamiento | Base propuesta |
| --- | --- |
| Cuentas, seguridad y auditoría | Interés legítimo (art. 6.1.f) en la seguridad de los sistemas; obligación de seguridad (art. 32) |
| Perfiles de talento y CV a medida | Ejecución del contrato laboral o interés legítimo; valorar el consentimiento si los CV se envían a clientes |
| Contactos de clientes | Interés legítimo en la relación comercial B2B |
| Asistencia con IA | Interés legítimo, con prueba de ponderación **[REVISAR]** |
| Analítica | Datos agregados de negocio; sin datos personales en los resultados |

### Ciclo de vida y conservación

| Dato | Plazo | Cómo |
| --- | --- | --- |
| Notificaciones leídas | 90 días (`NOTIFICATION_RETENTION_DAYS`) | Borrado nocturno |
| IP y navegador en auditoría | 365 días (`AUDIT_ANONYMIZE_DAYS`) | Se anonimizan; la entrada se conserva |
| Muestra de respuestas de la IA | 30 días (`AI_SAMPLE_RETENTION_DAYS`) | Borrado programado |
| Consultas de búsqueda | 90 días (`SEARCH_LOG_RETENTION_DAYS`) | Borrado programado |
| Recuerdos del copiloto | Hasta 50 por persona; la persona los edita o borra | En pantalla |
| Sesiones caducadas | Borrado programado | Tarea nocturna |
| Copias de seguridad | 14 días en el servidor (`BACKUP_KEEP_DAYS`) | Rotación; la copia externa la fija la organización **[REVISAR]** |
| Datos de negocio (clientes, contactos, talento, documentos, propuestas) | Borrado lógico; **sin plazo automático** | **[REVISAR]** definir plazos y su borrado definitivo |

## 3. Flujo de datos hacia la IA

1. La persona pregunta o pide una acción. El texto pasa por **guardarraíles**: límite de
   longitud, detección de intentos de manipulación y ocultación de datos personales que no
   hacen falta.
2. El backend elige **solo los fragmentos de documentos que esa persona puede ver**
   (filtro en MySQL, en Qdrant y otra vez sobre los resultados).
3. Los **embeddings** (índice semántico) se calculan **en el propio servidor** con un modelo
   local: los documentos no salen para indexarse. (Si se cambiara `EMBEDDING_PROVIDER` a un
   servicio externo, ese proveedor pasaría a ser encargado y habría que añadirlo abajo.)
4. El servicio de IA, dentro de la red interna, envía la petición al **proveedor del modelo**
   (Anthropic, Claude) por HTTPS. **Aquí hay transferencia** de los fragmentos y de la
   pregunta.
5. La respuesta pasa el control de salida (filtración de instrucciones, datos personales) y
   se muestra con la marca «Generado con IA».
6. Se registra cada llamada (modelo, tokens, coste, latencia) y una muestra de la respuesta
   durante 30 días.

«Pregunta a tus datos» (Analítica) solo envía cifras agregadas: sin contactos ni usuarios.

**Encargados del tratamiento — [REVISAR]**

| Encargado | Qué recibe | Ubicación | Garantías |
| --- | --- | --- | --- |
| Proveedor del modelo de IA (Anthropic) | Preguntas, fragmentos de documentos, borradores | **[REVISAR]** EE. UU. u otra región | **[REVISAR]** contrato de encargo (DPA), cláusulas contractuales tipo o Marco de Privacidad de Datos UE-EE. UU., política de conservación y de no entrenamiento con datos de la API |
| Proveedor del servidor | Todo (cifrado en tránsito; en reposo **[REVISAR]**) | **[REVISAR]** | Contrato de encargo |
| Proveedor de correo (SMTP) | Email y texto de los avisos | **[REVISAR]** | Contrato de encargo |
| Almacenamiento de copias externas | Copias completas (con datos personales y secretos) | **[REVISAR]** | Cifrado antes de salir del servidor |
| Proveedor de IA de reserva (opcional, `FALLBACK_LLM_*`) | Igual que el principal | **[REVISAR]** | Solo si se activa |

## 4. Necesidad y proporcionalidad

- **Minimización:** la IA recibe fragmentos, no documentos completos, y solo los que la
  persona puede ver. Los documentos se pueden restringir por rol. La analítica trabaja con
  agregados.
- **Exactitud:** todo lo generado se marca como IA y requiere revisión humana; las acciones
  del copiloto que cambian datos necesitan aprobación expresa.
- **Limitación del plazo:** ver la tabla de conservación. Falta un plazo para los datos de
  negocio **[REVISAR]**.
- **Transparencia:** **[REVISAR]** cláusula informativa para empleados (uso de la IA, perfiles
  de talento, auditoría) y para contactos de clientes.
- **Derechos de los interesados:**
  - Acceso: `GET /api/admin/ai/gdpr/users/{id}` exporta todo el uso de la IA de una persona
    usuaria (llamadas, valoraciones, búsquedas, conversaciones, recuerdos, ejecuciones). El
    copiloto tiene también exportación propia.
  - Supresión: `POST /api/admin/ai/gdpr/users/{id}/erase` borra conversaciones y recuerdos y
    desvincula el resto (se conservan solo importes y tokens).
  - Contactos y perfiles de talento: hoy solo hay borrado lógico desde la interfaz.
    **[REVISAR]** procedimiento de supresión definitiva (y su efecto en las copias).
  - Oposición y limitación: **[REVISAR]** procedimiento.
- **Decisiones automatizadas (art. 22):** la plataforma no toma decisiones con efectos
  jurídicos sobre personas. La adaptación de CV y la ordenación de perfiles son sugerencias
  que decide una persona. **[REVISAR]** confirmarlo en el procedimiento de selección de equipos.

## 5. Riesgos

Probabilidad e impacto: B (baja), M (media), A (alta). El riesgo residual supone aplicadas
las medidas de la sección 6.

| # | Riesgo para las personas | Prob. | Impacto | Medidas | Residual |
| --- | --- | --- | --- | --- | --- |
| R1 | Acceso no autorizado a cuentas (robo de contraseña) | M | A | M1, M2, M3 | B |
| R2 | Una persona ve documentos o CV que no le corresponden, también a través de la IA | M | A | M4, M5 | B |
| R3 | Transferencia internacional al proveedor de IA sin garantías adecuadas | M | A | M6 **[REVISAR]** | M → B con DPA y cláusulas |
| R4 | El proveedor de IA conserva o reutiliza los datos | B | A | M6 **[REVISAR]** | B |
| R5 | Inyección de instrucciones en un documento que lleva a la IA a revelar datos o actuar | M | M | M7, M8 | B |
| R6 | Respuestas inexactas sobre personas (CV a medida con datos inventados) | M | M | M8, M9 | B |
| R7 | Seguimiento excesivo de la plantilla (auditoría, consultas, uso de IA) | M | M | M10 **[REVISAR]** | B |
| R8 | Conservación indefinida de contactos, perfiles y documentos | A | M | **[REVISAR]** plazos | M hasta fijarlos |
| R9 | Pérdida o robo de las copias de seguridad | B | A | M11 | B |
| R10 | Brecha no detectada o comunicada fuera de plazo | B | A | M12 | B |
| R11 | Datos personales en registros técnicos (logs) | M | B | M13 | B |

## 6. Medidas

| # | Medida | Estado |
| --- | --- | --- |
| M1 | Contraseñas de 12+ caracteres con hash bcrypt; bloqueo tras 5 fallos; MFA TOTP con códigos de respaldo | Hecho |
| M2 | Sesiones con token de acceso en memoria (30 min) y refresco rotatorio en cookie segura; reutilización detectada y revocada | Hecho |
| M3 | Auditoría de accesos, cambios y acciones sensibles, con anonimización de IP al año | Hecho |
| M4 | Permisos por rol leídos de la base de datos en cada petición, denegación por defecto, autorización por objeto | Hecho |
| M5 | La IA solo recibe documentos que la persona puede ver (triple filtro); documentos restringibles por rol | Hecho |
| M6 | Contrato de encargo con el proveedor de IA y garantías de transferencia; política de no entrenamiento | **[REVISAR]** |
| M7 | Guardarraíles de entrada y salida; agentes sin herramientas de terminal ni ficheros, catálogo cerrado | Hecho |
| M8 | Aprobación humana para toda acción del copiloto que cambia datos; marca «Generado con IA» en pantalla y ficheros | Hecho |
| M9 | Revisión humana obligatoria de las propuestas (flujo de revisiones) antes de enviarlas | Hecho |
| M10 | Informar a la plantilla; limitar quién ve la auditoría y el uso de IA por persona (rol auditor) | Técnico hecho; información **[REVISAR]** |
| M11 | Copias cifradas fuera del servidor; `.env` (secretos) solo en el servidor y en la copia | Procedimiento en `despliegue.md`; ejecución **[REVISAR]** |
| M12 | Guía de incidencias con el plazo de 72 horas y registro de brechas | Hecho (`incidencias.md`, caso 14) |
| M13 | Registros en JSON sin contraseñas ni tokens; rotación 20 MB × 5 | Hecho |
| M14 | Redes internas sin exposición: solo nginx publica puertos; HTTPS con HSTS | Hecho |

## 7. Plan de acción

| Acción | Responsable | Fecha |
| --- | --- | --- |
| Firmar o verificar el DPA con el proveedor de IA y documentar la transferencia | **[REVISAR]** | **[REVISAR]** |
| Fijar plazos de conservación de contactos, perfiles y documentos, y su borrado definitivo | **[REVISAR]** | **[REVISAR]** |
| Redactar la información a empleados y a contactos de clientes | **[REVISAR]** | **[REVISAR]** |
| Registrar el tratamiento en el registro de actividades (art. 30) | **[REVISAR]** | **[REVISAR]** |
| Programar y probar copias externas cifradas | **[REVISAR]** | **[REVISAR]** |
| Consultar a la representación de la plantilla, si procede | **[REVISAR]** | **[REVISAR]** |

## 8. Conclusión — [REVISAR]

Con las medidas técnicas ya aplicadas y las pendientes de la sección 7, el riesgo residual
se estima **bajo**, salvo la conservación de datos de negocio (R8), que queda **medio**
hasta fijar plazos. No parece necesaria la consulta previa a la autoridad de control
(art. 36), a confirmar por el DPD.

| Firma | Fecha |
| --- | --- |
| DPD: | |
| Responsable del tratamiento: | |
