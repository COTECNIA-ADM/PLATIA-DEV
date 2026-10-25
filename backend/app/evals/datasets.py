"""Carga de los juegos de casos de ``data/``."""
import json
from functools import cache
from pathlib import Path

DATA = Path(__file__).parent / "data"


@cache
def load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def cases(name: str) -> list[dict]:
    return load(name)["casos"]


def input_text(case: dict) -> str:
    """Texto del caso; ``repetir: [texto, n]`` genera textos largos sin escribirlos."""
    if "repetir" in case:
        text, times = case["repetir"]
        return text * times
    return case["texto"]
