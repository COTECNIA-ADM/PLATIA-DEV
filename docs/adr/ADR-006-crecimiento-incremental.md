# ADR-006: Empezar con 8 contenedores y crecer con motivos concretos

**Fecha:** 2026-10-23 · **Estado:** Aceptado

## Contexto
La arquitectura de referencia del libro tiene 17 servicios más Selenium Grid, pero llegó
a ellos de forma gradual, a medida que cada pieza se quedaba corta.

## Decisión
Núcleo inicial de 8 contenedores (ver `docs/arquitectura.md`). Se separa un servicio cuando
tiene un ciclo de escalado, despliegue o fallo distinto del resto, y se registra el motivo.

## Alternativas
- **Los 17 desde el principio:** más memoria, más superficie de fallo y menos aprendizaje por fase.
- **Monolito:** separar después saldría más caro que separar ahora backend, IA y frontal.

## Consecuencias
- En desarrollo bastan unos 8 GB de RAM.
- Cada ampliación llega con un PR que explica por qué hacía falta.
