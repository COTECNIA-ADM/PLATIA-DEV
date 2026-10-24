"""Recorrido de prueba de la fase 5c (copiloto) contra la plataforma levantada en Docker.

Uso:  python scripts/demo_fase5c.py --email tu@empresa.com [--url http://localhost:8080]

Abre una conversación con el copiloto y muestra la respuesta mientras se escribe:
1. Le pide buscar oportunidades (usa herramientas de solo lectura, sin pedir permiso).
2. Le pide crear una propuesta para una oportunidad de ejemplo: el agente se para y
   pide tu aprobación; tú decides en el terminal.
3. Enseña lo que el copiloto recuerda de ti y lo que cuesta.

Hace llamadas reales a Claude con tu ANTHROPIC_API_KEY (unos céntimos, normalmente
menos de 0,15 USD). La contraseña se pide por teclado y no se muestra. Solo usa la
biblioteca estándar. Crea datos de ejemplo (una oportunidad y, si apruebas, una propuesta).
"""
import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/") + "/api"
        self.token = None

    def _request(self, method: str, path: str, body=None, app: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if app:
            req.add_header("X-App-Code", app)
        return req

    def call(self, method: str, path: str, body=None, app: str | None = None):
        try:
            with urllib.request.urlopen(self._request(method, path, body, app), timeout=60) as resp:
                payload = resp.read()
                return resp.status, (json.loads(payload) if payload else None)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                return exc.code, json.loads(payload)
            except ValueError:
                return exc.code, payload

    def stream(self, path: str, body: dict):
        """Lee la respuesta SSE línea a línea y devuelve los eventos (nombre, datos)."""
        try:
            resp = urllib.request.urlopen(self._request("POST", path, body), timeout=300)
        except urllib.error.HTTPError as exc:
            print(f"\n[ERR] {exc.code} {exc.read().decode(errors='replace')}")
            sys.exit(1)
        event = None
        with resp:
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    yield event, json.loads(line[6:])


def step(title: str, status: int, detail="") -> None:
    ok = "OK " if 200 <= status < 300 else "ERR"
    print(f"[{ok}] {title} ({status}) {detail}")
    if ok == "ERR":
        sys.exit(1)


def show(events) -> dict:
    """Pinta la conversación según llega y devuelve el último evento importante."""
    last = {}
    print("      ", end="")
    for event, data in events:
        if event == "agent":
            print(f"(responde el agente «{data.get('name')}»)\n      ", end="")
        elif event == "delta":
            print(data["text"].replace("\n", "\n      "), end="", flush=True)
        elif event == "replace":
            print("\n      [texto corregido por los guardarraíles]")
        elif event == "tool_call":
            print(f"\n      -> herramienta {data['name']}", end="", flush=True)
        elif event == "tool_result":
            print(f" ({'bien' if data.get('ok') else 'error'}, {data.get('ms')} ms)\n      ", end="")
        elif event == "notice":
            print(f"\n      [aviso] {data.get('message')}")
        elif event == "rag_answer":
            print((data.get("answer") or "").replace("\n", "\n      "))
        elif event in ("approval_required", "done", "error"):
            last = {"event": event, **data}
    print()
    return last


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
    step("Inicio de sesión", status)
    api.token = body["access_token"]

    status, opp = api.call("POST", "/opportunities", {
        "title": "SOC gestionado 24x7 para un cabildo insular (ejemplo)",
        "description": "Centro de operaciones de seguridad con SIEM, respuesta a incidentes y "
                       "concienciación del personal. Presupuesto estimado 150.000 EUR."})
    step("Oportunidad de ejemplo", status, f"id {opp.get('id')}")

    status, conv = api.call("POST", "/copilot/conversations", {"title": "Prueba de la fase 5c"})
    step("Conversación nueva", status, f"id {conv.get('id')}")
    path = f"/copilot/conversations/{conv['id']}/messages"

    print("\n[Tú] ¿Qué oportunidades de ciberseguridad tenemos abiertas?")
    last = show(api.stream(path, {"content": "¿Qué oportunidades de ciberseguridad tenemos abiertas? "
                                             "Dame las tres más relevantes."}))
    step("Respuesta con herramientas", 200 if last.get("event") == "done" else 500,
         f"{last.get('tool_calls')} herramientas, {last.get('cost_usd')} USD")

    print(f"\n[Tú] Crea una propuesta base para @oportunidad:{opp['id']}")
    last = show(api.stream(path, {"content": f"Crea una propuesta base para @oportunidad:{opp['id']}"}))
    while last.get("event") == "approval_required":
        print("      El agente quiere hacer esto:")
        for action in last["actions"]:
            print(f"        - {action['summary']}")
        approve = input("      ¿Lo apruebas? (s/n): ").strip().lower().startswith("s")
        last = show(api.stream(f"/copilot/runs/{last['run_id']}/approval", {"approve": approve}))
    step("Fin de la conversación", 200 if last.get("event") == "done" else 500, last.get("status"))

    status, props = api.call("GET", f"/proposals?opportunity_id={opp['id']}")
    print(f"      Propuestas de la oportunidad: {props['pagination']['total']}")

    status, mems = api.call("GET", "/copilot/memories")
    step("Lo que el copiloto recuerda de ti", status, f"{len(mems['items'])} recuerdos")
    for m in mems["items"]:
        print(f"      - [{m['category']}] {m['content']}")
    print("      (los recuerdos se extraen en segundo plano; si no ves ninguno, vuelve a mirar en un minuto)")

    status, usage = api.call("GET", "/admin/ai/usage/summary?days=1", app="admin")
    if status == 200:
        step("Coste registrado hoy", status, f"{usage['total_cost_usd']} USD")
        for item in usage["items"]:
            print(f"      {item['service_type']:<22} {item['model']:<20} {item['calls']:>3} llamadas  {item['cost_usd']} USD")


if __name__ == "__main__":
    main()
