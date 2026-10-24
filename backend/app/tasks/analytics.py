"""Inteligencia comercial programada (cola ``default``, Capítulo 23).

- ``take_snapshot``: foto diaria de la cartera abierta (total y por fase), para
  comparar periodos y ver su evolución. Una por día: repetirla la sustituye.
- ``compute_heatmap``: puntuación del mapa de oportunidad del mes en curso. El
  día 1 también cierra el mes anterior con sus datos completos.
"""
from datetime import timedelta

from ..models import utcnow
from ..queue import PlatformTask, celery
from ..services import analytics, market


@celery.task(name="tasks.analytics.take_snapshot", base=PlatformTask, bind=True)
def take_snapshot(self) -> dict:
    return analytics.take_snapshot()


@celery.task(name="tasks.analytics.compute_heatmap", base=PlatformTask, bind=True)
def compute_heatmap(self, period: str | None = None) -> dict:
    now = utcnow()
    results = [market.compute(period, now)]
    if period is None and now.day == 1:
        results.append(market.compute(market.current_period(now - timedelta(days=1)), now))
    return {"periods": results}
