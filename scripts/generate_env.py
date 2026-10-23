#!/usr/bin/env python3
"""Crea el fichero .env a partir de .env.example con secretos aleatorios.

Uso: python scripts/generate_env.py [--force]

- Sustituye cada <GENERAR> por un secreto aleatorio distinto.
- Deja vacías las claves de proveedores externos (ANTHROPIC_API_KEY, ...):
  esas las pones tú a mano en .env.
- No sobrescribe un .env existente salvo con --force (perderías los secretos
  con los que se creó la base de datos).
"""
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"
PLACEHOLDER = "<GENERAR>"


def main() -> int:
    if TARGET.exists() and "--force" not in sys.argv:
        print(f"{TARGET} ya existe. Usa --force para regenerarlo (cambiará los secretos).")
        return 1

    lines = []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if PLACEHOLDER in line:
            # token_urlsafe: sin caracteres especiales de shell ni de URL
            line = line.replace(PLACEHOLDER, secrets.token_urlsafe(32))
        lines.append(line)

    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        TARGET.chmod(0o600)
    except OSError:
        pass
    print(f"Creado {TARGET}. Ahora edítalo y pon tu ANTHROPIC_API_KEY.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
