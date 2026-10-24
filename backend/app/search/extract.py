"""Filtros de búsqueda a partir de una frase en español (Capítulo 13).

"Busca contratos de ciberseguridad de más de 100.000 euros que cierren este mes"
-> texto ``ciberseguridad``, ``value_min=100000``, ``deadline_within_days`` hasta
fin de mes y solo oportunidades abiertas.

Es determinista y sin coste. Cuando la consulta llega a la segunda capa del
clasificador, el modelo también propone filtros; los de aquí mandan y los del
modelo solo rellenan huecos (``merge``).
"""
import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def normalize(text: str, max_chars: int = 500) -> str:
    """Minúsculas, sin tildes ni caracteres de control y con espacios simples.
    Los patrones del clasificador se escriben sobre este texto."""
    text = CONTROL.sub(" ", text or "")[:max_chars]
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------------------ Importes
_NUM = r"(\d{1,3}(?:[.\s]\d{3})+|\d+(?:[.,]\d+)?)"
_UNIT = r"(?:\s*(millones|millon|meur|mil|me|m|k|euros|eur|€)(?![a-z]))?"
_NOT_TIME = r"(?!\s*(?:dias?|semanas?|mes(?:es)?|anos?|horas?|%|por ciento))"
_AMOUNT = _NUM + _UNIT + r"(?:\s*(?:euros|eur|€)(?![a-z]))?" + _NOT_TIME
_BETWEEN = re.compile(r"\bentre\s+" + _AMOUNT + r"\s+y\s+" + _AMOUNT)
_MIN = re.compile(r"\b(?:mas de|superior(?:es)? a|por encima de|mayor(?:es)? (?:de|que|a)|desde|minimo(?: de)?|"
                  r"al menos|a partir de|como minimo|>=?)\s*" + _AMOUNT)
_MAX = re.compile(r"\b(?:menos de|inferior(?:es)? a|por debajo de|hasta|maximo(?: de)?|como mucho|no mas de|"
                  r"<=?)\s*" + _AMOUNT)


def _to_number(raw: str, unit: str | None) -> float | None:
    raw = raw.strip()
    if re.fullmatch(r"\d{1,3}(?:[.\s]\d{3})+", raw):
        value = float(re.sub(r"[.\s]", "", raw))  # 100.000 / 100 000
    else:
        value = float(raw.replace(",", "."))  # 1,5 / 1.5 / 200
    unit = (unit or "").strip()
    if unit in ("k", "mil"):
        value *= 1_000
    elif unit in ("m", "millon", "millones", "me", "meur"):
        value *= 1_000_000
    return value


def _plausible(value: float | None, unit: str | None, raw: str) -> bool:
    """Un número suelto pequeño ("más de 3") no es un importe; con unidad o con
    cuatro cifras o más, sí."""
    return value is not None and (bool(unit) or value >= 1000 or "€" in raw or "eur" in raw)


# ------------------------------------------------------------------ Fechas y plazos
_WITHIN = re.compile(r"\b(?:en|dentro de|durante|para) (?:los |las )?(?:proximos |proximas |siguientes )?"
                     r"(\d{1,3}) (dias|semanas|meses)\b")
_LAST = re.compile(r"\b(?:en )?(?:los |las )?(?:ultimos|ultimas) (\d{1,3}) (dias|semanas|meses)\b")
_DEADLINE_WORDS = re.compile(r"\b(plazo|plazos|cierr\w*|venc\w*|fecha limite|termin\w*|presentacion|finaliz\w*|"
                             r"quedan?|caduc\w*)\b")
_PUBLISHED_WORDS = re.compile(r"\b(publicad\w*|nuev[oa]s|recientes?|aparecid\w*|salid[oa]s)\b")
_PERIODS = {
    "hoy": "today", "esta semana": "week", "la semana que viene": "next_week", "la proxima semana": "next_week",
    "este mes": "month", "fin de mes": "month", "el mes que viene": "next_month", "el proximo mes": "next_month",
    "la ultima semana": "last_week", "el ultimo mes": "last_month", "ayer": "yesterday",
    "este trimestre": "quarter", "proximo trimestre": "next_quarter", "siguiente trimestre": "next_quarter",
}
_PERIOD_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _PERIODS), key=len, reverse=True)) + r")\b")
_UNIT_DAYS = {"dias": 1, "semanas": 7, "meses": 30}

# ------------------------------------------------------------------ Estado
_STATUS_WORDS = [
    (re.compile(r"\b(abiert[oa]s?|activ[oa]s?|vigentes?|en plazo|pendientes de presentar)\b"), "open"),
    (re.compile(r"\b(ganad[oa]s|adjudicad[oa]s a nosotros)\b"), "won"),
    (re.compile(r"\b(perdid[oa]s)\b"), "lost"),
    (re.compile(r"\b(descartad[oa]s)\b"), "discarded"),
]
_CPV = re.compile(r"\bcpv\s*(\d{2,8})\b|\b(\d{8})(?:-\d)?\b")

# Palabras que expresan la orden o el tipo de cosa buscada, no lo que se busca
FILLER = set("""
busca buscame buscar busco buscamos encuentra encuentrame encontrar localiza muestra muestrame mostrar
ensename lista listame listado dame quiero queria necesito ver filtra filtrar hay tenemos existe existen
oportunidad oportunidades contrato contratos licitacion licitaciones concurso concursos expediente expedientes
publica publicas publico publicos sector ambito area tipo
de del la las el los en con para por que y o a al un una unos unas sobre cuyo cuya cuyos cuyas me nos se
mas menos importe presupuesto valor euros eur cuantia estimado estimada base superior superiores inferior
inferiores dias semanas meses anos horas proximo proximos proxima proximas
hasta todas todos todo toda alguna algun algunas algunos cual cuales cuantas cuantos
""".split())


@dataclass
class Extracted:
    keywords: str = ""
    value_min: float | None = None
    value_max: float | None = None
    deadline_within_days: int | None = None
    published_within_days: int | None = None
    statuses: list[str] = field(default_factory=list)
    only_open: bool | None = None
    cpv: list[str] = field(default_factory=list)

    def to_filters(self) -> dict:
        out = {k: v for k, v in {
            "q": self.keywords, "value_min": self.value_min, "value_max": self.value_max,
            "deadline_within_days": self.deadline_within_days, "published_within_days": self.published_within_days,
            "status": self.statuses or None, "cpv": self.cpv or None,
        }.items() if v not in (None, "", [])}
        out["only_open"] = self.only_open if self.only_open is not None else not self.statuses
        return out


def _period_days(period: str, now: datetime) -> tuple[str, int]:
    """("future"|"past", días) de una expresión como "este mes"."""
    last_day = calendar.monthrange(now.year, now.month)[1]
    quarter_end_month = ((now.month - 1) // 3 + 1) * 3
    quarter_end = datetime(now.year, quarter_end_month, calendar.monthrange(now.year, quarter_end_month)[1],
                           tzinfo=now.tzinfo)
    to_quarter_end = (quarter_end.date() - now.date()).days
    return {
        "quarter": ("future", to_quarter_end), "next_quarter": ("future", to_quarter_end + 92),
        "today": ("both", 0), "yesterday": ("past", 1), "week": ("future", 7 - now.weekday()),
        "next_week": ("future", 14 - now.weekday()), "month": ("future", last_day - now.day),
        "next_month": ("future", last_day - now.day + 31), "last_week": ("past", 7), "last_month": ("past", 31),
    }[period]


def extract(text: str, now: datetime | None = None) -> Extracted:
    now = now or datetime.now(timezone.utc)
    t = normalize(text)
    out = Extracted()
    spans: list[tuple[int, int]] = []

    if m := _BETWEEN.search(t):
        low = _to_number(m.group(1), m.group(2))
        high = _to_number(m.group(3), m.group(4) or m.group(2))
        if _plausible(low, m.group(2) or m.group(4), m.group(0)) and low is not None and high is not None:
            out.value_min, out.value_max = min(low, high), max(low, high)
            spans.append(m.span())
    if out.value_min is None and (m := _MIN.search(t)):
        value = _to_number(m.group(1), m.group(2))
        if _plausible(value, m.group(2), m.group(0)):
            out.value_min = value
            spans.append(m.span())
    if out.value_max is None and (m := _MAX.search(t)):
        value = _to_number(m.group(1), m.group(2))
        if _plausible(value, m.group(2), m.group(0)):
            out.value_max = value
            spans.append(m.span())

    talks_deadline = bool(_DEADLINE_WORDS.search(t))
    talks_published = bool(_PUBLISHED_WORDS.search(t))
    if m := _WITHIN.search(t):
        out.deadline_within_days = int(m.group(1)) * _UNIT_DAYS[m.group(2)]
        spans.append(m.span())
    if m := _LAST.search(t):
        out.published_within_days = int(m.group(1)) * _UNIT_DAYS[m.group(2)]
        spans.append(m.span())
    for m in _PERIOD_RE.finditer(t):
        period = _PERIODS[m.group(1)]
        direction, days = _period_days(period, now)
        if direction == "past" or (talks_published and not talks_deadline):
            # "publicadas esta semana": desde el lunes; "este mes": desde el día 1
            since = {"today": 1, "week": now.weekday() + 1, "month": now.day}.get(period, days)
            out.published_within_days = out.published_within_days or max(since, 1)
        elif out.deadline_within_days is None:
            out.deadline_within_days = days
        spans.append(m.span())

    for regex, status in _STATUS_WORDS:
        if m := regex.search(t):
            spans.append(m.span())
            if status == "open":
                out.only_open = True
            elif status not in out.statuses:
                out.statuses.append(status)
    if out.deadline_within_days is not None and out.only_open is None:
        out.only_open = True  # "que cierran este mes" implica que siguen abiertas

    for m in _CPV.finditer(t):
        out.cpv.append(m.group(1) or m.group(2))
        spans.append(m.span())

    # Lo que queda, sin las expresiones reconocidas ni palabras de relleno, es el texto a buscar
    kept, last = [], 0
    for start, end in sorted(spans):
        if start >= last:
            kept.append(t[last:start])
            last = end
    kept.append(t[last:])
    rest = re.sub(r"[¿?¡!,;:()\"']", " ", " ".join(kept))
    words = [w for w in rest.split() if w not in FILLER and not _DEADLINE_WORDS.fullmatch(w)
             and not _PUBLISHED_WORDS.fullmatch(w) and len(w) > 1]
    out.keywords = " ".join(words)[:200]
    return out


def merge(base: Extracted, llm: dict | None) -> Extracted:
    """Completa lo que no encontró el extractor con los filtros que propuso el modelo."""
    if not llm:
        return base

    def num(key: str, low: float, high: float) -> float | None:
        try:
            value = float(llm.get(key) or 0)
        except (TypeError, ValueError):
            return None
        return value if low < value <= high else None  # 0 = "no indicado"

    if base.value_min is None:
        base.value_min = num("value_min_eur", 0, 1e12)
    if base.value_max is None:
        base.value_max = num("value_max_eur", 0, 1e12)
    if base.deadline_within_days is None and (d := num("deadline_within_days", 0, 3650)):
        base.deadline_within_days = int(d)
    if base.published_within_days is None and (d := num("published_within_days", 0, 3650)):
        base.published_within_days = int(d)
    # Si se llegó a la capa 2 es porque la frase no encajaba en los patrones: las
    # palabras clave del modelo suelen ser más limpias que lo que sobra al extractor
    if isinstance(llm.get("keywords"), str) and llm["keywords"].strip():
        base.keywords = normalize(llm["keywords"], 200)
    if base.only_open is None and llm.get("only_open") is True:
        base.only_open = True
    if base.value_min is not None and base.value_max is not None and base.value_min > base.value_max:
        base.value_min, base.value_max = base.value_max, base.value_min
    return base
