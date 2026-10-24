"""Detección de datos personales (PII) en texto (Capítulos 11 y 14).

Se usa en dos sitios: para sustituirlos por marcadores antes de enviar texto
libre del usuario a un proveedor externo, y en la tarea que revisa cada seis
horas las respuestas guardadas. Para reducir falsos positivos, el DNI, el NIE,
el IBAN y las tarjetas se validan con su dígito de control.
"""
import re

DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"

_DNI = re.compile(r"\b(\d{8})[ -]?([A-Za-z])\b")
_NIE = re.compile(r"\b([XYZxyz])[ -]?(\d{7})[ -]?([A-Za-z])\b")
_IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,4})?)\b")
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_PHONE = re.compile(r"(?<![\w+])(?:\+34|0034)?[ -]?[6789]\d{2}[ -]?\d{3}[ -]?\d{3}(?!\d)")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _valid_dni(m: re.Match) -> bool:
    return DNI_LETTERS[int(m.group(1)) % 23] == m.group(2).upper()


def _valid_nie(m: re.Match) -> bool:
    number = "XYZ".index(m.group(1).upper()) * 10_000_000 + int(m.group(2))
    return DNI_LETTERS[number % 23] == m.group(3).upper()


def _valid_iban(m: re.Match) -> bool:
    iban = m.group(1).replace(" ", "")
    if not 15 <= len(iban) <= 34:
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def _valid_card(m: re.Match) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", m.group(0))]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# Orden importante: lo más específico primero (un IBAN contiene grupos de dígitos)
DETECTORS = [
    ("iban", _IBAN, _valid_iban),
    ("card", _CARD, _valid_card),
    ("nie", _NIE, _valid_nie),
    ("dni", _DNI, _valid_dni),
    ("email", _EMAIL, None),
    ("phone", _PHONE, None),
]


def scan(text: str | None) -> list[str]:
    """Tipos de dato personal encontrados (sin repetir)."""
    if not text:
        return []
    found = []
    for name, pattern, validator in DETECTORS:
        if any(validator is None or validator(m) for m in pattern.finditer(text)):
            found.append(name)
    return found


def redact(text: str) -> tuple[str, list[str]]:
    """Sustituye los datos personales por ``[TIPO]`` y devuelve los tipos encontrados."""
    found: list[str] = []
    for name, pattern, validator in DETECTORS:
        def _sub(m: re.Match, name=name, validator=validator) -> str:
            if validator is None or validator(m):
                if name not in found:
                    found.append(name)
                return f"[{name.upper()}]"
            return m.group(0)
        text = pattern.sub(_sub, text)
    return text, found
