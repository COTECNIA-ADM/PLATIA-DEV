#!/usr/bin/env python3
"""Crea el fichero .env a partir de .env.example con secretos aleatorios.

Uso: python scripts/generate_env.py [--force | --actualizar]

- Sustituye cada <GENERAR> por un secreto aleatorio distinto y cada
  <GENERAR_FERNET> por una clave Fernet válida.
- --actualizar añade a un .env existente las variables nuevas de .env.example
  (por ejemplo, al pasar de fase) sin tocar las que ya tienes.
- Deja vacías las claves de proveedores externos (ANTHROPIC_API_KEY, ...):
  esas las pones tú a mano en .env.
- No sobrescribe un .env existente salvo con --force (perderías los secretos
  con los que se creó la base de datos).
"""
import base64
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"
PLACEHOLDER = "<GENERAR>"
FERNET_PLACEHOLDER = "<GENERAR_FERNET>"


def fill(line: str) -> str:
    if FERNET_PLACEHOLDER in line:
        line = line.replace(FERNET_PLACEHOLDER, base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    if PLACEHOLDER in line:
        # token_urlsafe: sin caracteres especiales de shell ni de URL
        line = line.replace(PLACEHOLDER, secrets.token_urlsafe(32))
    return line


def _key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()


def update() -> int:
    if not TARGET.exists():
        print(f"No existe {TARGET}. Ejecuta primero: python scripts/generate_env.py")
        return 1
    current = TARGET.read_text(encoding="utf-8")
    existing = {_key(line) for line in current.splitlines()}
    added = [fill(line) for line in EXAMPLE.read_text(encoding="utf-8").splitlines()
             if _key(line) and _key(line) not in existing]
    if not added:
        print("Tu .env ya tiene todas las variables.")
        return 0
    block = "\n# --- Añadido por generate_env.py --actualizar ---\n" + "\n".join(added) + "\n"
    TARGET.write_text(current.rstrip("\n") + "\n" + block, encoding="utf-8", newline="\n")
    names = ", ".join(_key(line) for line in added)
    print(f"Añadidas {len(added)} variables a {TARGET}: {names}")
    return 0


def main() -> int:
    if "--actualizar" in sys.argv:
        return update()
    if TARGET.exists() and "--force" not in sys.argv:
        print(f"{TARGET} ya existe. Usa --force para regenerarlo (cambiará los secretos)")
        print("o --actualizar para añadir solo las variables nuevas.")
        return 1

    lines = [fill(line) for line in EXAMPLE.read_text(encoding="utf-8").splitlines()]

    # newline="\n": en Windows también LF, como espera Docker Compose
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    try:
        TARGET.chmod(0o600)
    except OSError:
        pass
    print(f"Creado {TARGET}. Ahora edítalo y pon tu ANTHROPIC_API_KEY.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
