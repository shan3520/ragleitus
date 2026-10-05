"""Celery worker: runs document indexing and experiments outside the API process.

Used when TASK_QUEUE=celery. Start it with

    celery -A app.worker worker --loglevel=info

Tasks are acknowledged after they finish (acks_late), so a worker that dies
mid-task leaves the job in Redis for another worker. Documents whose job was
lost anyway (Redis restarted, the job expired) are found by
ingestion.requeue_stalled, which runs whenever a worker starts.
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_ready

from app.core.config import settings
from app.services import experiment_runner, ingestion

logger = logging.getLogger(__name__)

celery_app = Celery("ragforge", broker=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # One job at a time per process: indexing is CPU- and memory-heavy (embedding).
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="ragforge.index_document")
def index_document_task(document_id: int) -> None:
    ingestion.index_document(document_id)


@celery_app.task(name="ragforge.run_experiment")
def run_experiment_task(experiment_id: int) -> None:
    # A redelivered job finds the experiment already running and does nothing;
    # a run lost with its worker can be started again once it is stale.
    experiment_runner.run_experiment(experiment_id)


@worker_ready.connect
def _requeue_stalled_on_start(**_kwargs) -> None:
    # Logging is Celery's here (it redirects stdout/stderr into its loggers).
    try:
        ingestion.requeue_stalled()
    except Exception:
        logger.exception("Could not re-queue stalled documents")
