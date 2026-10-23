import re
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect

from app.extensions import db
from app.models import (
    AuditLog,
    Client,
    Contact,
    Document,
    Opportunity,
    Proposal,
    ProposalSection,
    User,
)

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"


def _all_models():
    return [m.class_ for m in db.Model.registry.mappers]


def test_every_model_declares_a_known_bind():
    for model in _all_models():
        assert getattr(model, "__bind_key__", None) in {"core", "operations", "analytics"}, model


def test_business_models_have_soft_delete_and_audit():
    for model in _all_models():
        if model.__bind_key__ != "operations":
            continue
        cols = set(model.__table__.columns.keys())
        assert {"is_active", "deleted_at", "created_at", "updated_at", "created_by"} <= cols, model


def test_tables_are_created_in_their_own_schema(app):
    core = set(inspect(db.engines["core"]).get_table_names())
    ops = set(inspect(db.engines["operations"]).get_table_names())
    analytics = set(inspect(db.engines["analytics"]).get_table_names())
    assert {"users", "apps", "app_roles", "llm_usage_log", "prompts"} <= core
    assert {"clients", "opportunities", "documents", "proposals"} <= ops
    assert {"funnel_stages", "analytics_snapshots"} <= analytics
    assert not core & ops and not ops & analytics


def test_initial_migration_creates_every_table():
    text = "".join(p.read_text(encoding="utf-8") for p in MIGRATIONS.glob("*.py"))
    in_migrations = set(re.findall(r"op\.create_table\('(\w+)'", text))
    in_models = {m.__tablename__ for m in _all_models()}
    assert in_models == in_migrations


def test_timestamp_defaults_are_functions_not_fixed_values():
    # Con default=datetime.now(...) todas las filas compartirían la fecha de arranque
    for model in _all_models():
        for name in ("created_at", "updated_at"):
            col = model.__table__.columns.get(name)
            if col is not None:
                assert col.default.is_callable, f"{model.__name__}.{name}"


def test_updated_at_changes_on_update(app):
    client = Client(name="Acme")
    db.session.add(client)
    db.session.commit()
    before = client.updated_at
    client.updated_at = before - timedelta(days=1)  # simula una fila antigua
    db.session.commit()
    client.name = "Acme S.A."
    db.session.commit()
    assert client.updated_at > before - timedelta(days=1)


def test_soft_delete_hides_rows_from_active_queries(app):
    keep, gone = Client(name="Activo"), Client(name="Borrado")
    db.session.add_all([keep, gone])
    db.session.commit()

    gone.soft_delete()
    db.session.commit()

    names = [c.name for c in db.session.scalars(Client.select_active())]
    assert names == ["Activo"]
    assert gone.deleted_at is not None
    assert db.session.get(Client, gone.id) is not None  # la fila sigue existiendo

    gone.restore()
    db.session.commit()
    assert len(db.session.scalars(Client.select_active()).all()) == 2


def test_client_relations_and_opportunity_phase(app):
    client = Client(name="Cliente B2B", segment="A")
    client.contacts.append(Contact(full_name="Ana Pérez", is_primary=True))
    opp = Opportunity(title="Migración a la nube", client=client, status="proposal_sent")
    db.session.add(client)
    db.session.commit()
    assert opp.funnel_phase == "F4"
    assert client.opportunities[0].title == "Migración a la nube"
    assert client.contacts[0].client_id == client.id


def test_every_opportunity_status_maps_to_a_funnel_phase():
    assert len(Opportunity.STATUSES) == 12
    assert set(Opportunity.STATUS_PHASE.values()) == {"F1", "F2", "F3", "F4", "F5"}


def test_proposal_section_prefers_human_edit(app):
    opp = Opportunity(title="Oportunidad")
    proposal = Proposal(opportunity=opp, title="Propuesta")
    section = ProposalSection(proposal=proposal, key="resumen", title="Resumen", ai_content="IA")
    db.session.add(proposal)
    db.session.commit()
    assert section.final_content == "IA"
    section.edited_content = "Editado"
    assert section.final_content == "Editado"


def test_document_versions_link_to_parent(app):
    v1 = Document(title="Pliego", file_hash="a" * 64)
    db.session.add(v1)
    db.session.commit()
    v2 = Document(title="Pliego", parent_version=v1, version_number=2, file_hash="b" * 64)
    v1.is_current_version = False
    db.session.add(v2)
    db.session.commit()
    assert v2.parent_version_id == v1.id
    assert v1.processing_status == "pending"


def test_user_email_is_unique(app):
    db.session.add_all([User(email="a@example.com", full_name="A"), User(email="a@example.com", full_name="B")])
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_audit_log_defaults(app):
    entry = AuditLog(action="LOGIN_SUCCESS", user_id=1)
    db.session.add(entry)
    db.session.commit()
    assert entry.severity == "INFO" and entry.created_at is not None
