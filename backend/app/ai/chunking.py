"""Fragmentación de documentos para RAG (Capítulo 12).

Dos niveles (patrón *parent document*):

- **Bloques padre** (~2.400 caracteres) que respetan la estructura del documento
  según su tipo: cláusulas numeradas en contratos y pliegos, secciones en los CV,
  filas con cabecera repetida en tablas y párrafos en el resto. Es lo que recibe
  el modelo como contexto.
- **Fragmentos hijo** (~500 caracteres, con solapamiento) dentro de cada padre.
  Es lo que se vectoriza: el modelo de embeddings local solo mira los primeros
  ~128 tokens de cada texto, y un fragmento pequeño da una búsqueda más precisa.

Cada hijo guarda la posición de su padre en el texto del documento, así el
backend recupera el contexto completo de MySQL sin duplicarlo en Qdrant. El
solapamiento evita que un requisito quede partido entre dos fragmentos sin que
ninguno lo contenga entero.
"""
import re
from dataclasses import dataclass

PARENT_CHARS = 2400
PARENT_OVERLAP = 300
CHILD_CHARS = 500
CHILD_OVERLAP = 100
MAX_CHILDREN = 5000

CLAUSE_TYPES = {"contrato", "pliego", "normativa", "certificacion", "acta", "acta_reunion", "requisitos",
                "documento_requisitos"}
SECTION_TYPES = {"cv", "cv_profile"}

# Cláusula o punto numerado al principio de línea: "1.", "2.3", "12.1.4)", "CLÁUSULA 5", "Artículo 3"
_CLAUSE = re.compile(r"(?im)^(?:\s*(?:cl[aá]usula|art[ií]culo|anexo|punto)\s+[\dIVXLC]+|\s*\d{1,2}(?:\.\d{1,2}){0,3}[.)]\s+\S)")
# Encabezado corto en línea propia (CV): "EXPERIENCIA", "Formación académica:", "## Idiomas"
_HEADING = re.compile(r"(?m)^(?:#{1,4}\s+.+|[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ \t/&]{3,60}:?|[A-ZÁÉÍÓÚÑ][\wáéíóúñ ]{2,40}:)\s*$")
_SEPARATORS = ("\n\n", "\n", ". ", "; ", ", ", " ")


@dataclass
class Parent:
    start: int
    end: int


@dataclass
class Child:
    text: str
    parent_start: int
    parent_end: int
    page: int | None


def _split_points(text: str, pattern: re.Pattern) -> list[int]:
    points = sorted({0, *(m.start() for m in pattern.finditer(text))})
    return points


def _pack(text: str, points: list[int], size: int) -> list[Parent]:
    """Agrupa secciones consecutivas hasta ``size`` caracteres; las más largas se trocean."""
    bounds = [*points, len(text)]
    parents: list[Parent] = []
    start = bounds[0]
    for i in range(1, len(bounds)):
        end = bounds[i]
        # Corta antes de esta sección si el bloque se pasa de tamaño (y no es un
        # encabezado suelto, que se queda con la sección siguiente)
        if end - start > size and bounds[i - 1] - start >= size // 4:
            parents.append(Parent(start, bounds[i - 1]))
            start = bounds[i - 1]
    parents.append(Parent(start, len(text)))
    out: list[Parent] = []
    for p in parents:
        if p.end - p.start > size * 1.5:
            out += [Parent(p.start + s, p.start + e) for s, e in _windows(text[p.start:p.end], size, PARENT_OVERLAP)]
        elif text[p.start:p.end].strip():
            out.append(p)
    return out


def _windows(text: str, size: int, overlap: int) -> list[tuple[int, int]]:
    """Ventanas de ``size`` caracteres que cortan, si pueden, en un separador natural."""
    spans: list[tuple[int, int]] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            for sep in _SEPARATORS:
                cut = text.rfind(sep, start + size // 2, end)
                if cut != -1:
                    end = cut + len(sep)
                    break
        if text[start:end].strip():
            spans.append((start, end))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
        # Empieza la siguiente ventana al principio de una palabra
        while start < n and start > 0 and not text[start - 1].isspace() and not text[start].isspace():
            start += 1
    return spans


def _tabular_parents(text: str, size: int) -> list[Parent]:
    """Tablas (CSV): bloques de filas completas; la cabecera se repite en los hijos."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return []
    parents, offset = [], len(lines[0])
    start = offset
    for line in lines[1:]:
        if offset + len(line) - start > size and offset > start:
            parents.append(Parent(start, offset))
            start = offset
        offset += len(line)
    if offset > start:
        parents.append(Parent(start, offset))
    return parents or [Parent(0, len(text))]


def _page_at(page_starts: list[int], pos: int) -> int | None:
    if len(page_starts) <= 1:
        return None
    page = 1
    for i, start in enumerate(page_starts):
        if start <= pos:
            page = i + 1
        else:
            break
    return page


def chunk_document(text: str, doc_type: str | None = None, mime_type: str | None = None) -> tuple[list[Child], bool]:
    """Devuelve los fragmentos hijo y si se ha truncado el documento por tamaño."""
    if not text or not text.strip():
        return [], False
    kind = (doc_type or "").lower()
    header = ""
    if mime_type in ("text/csv",) or kind in ("presupuesto", "tabla"):
        parents = _tabular_parents(text, PARENT_CHARS)
        header = text.splitlines()[0].strip()[:300] if text.splitlines() else ""
    elif kind in CLAUSE_TYPES:
        parents = _pack(text, _split_points(text, _CLAUSE), PARENT_CHARS)
    elif kind in SECTION_TYPES:
        parents = _pack(text, _split_points(text, _HEADING), PARENT_CHARS)
    else:
        parents = _pack(text, _split_points(text, re.compile(r"\n\s*\n")), PARENT_CHARS)

    # Los PDF se extraen con un salto de página (\f) entre páginas
    page_starts = [0, *(m.end() for m in re.finditer("\f", text))]
    children: list[Child] = []
    for parent in parents:
        body = text[parent.start:parent.end]
        for s, e in _windows(body, CHILD_CHARS, CHILD_OVERLAP):
            piece = " ".join(body[s:e].split())
            if len(piece) < 20:
                continue
            if header:
                piece = f"{header}\n{piece}"
            children.append(Child(piece, parent.start, parent.end, _page_at(page_starts, parent.start + s)))
            if len(children) >= MAX_CHILDREN:
                return children, True
    return children, False
