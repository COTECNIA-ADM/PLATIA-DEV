"""La tabla de rutas de ``docs/api.md`` coincide con las rutas reales de Flask (fase 9b).

Notación de la tabla (columna «Rutas»): cada ruta va entre comillas invertidas como
``MÉTODOS /ruta``, con varios métodos separados por ``/`` (``GET/PATCH /clients/{id}``)
y un último tramo opcional entre corchetes (``/contacts[/{cid}]``). La parte de la
consulta (``?months=``) se ignora. Las rutas se escriben sin el prefijo ``/api``.

Con tramos opcionales no se sabe qué método va con qué variante, así que se comprueba:
- toda ruta de Flask aparece en alguna fila con su método;
- toda variante documentada existe en Flask, y cada método de la fila existe en
  alguna de sus variantes.
"""
import re
from pathlib import Path

import pytest

API_DOC = Path(__file__).resolve().parents[2] / "docs" / "api.md"
SPAN = re.compile(r"`([A-Z]+(?:/[A-Z]+)*) (/[^`\s]*)`")
PARAM = re.compile(r"\{[^}]*\}")


def _normalize(path: str) -> str:
    return PARAM.sub("{}", path.split("?", 1)[0].rstrip("/") or "/")


def _expand(path: str) -> list[str]:
    """``/a[/{b}]`` → ``/a`` y ``/a/{b}`` (admite varios tramos opcionales)."""
    match = re.search(r"\[([^\[\]]*)\]", path)
    if not match:
        return [path]
    before, after = path[: match.start()], path[match.end():]
    return _expand(before + after) + _expand(before + match.group(1) + after)


def documented() -> list[tuple[set[str], list[str], str]]:
    """(métodos, variantes, texto) por cada ruta de la tabla «Recursos»."""
    text = API_DOC.read_text(encoding="utf-8")
    section = text.split("## Recursos", 1)[1].split("\n## ", 1)[0]
    entries = []
    for line in section.splitlines():
        cells = line.split(" | ")
        if not line.startswith("|") or len(cells) < 3:
            continue
        for methods, path in SPAN.findall(cells[1]):
            variants = [_normalize("/api" + p) for p in _expand(path.replace("\\|", "|"))]
            entries.append((set(methods.split("/")), variants, f"{methods} {path}"))
    return entries


def flask_routes(app) -> set[tuple[str, str]]:
    routes = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        path = _normalize(re.sub(r"<[^>]+>", "{}", rule.rule))
        routes |= {(m, path) for m in rule.methods - {"HEAD", "OPTIONS"}}
    return routes


@pytest.fixture()
def routes(app):
    return flask_routes(app)


def test_the_table_has_routes():
    assert len(documented()) > 50


def test_every_flask_route_is_documented(routes):
    covered = {(m, v) for methods, variants, _ in documented() for m in methods for v in variants}
    missing = sorted(f"{m} {p.removeprefix('/api')}" for m, p in routes - covered)
    assert not missing, "Rutas sin documentar en docs/api.md:\n" + "\n".join(missing)


def test_every_documented_route_exists(routes):
    paths = {p for _, p in routes}
    errors = []
    for methods, variants, text in documented():
        errors += [f"{text}: no existe {v.removeprefix('/api')}" for v in variants if v not in paths]
        errors += [f"{text}: ninguna variante admite {m}" for m in sorted(methods)
                   if not any((m, v) in routes for v in variants)]
    assert not errors, "docs/api.md documenta rutas que no existen:\n" + "\n".join(errors)


def test_optional_segments_expand():
    assert _expand("/a[/{b}]") == ["/a", "/a/{b}"]
    assert _normalize("/api/x/{id}?q=1") == "/api/x/{}"
