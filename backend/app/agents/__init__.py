"""Agentes y copiloto (Capítulos 14 y 15).

- ``actor``: en nombre de quién actúa el agente y con qué permisos (de la BD).
- ``tools``: catálogo de herramientas que el código implementa; cada una declara
  su esquema, su permiso y su nivel de autonomía mínimo.
- ``definitions``: agentes definidos como datos (Agent Studio).
- ``runner``: el bucle razonar-actuar con aprobaciones, límites y registro.
- ``chat``: el copiloto: menciones, intención, historial y memoria.
"""
