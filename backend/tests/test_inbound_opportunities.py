"""Oportunidades que entregan los flujos de entrada de n8n (P8 conector de TED, ADR-020)."""
import io
from datetime import datetime
from decimal import Decimal

from app.extensions import db
from app.models import Opportunity
from app.services import inbound_opportunities as service

KEY = {"X-Platia-Integration-Key": "test-callback-key"}


def notice(number="123-2026", **extra):
    return {"publication-number": number, "notice-title": {"eng": ["Cloud services"], "spa": ["Servicios en la nube"]},
            "buyer-name": {"spa": ["Ayuntamiento de Ejemplo"]}, "classification-cpv": ["72000000", "72000000", "x"],
            "deadline-receipt-tender-date-lot": ["2026-12-20+01:00", "2026-12-15+01:00"],
            "publication-date": "2026-11-12+01:00", "estimated-value-proc": [150000.456],
            "estimated-value-cur-proc": ["EUR"], **extra}


def send(client, body, headers=KEY):
    return client.post("/api/opportunities/inbound", json=body, headers=headers)


def test_inbound_needs_the_integration_key(client):
    body = {"source": "ted", "format": "ted", "items": [notice()]}
    assert send(client, body, headers={}).status_code == 401
    assert send(client, body, headers={"X-Platia-Integration-Key": "otra"}).status_code == 401
    assert db.session.scalar(db.select(db.func.count()).select_from(Opportunity)) == 0


def test_validation(client):
    assert send(client, {"source": "otra", "items": []}).status_code == 422
    assert send(client, {"source": "ted", "items": [{}] * 251}).status_code == 422
    assert send(client, {"source": "ted", "items": [], "owner_user_id": 1}).status_code == 422
    # En formato platia cada ítem se valida
    assert send(client, {"source": "ted", "items": [{"id": "1", "title": "x", "link": "javascript:x"}]}).status_code == 422
    assert send(client, {"source": "ted", "items": [{"id": "1", "title": "x", "status": "won"}]}).status_code == 422


def test_ted_notices_create_detected_opportunities_once(client):
    body = {"source": "ted", "format": "ted", "workflow_id": "platiaTed01",
            "items": [notice(), notice("124-2026", **{"estimated-value-cur-proc": ["USD"]}), {"notice-title": "x"}]}
    resp = send(client, body)
    assert resp.status_code == 201, resp.json
    assert resp.json["created"] == 2 and resp.json["skipped"] == 1
    opp = db.session.scalar(db.select(Opportunity).filter_by(source="ted", external_id="123-2026"))
    assert opp.status == "detected" and opp.title == "Servicios en la nube" and opp.owner_user_id is None
    assert opp.contracting_entity == "Ayuntamiento de Ejemplo" and opp.cpv_codes == ["72000000"]
    assert opp.estimated_value_eur == Decimal("150000.46")
    # El plazo más cercano, al final del día local y en UTC
    assert opp.deadline == datetime(2026, 12, 15, 22, 59, 59)
    assert opp.published_at == datetime(2026, 11, 11, 23, 0)
    assert opp.extra_data["link"] == "https://ted.europa.eu/es/notice/123-2026/html"
    assert opp.extra_data["workflow_id"] == "platiaTed01"
    other = db.session.scalar(db.select(Opportunity).filter_by(external_id="124-2026"))
    assert other.estimated_value_eur is None  # en otra moneda no se convierte
    # La misma entrega otra vez no duplica
    again = send(client, body)
    assert again.status_code == 200 and again.json["unchanged"] == 2 and again.json["created"] == 0


def test_update_keeps_the_work_status(client):
    send(client, {"source": "ted", "format": "ted", "items": [notice()]})
    opp = db.session.scalar(db.select(Opportunity).filter_by(external_id="123-2026"))
    opp.status = "qualifying"
    db.session.commit()
    resp = send(client, {"source": "ted", "format": "ted", "items": [notice(**{"notice-title": "Título corregido"})]})
    assert resp.json["updated"] == 1
    db.session.refresh(opp)
    assert opp.title == "Título corregido" and opp.status == "qualifying"


def test_platia_format(client):
    item = {"id": "BZ-1", "title": "Pliego recibido por correo", "description": "Ver adjuntos",
            "deadline": "2026-12-01T12:00:00+01:00", "estimated_value": "1000.5", "cpv_codes": ["72000000-5"]}
    resp = send(client, {"source": "buzon_pliegos", "items": [item]})
    assert resp.status_code == 201, resp.json
    opp = db.session.get(Opportunity, resp.json["created_ids"][0])
    assert opp.source == "buzon_pliegos" and opp.deadline == datetime(2026, 12, 1, 11, 0)
    assert opp.estimated_value_eur == Decimal("1000.50")


def test_ted_normalisation_is_tolerant():
    assert service.normalize_ted({"publication-number": "no-vale"}) is None
    item = service.normalize_ted({"publication-number": "9-2026", "notice-title": None, "buyer-name": 7,
                                  "classification-cpv": "48000000", "deadline": "20261201",
                                  "estimated-value-glo": ["abc", 10], "estimated-value-cur-glo": "eur"})
    assert item["title"] == "Anuncio TED 9-2026" and item["entity"] == "7" and item["cpv_codes"] == ["48000000"]
    assert item["deadline"] == datetime(2026, 12, 1, 23, 59, 59) and item["estimated_value"] == Decimal("10.00")
    assert item["published_at"] is None
    assert service._text({"deu": "Nur Deutsch"}) == "Nur Deutsch"


# ------------------------------------------------------------------ P6: adjuntos del buzón de pliegos
def _mail_opportunity(client, ref="<abc@correo.example>") -> int:
    resp = send(client, {"source": "buzon_pliegos", "workflow_id": "platiaBuzon01",
                         "items": [{"id": ref, "title": "Pliego: limpieza de oficinas"}]})
    return resp.json["created_ids"][0]


def attach(client, opp_id, content=b"Pliego de prescripciones tecnicas", name="pliego.txt", headers=KEY, **form):
    return client.post(f"/api/opportunities/inbound/{opp_id}/documents", headers=headers,
                       data={"file": (io.BytesIO(content), name), "source": "buzon_pliegos", **form},
                       content_type="multipart/form-data")


def test_mailbox_attachment_is_stored_linked_and_processed(client, as_role):
    from app.models import Document, OpportunityDocument

    opp_id = _mail_opportunity(client)
    assert attach(client, opp_id, headers={}).status_code == 401
    resp = attach(client, opp_id, title="PPT limpieza")
    assert resp.status_code == 201, resp.json
    document = db.session.get(Document, resp.json["document_id"])
    assert document.title == "PPT limpieza" and document.created_by is None and document.doc_type == "pliego"
    assert document.processing_status == "processed"  # Celery en línea en los tests
    link = db.session.scalar(db.select(OpportunityDocument).filter_by(opportunity_id=opp_id))
    assert link.document_id == document.id and link.role == "requirements"
    # El mismo fichero otra vez no duplica
    again = attach(client, opp_id)
    assert again.status_code == 200 and again.json["duplicate"] and again.json["document_id"] == document.id
    assert db.session.scalar(db.select(db.func.count()).select_from(OpportunityDocument)) == 1
    # Quien trabaja en operaciones lo ve en la oportunidad
    detail = client.get(f"/api/opportunities/{opp_id}", headers=as_role("analyst")).json
    assert [d["document_id"] for d in detail["documents"]] == [document.id]


def test_attachments_only_for_new_opportunities_of_the_mailbox(client):
    opp_id = _mail_opportunity(client)
    # Un fichero que no es lo que dice ser se rechaza como en una subida normal
    assert attach(client, opp_id, content=b"MZ\x90\x00binario", name="pliego.pdf").status_code == 422
    # Otra fuente, otra oportunidad o una que ya se trabaja
    assert attach(client, opp_id, source="ted").status_code == 404
    send(client, {"source": "ted", "format": "ted", "items": [notice()]})
    ted = db.session.scalar(db.select(Opportunity).filter_by(source="ted"))
    assert client.post(f"/api/opportunities/inbound/{ted.id}/documents", headers=KEY, content_type="multipart/form-data",
                       data={"file": (io.BytesIO(b"x"), "a.txt"), "source": "ted"}).status_code == 404
    assert attach(client, 9999).status_code == 404
    opp = db.session.get(Opportunity, opp_id)
    opp.status = "qualifying"
    db.session.commit()
    assert attach(client, opp_id).status_code == 409


def test_attachment_limit(client, monkeypatch):
    monkeypatch.setattr(service, "MAX_DOCUMENTS", 1)
    opp_id = _mail_opportunity(client)
    assert attach(client, opp_id).status_code == 201
    assert attach(client, opp_id, content=b"Otro anexo distinto").status_code == 422
