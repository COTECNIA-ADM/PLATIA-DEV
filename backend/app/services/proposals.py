"""Propuestas: cinco tipos, una máquina de estados (Capítulo 9).

- base: flujo simple; la revisión es opcional (se puede enviar desde borrador).
- competitive: necesita un análisis de competencia adjunto antes de revisión.
- premium y executive: doble revisión, técnica y ejecutiva.
- custom: la aprueba el responsable de área antes de enviarse.

A ``approved`` solo se llega con revisiones (POST /reviews), nunca cambiando el
estado a mano. Quien revisa no puede ser el responsable de la propuesta
(principio de los cuatro ojos), salvo un administrador.
"""
import structlog

from ..errors import BusinessRuleError, ForbiddenError
from ..models import Opportunity, Proposal, ProposalReview, ProposalSection, ProposalTemplate, utcnow
from . import opportunities as opp_service

log = structlog.get_logger(__name__)

_REVIEWED_FLOW = {
    "draft": {"in_review", "archived"},
    "in_review": {"draft"},  # retirar de revisión; aprobar va por /reviews
    "approved": {"sent", "draft", "archived"},
    "sent": {"won", "lost"},
    "won": {"archived"},
    "lost": {"archived"},
    "archived": set(),
}
TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "base": {**_REVIEWED_FLOW, "draft": {"in_review", "sent", "archived"}},
    "competitive": _REVIEWED_FLOW,
    "premium": _REVIEWED_FLOW,
    "custom": _REVIEWED_FLOW,
    "executive": _REVIEWED_FLOW,
}
REQUIRED_REVIEWS: dict[str, set[str]] = {
    "base": {"any"},
    "competitive": {"any"},
    "premium": {"technical", "executive"},
    "executive": {"technical", "executive"},
    "custom": {"area"},
}
EDITABLE_STATUSES = {"draft"}

# Secciones por defecto si no se elige plantilla
DEFAULT_SECTIONS = [
    ("resumen_ejecutivo", "Resumen ejecutivo"),
    ("contexto", "Contexto y necesidades del cliente"),
    ("solucion", "Solución propuesta"),
    ("metodologia", "Metodología y plan de trabajo"),
    ("equipo", "Equipo"),
    ("presupuesto", "Presupuesto"),
]
EXTRA_SECTIONS = {
    "competitive": [("diferenciales", "Diferenciales frente a la competencia")],
    "premium": [("valor_estrategico", "Valor estratégico")],
    "executive": [("mensaje_direccion", "Mensaje para la dirección")],
}

# Estado de la propuesta -> estado al que avanza la oportunidad (si la transición es válida)
OPPORTUNITY_SYNC = {
    "in_review": "proposal_review",
    "sent": "proposal_sent",
    "won": "won",
    "lost": "lost",
}


def allowed_transitions(proposal: Proposal) -> list[str]:
    return sorted(TRANSITIONS[proposal.proposal_type].get(proposal.status, set()))


def build_sections(proposal: Proposal, template: ProposalTemplate | None) -> None:
    if template is not None:
        items = sorted(template.sections or [], key=lambda s: s.get("order", 0))
        pairs = [(s["key"], s["title"]) for s in items]
    else:
        pairs = DEFAULT_SECTIONS + EXTRA_SECTIONS.get(proposal.proposal_type, [])
    for position, (key, title) in enumerate(pairs):
        proposal.sections.append(ProposalSection(key=key, title=title, position=position,
                                                 created_by=proposal.created_by))


def ensure_editable(proposal: Proposal) -> None:
    if proposal.status not in EDITABLE_STATUSES:
        raise BusinessRuleError("Solo se puede editar una propuesta en borrador.")


def _active_sections(proposal: Proposal) -> list[ProposalSection]:
    return [s for s in proposal.sections if s.is_active]


def _check_preconditions(proposal: Proposal, target: str) -> None:
    if target == "in_review" or (target == "sent" and proposal.status == "draft"):
        if not any((s.final_content or "").strip() for s in _active_sections(proposal)):
            raise BusinessRuleError("La propuesta no tiene contenido en ninguna sección.")
    if target == "in_review" and proposal.proposal_type == "competitive":
        if not any(a.kind == "competitive_analysis" and a.is_active for a in proposal.attachments):
            raise BusinessRuleError(
                "Las propuestas competitivas necesitan un análisis de competencia adjunto "
                "antes de entrar en revisión."
            )
    if target == "sent" and proposal.total_amount_eur is None:
        raise BusinessRuleError("Indica el importe total antes de enviar la propuesta.")


def _sync_opportunity(proposal: Proposal, comment: str | None) -> str | None:
    target = OPPORTUNITY_SYNC.get(proposal.status)
    opp: Opportunity = proposal.opportunity
    if target is None or opp is None or opp.status == target:
        return None
    if target not in opp_service.TRANSITIONS.get(opp.status, set()):
        log.info("opportunity_sync_skipped", opportunity_id=opp.id, status=opp.status, target=target)
        return None
    reason = comment or f"Propuesta {proposal.id}: {proposal.status}"
    opp_service.change_status(opp, target, reason)
    return target


def change_status(proposal: Proposal, target: str, can_send: bool, comment: str | None = None) -> dict:
    """Cambia el estado validando el grafo y las reglas del tipo. No hace commit."""
    if target == "approved":
        raise BusinessRuleError("Para aprobar una propuesta, registra las revisiones en /reviews.")
    if target not in allowed_transitions(proposal):
        raise BusinessRuleError(
            f"No se puede pasar de '{proposal.status}' a '{target}' en una propuesta "
            f"de tipo '{proposal.proposal_type}'.",
            allowed=[t for t in allowed_transitions(proposal) if t != "approved"],
        )
    if target == "sent" and not can_send:
        raise ForbiddenError("No tienes permiso para enviar propuestas al cliente.")
    if target in ("lost",) and not comment:
        raise BusinessRuleError("Indica el motivo en 'comment'.")
    _check_preconditions(proposal, target)
    previous = proposal.status
    proposal.status = target
    if target == "in_review":
        proposal.review_round += 1
    if target == "sent":
        proposal.sent_at = utcnow()
    synced = _sync_opportunity(proposal, comment)
    return {"from": previous, "to": target, "opportunity_status": synced}


def required_reviews(proposal: Proposal) -> set[str]:
    return REQUIRED_REVIEWS[proposal.proposal_type]


def add_review(proposal: Proposal, reviewer_id: int, reviewer_is_admin: bool, kind: str,
               decision: str, comment: str | None) -> dict:
    """Registra una revisión de la ronda actual. Aprueba la propuesta cuando están
    todas las revisiones necesarias; una sola revisión negativa la devuelve a borrador.
    No hace commit."""
    if proposal.status != "in_review":
        raise BusinessRuleError("La propuesta no está en revisión.")
    owner = proposal.owner_user_id or proposal.created_by
    if reviewer_id == owner and not reviewer_is_admin:
        raise ForbiddenError("No puedes revisar tu propia propuesta.")
    required = required_reviews(proposal)
    if "any" not in required and kind not in required:
        raise BusinessRuleError(
            f"Esta propuesta necesita revisiones de tipo: {', '.join(sorted(required))}."
        )
    current = [r for r in proposal.reviews if r.review_round == proposal.review_round and r.is_active]
    if any(r.kind == kind and r.reviewer_user_id == reviewer_id for r in current):
        raise BusinessRuleError("Ya has registrado esta revisión en la ronda actual.")
    if decision == "reject" and not comment:
        raise BusinessRuleError("Explica en 'comment' qué hay que cambiar.")
    review = ProposalReview(review_round=proposal.review_round, reviewer_user_id=reviewer_id,
                            kind=kind, decision=decision, comment=comment, created_by=reviewer_id)
    proposal.reviews.append(review)
    if decision == "reject":
        proposal.status = "draft"
        return {"review": review, "status": "draft", "pending": sorted(required)}
    approved_kinds = {r.kind for r in current + [review] if r.decision == "approve"}
    pending = set() if "any" in required else required - approved_kinds
    if not pending:
        proposal.status = "approved"
        proposal.reviewed_by = reviewer_id
        proposal.reviewed_at = utcnow()
    return {"review": review, "status": proposal.status, "pending": sorted(pending)}
