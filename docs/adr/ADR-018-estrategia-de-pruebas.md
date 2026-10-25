# ADR-018: Pruebas por capas que se comprueban contra el código, sin coste de IA en la CI

**Fecha:** 2026-10-25 · **Estado:** Aceptado

## Contexto
La fase 7 (capítulos 18–20) cierra la plataforma con una batería de pruebas de calidad.
Ya había unas 240 pruebas del backend y 30 del servicio de IA, pero nada en el frontal, y
la seguridad se comprobaba ruta a ruta en cada fichero. Lo que más se rompe al crecer es lo
que se olvida: un decorador en una ruta nueva, un permiso en una pantalla, una redirección
que solo falla detrás del proxy.

## Decisión

**Las reglas se comprueban leyendo el código, no listas escritas a mano**
- `test_security_matrix.py` recorre todas las rutas de Flask: decoradores obligatorios,
  401 sin sesión, 403 con un rol vacío y 403 en IA sin el módulo. Las excepciones viven en
  el test con su motivo. Los decoradores dejan una marca en la función para poder leerlos.
- Lo mismo en el frontal (`src/test/conventions.test.ts`): nada de `localStorage`, HTML
  crudo ni `fetch` fuera de `lib/api.ts`.
- Y en la documentación: `test_api_docs.py` compara la tabla de `docs/api.md` con las rutas.

**Tres capas, cada una con su herramienta**
- Backend e IA: pytest (con SQLite y Meilisearch real en la CI). Cobertura mínima en la
  CI (`--cov-fail-under`) y revisión con ruff (E9, F, B).
- Frontal: Vitest + Testing Library con una API falsa por rutas (`src/test/utils.tsx`).
  Prueban comportamiento visible: lo que se envía, lo que se muestra, quién ve qué.
- Recorrido completo: Playwright contra la plataforma levantada con `docker compose`, con
  un superadministrador creado en cada ejecución con contraseña aleatoria. Pocas pruebas
  (recorrer menús, crear cliente y oportunidad, salir, cookies y cabeceras) porque son
  lentas; encuentran lo que las otras no ven, como la configuración de Nginx.

**La IA no cuesta dinero en la CI**
- Ninguna prueba de la CI llama a Anthropic. Las de calidad de IA (fase 7c) usan
  respuestas grabadas o simuladas; la ejecución con el modelo real es un script aparte que
  se lanza a mano.

## Consecuencias
- Una ruta, pantalla o regla nueva queda cubierta sin escribir nada si cumple las
  convenciones, y falla en la CI si no las cumple.
- El trabajo E2E alarga la CI unos 10 minutos (construir las imágenes). Va en un trabajo
  aparte para no frenar el resto.
- La cobertura mínima se sube a mano cuando la real sube; no baja sin motivo.

## Alternativas descartadas
- **Cypress**: Playwright ya está en el entorno de desarrollo y prueba varios navegadores.
- **Jest**: Vitest reutiliza la configuración de Vite y no necesita Babel.
- **Pruebas de instantánea (snapshot)**: se rompen con cada cambio de estilo y no dicen
  qué comportamiento falla.
