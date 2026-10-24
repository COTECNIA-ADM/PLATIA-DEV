"""Punto de entrada de los workers y de Celery Beat (Capítulo 8).

    celery -A celery_app worker -Q default,priority,sync,crm
    celery -A celery_app worker -Q ai,documents
    celery -A celery_app beat

Mismo código que el backend: las tareas están en app/tasks/ y la configuración
de colas, routing y planificación en app/queue.py.
"""
from app import create_app
from app.queue import celery

flask_app = create_app()

__all__ = ["celery", "flask_app"]
