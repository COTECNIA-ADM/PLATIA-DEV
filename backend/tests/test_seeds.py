from decimal import Decimal

from app.extensions import db
from app.models import App, AppRole, LLMModelPricing, LLMServiceConfig
from app.seeds import run_seeds


def test_seeds_create_base_data(app):
    created = run_seeds()
    assert created == {"apps": 4, "roles": 13, "llm_services": 4, "llm_pricing": 3}
    codes = {a.code for a in db.session.scalars(db.select(App))}
    assert codes == {"operations", "analytics", "admin", "security"}
    assert db.session.get(LLMServiceConfig, "proposal_generation").fallback_model


def test_seeds_are_idempotent_and_keep_edits(app):
    run_seeds()
    pricing = db.session.scalars(db.select(LLMModelPricing)).first()
    pricing.input_usd_per_mtok = Decimal("9.99")  # editado desde Admin
    db.session.commit()

    assert run_seeds() == {"apps": 0, "roles": 0, "llm_services": 0, "llm_pricing": 0}
    assert db.session.get(LLMModelPricing, (pricing.provider, pricing.model_name, pricing.effective_date)).input_usd_per_mtok == Decimal("9.99")
    assert db.session.scalar(db.select(db.func.count()).select_from(AppRole)) == 13


def test_admin_roles_skip_module_lists_and_others_are_explicit(app):
    run_seeds()
    roles = {(r.app.code, r.code): r for r in db.session.scalars(db.select(AppRole))}
    assert roles[("operations", "admin")].is_admin is True
    assert roles[("operations", "viewer")].is_admin is False
    assert roles[("operations", "viewer")].permissions["ai_modules_access"] == []
    assert "write" not in roles[("admin", "auditor")].permissions["users"]
