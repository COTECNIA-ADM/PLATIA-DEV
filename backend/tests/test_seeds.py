from decimal import Decimal

from app.extensions import db
from app.models import App, AppRole, LLMModelPricing, LLMServiceConfig
from app.seeds import run_seeds


def test_seeds_create_base_data(app):
    created = run_seeds()
    assert created == {"apps": 4, "roles": 8, "llm_services": 4, "llm_pricing": 3}
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
    assert db.session.scalar(db.select(db.func.count()).select_from(AppRole)) == 8
