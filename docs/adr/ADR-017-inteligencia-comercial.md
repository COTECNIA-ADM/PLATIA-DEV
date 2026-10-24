# ADR-017: Inteligencia comercial con puntuaciones relativas calculadas en el backend, fotos diarias e importación síncrona

**Fecha:** 2026-10-24 · **Estado:** Aceptado

## Contexto
La fase 9a completa la aplicación de Analítica (capítulo 23): un mapa de oportunidad que
diga dónde invertir el esfuerzo comercial, la comparación con el periodo anterior, los
objetivos, la ficha de competidores con su DAFO, la carga de datos desde Excel y preguntas
en lenguaje natural sobre las cifras. Los datos de origen viven en `operations_db`; los
resultados, en `analytics_db`.

## Decisión

**Mapa de oportunidad**
- Una puntuación de 0 a 100 por cruce sector × línea de servicio, media ponderada de
  cuatro dimensiones: demanda (número de oportunidades), tracción (mitad reciente frente a
  la anterior, con suavizado), valor económico (importe medio en escala logarítmica) y
  capacidad de ganar (tasa de éxito suavizada hacia la media con 3 cierres ficticios).
- Cada dimensión se normaliza entre las celdas del mes (mín.–máx.). La puntuación es
  **relativa**: 100 es el mejor cruce, no un umbral absoluto. Es lo que sirve para
  priorizar y no depende de calibrar umbrales por empresa.
- Pesos y ventana (3-36 meses) en `heatmap_config`, editables desde la pantalla con
  bloqueo optimista. Cambiarlos recalcula el mes en curso.
- Se calcula en el backend (`app/services/market.py`) y se guarda por mes en
  `heatmap_scores` (tarea nocturna `tasks.analytics.compute_heatmap`; el día 1 cierra
  también el mes anterior). Los meses pasados se conservan tal como quedaron.
- Las oportunidades sin sector o sin línea no puntúan; se cuentan aparte.

**Comparación y evolución**
- Los indicadores de flujo (nuevas, ganadas, tasa de éxito) se recalculan para el periodo
  anterior del mismo tamaño.
- La cartera abierta es un estado, no un flujo: no se puede reconstruir hacia atrás. Se
  guarda una foto diaria (`tasks.analytics.take_snapshot`, 23:50) en `analytics_snapshots`
  y la comparación usa la foto más cercana. Sin foto, no hay comparación (no se inventa).
- Las fotos guardan el total y el desglose por fase; con filtros de línea o sector no
  hay comparación de cartera.

**Objetivos y competidores**
- Objetivos mensuales por métrica (`new_count`, `new_eur`, `won_count`, `won_eur`) y
  línea de servicio opcional (cadena vacía = total), con unicidad por métrica, mes y línea.
- Competidores con el DAFO, las líneas y los sectores como listas JSON: son decenas de
  fichas y no se consultan por esos campos en SQL. Nuevo módulo de permisos `competitors`.
- Las líneas y los sectores se guardan por **código**, no por id, igual que en las
  oportunidades: el Excel se puede rellenar a mano.

**Importación desde Excel**
- Síncrona y con límites (5 MB, 2.000 filas por hoja, solo `.xlsx`), en lugar de una
  tarea Celery: con estos tamaños tarda menos de un segundo y así el resultado se ve al
  momento.
- Dos pasos: primero se comprueba (`dry_run`) y se devuelven los errores por hoja, fila y
  columna; después se aplica todo o nada. Columnas desconocidas son un error (no se
  ignoran en silencio). Se registra en auditoría.

**Pregunta a tus datos**
- La IA no consulta la base de datos ni escribe SQL: recibe un resumen ya calculado
  (indicadores, comparación, objetivos, embudo, desgloses, mejores celdas del mapa y
  competidores), limitado a 30.000 caracteres, y responde solo con eso.
- Son datos agregados de negocio, sin datos personales. Pasa por la pasarela
  (`analytics_qa`), los guardarraíles de entrada y salida y el registro de ROI, y se
  activa por rol con el módulo de IA `analytics_assistant`.

## Consecuencias
- Una puntuación alta no significa «buen mercado» en absoluto, sino «mejor que el resto
  este mes»; la pantalla lo explica y muestra los datos de cada celda.
- La comparación de cartera empieza a funcionar al día siguiente de instalar la fase; la
  evolución semanal necesita dos semanas de fotos.
- Si los ficheros de importación crecieran mucho (decenas de miles de filas), habría que
  pasar la importación a una tarea en segundo plano.
- Texto a SQL quedaría más flexible, pero abriría la puerta a consultas sobre datos que la
  persona no puede ver; se descarta mientras el resumen cubra las preguntas habituales.
