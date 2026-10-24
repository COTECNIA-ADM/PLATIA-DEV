"""Recorrido de prueba de la fase 4 contra la plataforma levantada en Docker.

Uso:  python scripts/demo_fase4.py --email tu@empresa.com [--url http://localhost:8080]

La contraseña se pide por teclado y no se muestra. Solo usa la biblioteca estándar
de Python. Crea datos de ejemplo (un cliente, una oportunidad, un documento y una
propuesta) y muestra cada paso; puedes borrarlos después desde la API.
"""
import argparse
import getpass
import json
import sys
import time
import uuid
import urllib.error
import urllib.request


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/") + "/api"
        self.token = None

    def call(self, method: str, path: str, body=None, app: str | None = None, raw: bytes | None = None,
             content_type: str = "application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", content_type)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if app:
            req.add_header("X-App-Code", app)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                return resp.status, (json.loads(payload) if "json" in ctype and payload else payload)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                return exc.code, json.loads(payload)
            except ValueError:
                return exc.code, payload

    def upload(self, path: str, filename: str, content: bytes, fields: dict):
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self.call("POST", path, raw=b"".join(parts),
                         content_type=f"multipart/form-data; boundary={boundary}")


def step(title: str, status: int, detail) -> None:
    ok = "OK " if 200 <= status < 300 else "ERR"
    print(f"[{ok}] {title} ({status}) {detail}")
    if ok == "ERR":
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()
    api = Api(args.url)

    status, body = api.call("POST", "/auth/login", {"email": args.email,
                                                    "password": getpass.getpass("Contraseña: ")})
    if status == 200 and body.get("mfa_required"):
        status, body = api.call("POST", "/auth/mfa/verify", {"mfa_token": body["mfa_token"],
                                                             "code": input("Código MFA: ").strip()})
    step("Inicio de sesión", status, "")
    api.token = body["access_token"]

    status, health = api.call("GET", "/health/full", app="admin")
    step("Estado completo", status, {s["name"]: s["status"] for s in health["services"]})

    suffix = uuid.uuid4().hex[:6]
    status, client = api.call("POST", "/clients", {"name": f"Ayuntamiento de Ejemplo {suffix}",
                                                   "sector": "public", "segment": "A"})
    step("Cliente creado", status, client.get("id"))

    status, opp = api.call("POST", "/opportunities", {
        "title": "Servicio de SOC 24x7, pentest anual y adecuación al ENS",
        "client_id": client["id"], "estimated_value_eur": "180000.00", "cpv_codes": ["72212730"],
        "description": "Ciberseguridad gestionada con SIEM y respuesta a incidentes."})
    step("Oportunidad creada y puntuada", status,
         f"línea={opp['service_line']} relevancia={opp['relevance_score']}/10")

    text = "Pliego de prescripciones técnicas.\nEl adjudicatario acreditará el ENS nivel medio.\n"
    status, doc = api.upload("/documents", f"pliego-{suffix}.txt", text.encode(), {"doc_type": "requirements"})
    step("Documento subido", status, f"id={doc.get('id')} estado={doc.get('processing_status')}")
    for _ in range(30):
        status, st = api.call("GET", f"/documents/{doc['id']}/status")
        if st["processing_status"] in ("processed", "failed"):
            break
        time.sleep(1)
    step("Documento procesado por el worker", status, st["processing_status"])

    status, _ = api.call("POST", f"/opportunities/{opp['id']}/documents", {"document_id": doc["id"]})
    step("Documento vinculado a la oportunidad", status, "")
    for target in ("qualifying", "qualified", "go_no_go", "preparing_proposal"):
        status, opp = api.call("POST", f"/opportunities/{opp['id']}/status",
                               {"version": opp["version"], "status": target})
    step("Oportunidad avanzada en el embudo", status, f"{opp['status']} ({opp['phase']})")

    status, templates = api.call("GET", "/proposal-templates?proposal_type=premium")
    status, prop = api.call("POST", "/proposals", {"opportunity_id": opp["id"], "proposal_type": "premium",
                                                   "template_id": templates["items"][0]["id"],
                                                   "total_amount_eur": "175000.00"})
    step("Propuesta premium creada", status, [s["key"] for s in prop["sections"]])
    section = prop["sections"][0]
    status, _ = api.call("PATCH", f"/proposals/{prop['id']}/sections/{section['id']}",
                         {"version": section["version"], "edited_content": "Resumen de la propuesta."})
    step("Sección editada", status, "")
    status, prop = api.call("GET", f"/proposals/{prop['id']}")
    status, prop = api.call("POST", f"/proposals/{prop['id']}/status",
                            {"version": prop["version"], "status": "in_review"})
    step("Propuesta en revisión", status, f"necesita: {prop['required_reviews']}")
    for kind in ("technical", "executive"):
        status, prop = api.call("POST", f"/proposals/{prop['id']}/reviews", {"kind": kind, "decision": "approve"})
        step(f"Revisión {kind}", status, prop["status"])
    for _ in range(30):
        status, prop = api.call("GET", f"/proposals/{prop['id']}")
        generated = [a for a in prop["attachments"] if a["kind"] == "generated"]
        if generated:
            break
        time.sleep(1)
    step("Paquete DOCX generado por el worker", status, generated[0]["filename"] if generated else "pendiente")

    status, notes = api.call("GET", "/notifications?unread=true")
    step("Notificaciones sin leer", status, [n["title"] for n in notes["items"]][:5])
    status, queues = api.call("GET", "/admin/tasks/queues", app="admin")
    step("Colas de Celery", status, queues["queues"])
    print("\nTodo correcto. La oportunidad es la", opp["id"], "y la propuesta la", prop["id"])


if __name__ == "__main__":
    main()
