"""Filtros de Meilisearch construidos como objetos.

Nunca se pega texto del usuario dentro de un filtro: cada condición se crea con
``eq``, ``any_of``, ``gte``... y ``to_meili`` escapa los valores al convertirla.
Así un valor como ``x" OR allowed_roles = "*`` no puede saltarse el control de
acceso (inyección de filtros, Capítulo 13). Los nombres de atributo los pone el
código, nunca la persona.

``matches`` evalúa el mismo filtro sobre un diccionario: lo usa el Meilisearch
falso de los tests, así que los tests comprueban la lógica real del filtro.
"""
import json
from dataclasses import dataclass, field

Value = str | int | float | bool


def _literal(value: Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    # json.dumps escapa comillas y barras invertidas igual que espera Meilisearch
    return json.dumps(str(value), ensure_ascii=False)


@dataclass(frozen=True)
class Cond:
    attr: str
    op: str  # "=", "!=", ">=", "<=", ">", "<", "IN"
    value: Value | tuple

    def to_meili(self) -> str:
        if self.op == "IN":
            return f"{self.attr} IN [{', '.join(_literal(v) for v in self.value)}]"
        return f"{self.attr} {self.op} {_literal(self.value)}"

    def matches(self, doc: dict) -> bool:
        actual = doc.get(self.attr)
        values = actual if isinstance(actual, list) else [actual]
        if self.op == "IN":
            return any(v in self.value for v in values)
        if self.op == "=":
            return self.value in values
        if self.op == "!=":
            return self.value not in values
        numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        ops = {">=": lambda a: a >= self.value, "<=": lambda a: a <= self.value,
               ">": lambda a: a > self.value, "<": lambda a: a < self.value}
        return any(ops[self.op](v) for v in numbers)


@dataclass(frozen=True)
class Group:
    kind: str  # "AND" | "OR"
    items: tuple = field(default_factory=tuple)

    def to_meili(self) -> str:
        parts = [i.to_meili() for i in self.items]
        if len(parts) == 1:
            return parts[0]
        return "(" + f" {self.kind} ".join(parts) + ")"

    def matches(self, doc: dict) -> bool:
        results = (i.matches(doc) for i in self.items)
        return all(results) if self.kind == "AND" else any(results)


Filter = Cond | Group


def eq(attr: str, value: Value) -> Cond:
    return Cond(attr, "=", value)


def any_of(attr: str, values) -> Cond | None:
    values = tuple(dict.fromkeys(v for v in values if v is not None and v != ""))
    if not values:
        return None
    return Cond(attr, "=", values[0]) if len(values) == 1 else Cond(attr, "IN", values)


def gte(attr: str, value: float | int) -> Cond:
    return Cond(attr, ">=", value)


def lte(attr: str, value: float | int) -> Cond:
    return Cond(attr, "<=", value)


def all_of(*items: Filter | None) -> Group | None:
    kept = tuple(i for i in items if i is not None)
    return Group("AND", kept) if kept else None


def either(*items: Filter | None) -> Group | None:
    kept = tuple(i for i in items if i is not None)
    return Group("OR", kept) if kept else None


def to_meili(f: Filter | None) -> str | None:
    return f.to_meili() if f is not None else None
