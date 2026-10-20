"""Celery configuration for the low-volume, single-worker ingestion queue."""

from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "kribu_ingestion",
    broker=settings.celery_broker_url.get_secret_value(),
    include=["app.ingestion.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.ingestion_task_timeout_seconds,
    task_soft_time_limit=max(1, settings.ingestion_task_timeout_seconds - 10),
    beat_schedule={
        "dispatch-document-ingestion-outbox": {
            "task": "app.ingestion.tasks.dispatch_ingestion_outbox",
            "schedule": settings.ingestion_poll_seconds,
        }
    },
)
