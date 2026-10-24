from decimal import Decimal

from app.extensions import db
from app.models import App, AppRole, LLMModelPricing, LLMServiceConfig
from app.seeds import run_seeds


def test_seeds_create_base_data(app):
    created = run_seeds()
    assert created == {"apps": 4, "roles": 13, "llm_services": 13, "llm_pricing": 3,
                       "service_lines": 6, "proposal_templates": 5, "prompts": 14, "budgets": 3,
                       "human_baselines": 5, "intent_patterns": 18, "agents": 3}
    codes = {a.code for a in db.session.scalars(db.select(App))}
    assert codes == {"operations", "analytics", "admin", "security"}
    assert db.session.get(LLMServiceConfig, "proposal_generation").fallback_model


def test_seeds_are_idempotent_and_keep_edits(app):
    run_seeds()
    pricing = db.session.scalars(db.select(LLMModelPricing)).first()
    pricing.input_usd_per_mtok = Decimal("9.99")  # editado desde Admin
    db.session.commit()

    assert set(run_seeds().values()) == {0}
    assert db.session.get(LLMModelPricing, (pricing.provider, pricing.model_name, pricing.effective_date)).input_usd_per_mtok == Decimal("9.99")
    assert db.session.scalar(db.select(db.func.count()).select_from(AppRole)) == 13


def test_admin_roles_skip_module_lists_and_others_are_explicit(app):
    run_seeds()
    roles = {(r.app.code, r.code): r for r in db.session.scalars(db.select(AppRole))}
    assert roles[("operations", "admin")].is_admin is True
    assert roles[("operations", "viewer")].is_admin is False
    assert roles[("operations", "viewer")].permissions["ai_modules_access"] == []
    assert "write" not in roles[("admin", "auditor")].permissions["users"]


def test_seeded_permissions_only_use_registered_modules(app):
    """Un módulo mal escrito en un rol sería un permiso que ningún endpoint comprueba."""
    from app.security.registry import validate_permissions

    run_seeds()
    for role in db.session.scalars(db.select(AppRole)):
        assert validate_permissions(role.permissions) == [], (role.app.code, role.code)


def test_seeded_templates_are_valid(app):
    from app.api.schemas import TemplateIn
    from app.models import ProposalTemplate

    run_seeds()
    templates = db.session.scalars(db.select(ProposalTemplate)).all()
    assert {t.proposal_type for t in templates} == {"base", "competitive", "premium", "custom", "executive"}
    for t in templates:
        TemplateIn.model_validate({"name": t.name, "proposal_type": t.proposal_type, "sections": t.sections})


def test_seeded_services_point_to_seeded_prompts(app):
    """Cada servicio con prompt tiene una versión activa, y el prompt usa variables conocidas."""
    from app.ai import prompts
    from app.models import Prompt

    run_seeds()
    for config in db.session.scalars(db.select(LLMServiceConfig)):
        if config.prompt_name:
            active = prompts.get_active(config.prompt_name)
            assert active.version == 1 and active.content_hash
            # Las instrucciones estables no llevan variables (así se pueden cachear)
            assert prompts.variables_of(active.system_prompt) == set()
    assert db.session.scalar(db.select(db.func.count()).select_from(Prompt)) == 14
