"""Coste de cada llamada con la tabla de precios vigente (Capítulo 11).

El precio no está en el código: se lee de ``llm_model_pricing`` (la fila con la
fecha de efecto más reciente que no sea futura). Si un modelo no tiene precio,
el coste queda en 0 y se avisa en el log para que se dé de alta.
"""
from datetime import date
from decimal import Decimal

import structlog

from ..extensions import db
from ..models import LLMModelPricing

log = structlog.get_logger(__name__)
MILLION = Decimal(1_000_000)
CACHE_READ_FACTOR = Decimal("0.1")
CACHE_WRITE_FACTOR = Decimal("1.25")


def price_for(provider: str, model: str, on: date | None = None) -> LLMModelPricing | None:
    on = on or date.today()
    return db.session.scalars(
        db.select(LLMModelPricing)
        .where(LLMModelPricing.provider == provider, LLMModelPricing.model_name == model,
               LLMModelPricing.effective_date <= on)
        .order_by(LLMModelPricing.effective_date.desc())
    ).first()


def cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0,
             cache_write_tokens: int = 0) -> Decimal:
    if not (input_tokens or output_tokens or cache_read_tokens or cache_write_tokens):
        return Decimal("0")
    price = price_for(provider, model)
    if price is None:
        log.warning("llm_price_missing", provider=provider, model=model)
        return Decimal("0")
    inp = Decimal(price.input_usd_per_mtok)
    read = Decimal(price.cache_read_usd_per_mtok) if price.cache_read_usd_per_mtok is not None \
        else inp * CACHE_READ_FACTOR
    write = Decimal(price.cache_write_usd_per_mtok) if price.cache_write_usd_per_mtok is not None \
        else inp * CACHE_WRITE_FACTOR
    total = (Decimal(input_tokens) * inp + Decimal(output_tokens) * Decimal(price.output_usd_per_mtok)
             + Decimal(cache_read_tokens) * read + Decimal(cache_write_tokens) * write) / MILLION
    return total.quantize(Decimal("0.000001"))
