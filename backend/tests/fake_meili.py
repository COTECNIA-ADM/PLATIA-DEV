"""Meilisearch falso para los tests: misma interfaz que ``MeiliClient``, en memoria.

- Los filtros se evalúan con el mismo objeto que se convierte a texto para el
  Meilisearch real (``Filter.matches``): los tests comprueban la lógica de verdad.
- Búsqueda simplificada: cada palabra de la consulta debe aparecer (o ser el
  principio de una palabra) en algún atributo de búsqueda, sin tildes ni mayúsculas.
- Orden, facetas, paginación y resaltado con las mismas claves de respuesta.
Los tests de ``test_search_meili.py`` usan un Meilisearch real cuando lo hay.
"""
import re
import unicodedata

from app.search.client import MeiliError

_WORD = re.compile(r"[\w/.-]+", re.UNICODE)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _words(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [w for v in value for w in _words(v)]
    return _WORD.findall(_fold(value))


class FakeMeili:
    def __init__(self):
        self.indexes: dict[str, dict] = {}
        self.down = False
        self.searches: list[dict] = []
        self._task = 0

    def _check(self):
        if self.down:
            raise MeiliError("Meilisearch no responde (ConnectionError)")

    def _done(self) -> dict:
        self._task += 1
        return {"taskUid": self._task, "status": "enqueued"}

    def _index(self, uid: str) -> dict:
        if uid not in self.indexes:
            raise MeiliError(f"Index `{uid}` not found.", 404, "index_not_found")
        return self.indexes[uid]

    def docs(self, uid: str) -> dict:
        return self.indexes.get(uid, {}).get("docs", {})

    # --- Estado
    def health(self):
        self._check()
        return {"status": "available"}

    def version(self):
        return {"pkgVersion": "fake"}

    def index_stats(self, uid):
        self._check()
        if uid not in self.indexes:
            return None
        return {"numberOfDocuments": len(self.indexes[uid]["docs"]), "isIndexing": False}

    # --- Índices
    def create_index(self, uid, primary_key="id"):
        self._check()
        self.indexes.setdefault(uid, {"settings": {}, "docs": {}})
        return self._done()

    def delete_index(self, uid):
        self._check()
        if self.indexes.pop(uid, None) is None:
            return None
        return self._done()

    def update_settings(self, uid, settings):
        self._check()
        self.indexes.setdefault(uid, {"settings": {}, "docs": {}})["settings"].update(settings)
        return self._done()

    def swap_indexes(self, pairs):
        self._check()
        for a, b in pairs:
            self.indexes[a], self.indexes[b] = self._index(b), self._index(a)
        return self._done()

    # --- Documentos
    def add_documents(self, uid, documents):
        self._check()
        index = self.indexes.setdefault(uid, {"settings": {}, "docs": {}})
        for doc in documents:
            index["docs"][doc["id"]] = dict(doc)
        return self._done()

    def delete_documents(self, uid, ids):
        self._check()
        for i in ids:
            self._index(uid)["docs"].pop(i, None)
        return self._done()

    # --- Búsqueda
    def _highlight(self, text, words, pre, post):
        if not isinstance(text, str) or not words:
            return text

        def repl(m):
            token = _fold(m.group(0))
            return f"{pre}{m.group(0)}{post}" if any(token.startswith(w) for w in words) else m.group(0)

        return _WORD.sub(repl, text)

    def search(self, uid, query, filter=None):
        self._check()
        self.searches.append({"uid": uid, "query": query, "filter": filter})
        index = self._index(uid)
        settings = index["settings"]
        searchable = settings.get("searchableAttributes") or []
        stop = set(settings.get("stopWords") or [])
        words = [w for w in _words(query.get("q") or "") if w not in stop]
        hits = []
        for doc in index["docs"].values():
            if filter is not None and not filter.matches(doc):
                continue
            if words:
                fields = [_words(doc.get(a)) for a in searchable]
                found = 0
                score = 0.0
                for w in words:
                    for rank, tokens in enumerate(fields):
                        if any(t.startswith(w) for t in tokens):
                            found += 1
                            score += 1.0 / (rank + 1)
                            break
                if found < len(words):
                    continue
                ranking = min(1.0, score / len(words))
            else:
                ranking = 1.0
            hits.append((ranking, doc))
        hits.sort(key=lambda h: h[0], reverse=True)
        for rule in reversed(query.get("sort") or []):
            attr, direction = rule.split(":")
            present = [h for h in hits if h[1].get(attr) is not None]
            missing = [h for h in hits if h[1].get(attr) is None]
            present.sort(key=lambda h: h[1][attr], reverse=direction == "desc")
            hits = present + missing

        facets = None
        if query.get("facets"):
            facets = {}
            for attr in query["facets"]:
                counts: dict = {}
                for _, doc in hits:
                    values = doc.get(attr)
                    for v in values if isinstance(values, list) else [values]:
                        if v is not None:
                            counts[str(v)] = counts.get(str(v), 0) + 1
                facets[attr] = counts
        total = len(hits)
        if "page" in query:
            per = query.get("hitsPerPage", 20)
            start = (query["page"] - 1) * per
            window = hits[start:start + per]
        else:
            start = query.get("offset", 0)
            window = hits[start:start + query.get("limit", 20)]
        pre, post = query.get("highlightPreTag", "<em>"), query.get("highlightPostTag", "</em>")
        retrieve = query.get("attributesToRetrieve")
        out = []
        for ranking, doc in window:
            hit = {k: v for k, v in doc.items() if not retrieve or k in retrieve or "*" in retrieve}
            fmt = {k: self._highlight(doc.get(k), words, pre, post)
                   for k in (query.get("attributesToHighlight") or [])}
            fmt.update({a.split(":")[0]: self._highlight(doc.get(a.split(":")[0]), words, pre, post)
                        for a in (query.get("attributesToCrop") or [])})
            hit["_formatted"] = fmt
            if query.get("showRankingScore"):
                hit["_rankingScore"] = round(ranking, 4)
            out.append(hit)
        res = {"hits": out, "processingTimeMs": 1, "query": query.get("q", "")}
        if "page" in query:
            res.update(totalHits=total, page=query["page"], hitsPerPage=query.get("hitsPerPage", 20))
        else:
            res["estimatedTotalHits"] = total
        if facets is not None:
            res["facetDistribution"] = facets
        return res

    def multi_search(self, queries):
        return [self.search(uid, {**q}, f) for uid, q, f in queries]

    # --- Tareas
    def get_task(self, task_uid):
        return {"taskUid": task_uid, "status": "succeeded"}

    def wait(self, task, timeout=120.0, interval=0.2):
        return {"status": "succeeded"}
