"""Tareas de Celery: se ejecutan en línea (task_always_eager) contra SQLite y fakeredis."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import (Alert, AuditLog, Document, FailedTask, Notification, Opportunity, Proposal,
                        UserSession, utcnow)
from app.queue import backoff_with_jitter, task_lock, TaskAlreadyRunning
from app.tasks import alerts, documents, sync, system

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Licitaciones</title>
  <entry>
    <id>urn:licitacion:2026-001</id>
    <title>Servicio de ciberseguridad: SOC y respuesta a incidentes</title>
    <summary>Contratacion de un SOC 24x7, pentest anual y adecuacion al ENS.</summary>
    <updated>2026-10-23T10:00:00+02:00</updated>
    <author><name>Diputacion de Ejemplo</name></author>
    <link href="https://contratacion.example/2026-001"/>
    <category term="72212730"/>
  </entry>
  <entry>
    <id>urn:licitacion:2026-002</id>
    <title>Suministro de mobiliario</title>
    <summary>Sillas y mesas.</summary>
  </entry>
</feed>"""


def test_backoff_grows_with_jitter_and_cap():
    assert 45 <= backoff_with_jitter(0) <= 75
    assert 180 <= backoff_with_jitter(2) <= 300
    assert backoff_with_jitter(20) <= 3600 * 1.25


def test_task_lock(app):
    with task_lock("x"):
        with pytest.raises(TaskAlreadyRunning):
            with task_lock("x"):
                pass
    with task_lock("x"):  # liberado al salir
        pass


def test_feed_ingestion_dedupes_and_proactive_scan_alerts(seeded, make_user):
    admin = make_user("root@example.com", superadmin=True)
    first = sync.ingest_feed("contratacion", ATOM)
    assert first == {"created": 2, "updated": 0, "unchanged": 0}
    assert sync.ingest_feed("contratacion", ATOM) == {"created": 0, "updated": 0, "unchanged": 2}
    changed = ATOM.replace(b"SOC 24x7", b"SOC 24x7 y SIEM")
    assert sync.ingest_feed("contratacion", changed)["updated"] == 1

    opp = db.session.scalar(db.select(Opportunity).filter_by(external_id="urn:licitacion:2026-001"))
    assert opp.contracting_entity == "Diputacion de Ejemplo" and opp.cpv_codes == ["72212730"]
    assert opp.published_at.hour == 8  # normalizado a UTC

    result = alerts.proactive_scan.apply().get()
    assert result == {"scored": 2, "alerts": 1}
    alert = db.session.scalar(db.select(Alert))
    assert alert.opportunity_id == opp.id and "Ciberseguridad" in alert.message
    note = db.session.scalar(db.select(Notification).filter_by(user_id=admin.id))
    assert note.notification_type == "OPPORTUNITY_MATCH" and note.link == f"/opportunities/{opp.id}"
    # La segunda pasada no duplica alertas ni avisos
    alerts.proactive_scan.apply()
    assert db.session.scalar(db.select(db.func.count()).select_from(Alert)) == 1
    assert db.session.scalar(db.select(db.func.count()).select_from(Notification)) == 1


def test_feed_parser_blocks_xml_entities():
    evil = b"""<?xml version="1.0"?>
<!DOCTYPE feed [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>1</id><title>&xxe;</title></entry></feed>"""
    with pytest.raises(Exception) as exc:
        sync.parse_atom(evil)
    assert "Forbidden" in type(exc.value).__name__ or "Entities" in type(exc.value).__name__


def test_scan_without_feeds_does_nothing(seeded):
    assert sync.scan_opportunities.apply().get()["feeds"] == 0


def test_deal_stalled_notifies_owner_once(seeded, make_user):
    user = make_user("ana@example.com", roles={"operations": "manager"})
    opp = Opportunity(title="X", created_by=user.id)
    db.session.add(opp)
    db.session.flush()
    p = Proposal(opportunity_id=opp.id, title="Propuesta lenta", owner_user_id=user.id, status="sent")
    db.session.add(p)
    db.session.commit()
    db.session.execute(db.update(Proposal).values(updated_at=utcnow() - timedelta(days=30)))
    db.session.commit()
    assert alerts.deal_stalled.apply().get() == {"stalled": 1, "notified": 1}
    assert alerts.deal_stalled.apply().get() == {"stalled": 1, "notified": 0}


def test_failed_task_goes_to_dead_letter_queue(seeded):
    doc = Document(title="roto", storage_path="no/existe.txt", processing_status="pending")
    db.session.add(doc)
    db.session.commit()
    # Fichero inexistente: fallo de negocio, sin reintentos ni DLQ
    assert documents.process_upload.apply(args=[doc.id]).get()["status"] == "failed"
    assert db.session.scalar(db.select(FailedTask)) is None

    # Un fallo de infraestructura agota los reintentos y acaba en la DLQ
    from unittest import mock

    with mock.patch("app.tasks.documents.storage.absolute_path", side_effect=None) as path, \
            mock.patch("app.tasks.documents.extract_text", return_value="ok"), \
            mock.patch("app.tasks.documents.utcnow", side_effect=RuntimeError("BD caída")):
        path.return_value = "x"
        doc.processing_status = "pending"
        db.session.commit()
        result = documents.process_upload.apply(args=[doc.id])
    assert result.failed()
    failed = db.session.scalar(db.select(FailedTask))
    assert failed.task_name == "tasks.documents.process_upload" and failed.task_args == [doc.id]
    assert failed.error_type == "RuntimeError"
    assert db.session.scalar(db.select(AuditLog).filter_by(action="TASK_FAILED")) is not None


def test_recover_pending_requeues_stuck_documents(seeded, tmp_path):
    doc = Document(title="t", storage_path="x.txt", processing_status="pending")
    db.session.add(doc)
    db.session.commit()
    db.session.execute(db.update(Document).values(updated_at=utcnow() - timedelta(hours=1)))
    db.session.commit()
    assert documents.recover_pending.apply().get() == {"requeued": 1}
    assert db.session.get(Document, doc.id).processing_status == "failed"  # sin fichero


def test_gdpr_and_session_cleanup(seeded, make_user):
    user = make_user("ana@example.com")
    old = utcnow() - timedelta(days=400)
    db.session.add_all([
        Notification(user_id=user.id, notification_type="SYSTEM", title="vieja", read_at=old),
        Notification(user_id=user.id, notification_type="SYSTEM", title="sin leer"),
        AuditLog(action="LOGIN_SUCCESS", ip_address="1.2.3.4", user_agent="x", created_at=old),
        UserSession(user_id=user.id, refresh_jti="a" * 36, family_id="f" * 36, expires_at=old),
    ])
    db.session.commit()
    assert sync.gdpr_cleanup.apply().get() == {"notifications_deleted": 1}
    assert sync.anonymize_audit_logs.apply().get() == {"anonymized": 1}
    assert db.session.scalar(db.select(AuditLog).filter_by(action="LOGIN_SUCCESS")).ip_address is None
    assert sync.cleanup_sessions.apply().get() == {"sessions_deleted": 1}


def test_health_check_warns_superadmins_about_critical_events(seeded, make_user):
    admin = make_user("root@example.com", superadmin=True)
    assert system.platform_health_check.apply().get()["problems"] == []
    db.session.add(AuditLog(action="REFRESH_TOKEN_REUSE", severity="CRITICAL"))
    db.session.commit()
    problems = system.platform_health_check.apply().get()["problems"]
    assert problems and "críticos" in problems[0]
    note = db.session.scalar(db.select(Notification).filter_by(user_id=admin.id))
    assert note.notification_type == "SYSTEM" and note.priority == "high"


CODICE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2"
      xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
      xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2">
  <entry>
    <id>https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/123</id>
    <title>Servicio de mantenimiento evolutivo del portal web</title>
    <summary>Id licitación: 2026/45; Órgano: Ayuntamiento de Ejemplo; Importe: 99000 EUR</summary>
    <updated>2026-10-20T09:00:00.000+02:00</updated>
    <cac-place-ext:ContractFolderStatus>
      <cac-place-ext:LocatedContractingParty>
        <cac:Party><cac:PartyName><cbc:Name>Ayuntamiento de Ejemplo</cbc:Name></cac:PartyName></cac:Party>
      </cac-place-ext:LocatedContractingParty>
      <cac:ProcurementProject>
        <cac:BudgetAmount><cbc:EstimatedOverallContractAmount currencyID="EUR">99000</cbc:EstimatedOverallContractAmount></cac:BudgetAmount>
        <cac:RequiredCommodityClassification><cbc:ItemClassificationCode>72267000</cbc:ItemClassificationCode></cac:RequiredCommodityClassification>
      </cac:ProcurementProject>
      <cac:TenderingProcess><cac:TenderSubmissionDeadlinePeriod>
        <cbc:EndDate>2026-11-15</cbc:EndDate><cbc:EndTime>14:00:00</cbc:EndTime>
      </cac:TenderSubmissionDeadlinePeriod></cac:TenderingProcess>
    </cac-place-ext:ContractFolderStatus>
  </entry>
</feed>""".encode()


def test_codice_extension_of_public_procurement_feeds(seeded):
    item = sync.parse_atom(CODICE)[0]
    assert item["cpv_codes"] == ["72267000"]
    assert str(item["estimated_value"]) == "99000.00"
    assert item["entity"] == "Ayuntamiento de Ejemplo"
    assert item["deadline"].isoformat() == "2026-11-15T14:00:00"
    assert sync.ingest_feed("placsp", CODICE)["created"] == 1
    opp = db.session.scalar(db.select(Opportunity).filter_by(source="placsp"))
    assert opp.estimated_value_eur == 99000 and opp.status == "detected"
