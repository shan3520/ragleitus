"""Celery worker: runs document indexing and experiments outside the API process.

With METRICS_PORT set it serves Prometheus metrics (from every child
process), and with tracing configured each child sends its spans.

Used when TASK_QUEUE=celery. Start it with

    celery -A app.worker worker --loglevel=info

Tasks are acknowledged after they finish (acks_late), so a worker that dies
mid-task leaves the job in Redis for another worker. Documents whose job was
lost anyway (Redis restarted, the job expired) are found by
ingestion.requeue_stalled, which runs whenever a worker starts.
"""

from __future__ import annotations

import logging

import os
import tempfile

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown, worker_ready

from app.core.config import settings

# Tasks run in child processes; their metrics go through files that the main
# process's metrics server merges. Must be set before prometheus_client loads.
if settings.metrics_port and not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = tempfile.mkdtemp(prefix="ragleitus-metrics-")

from app.core import metrics, tracing  # noqa: E402
from app.services import experiment_runner, ingestion  # noqa: E402

logger = logging.getLogger(__name__)

celery_app = Celery("ragleitus", broker=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # One job at a time per process: indexing is CPU- and memory-heavy (embedding).
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="ragleitus.index_document")
def index_document_task(document_id: int) -> None:
    ingestion.index_document(document_id)


@celery_app.task(name="ragleitus.run_experiment")
def run_experiment_task(experiment_id: int) -> None:
    # A redelivered job finds the experiment already running and does nothing;
    # a run lost with its worker can be started again once it is stale.
    experiment_runner.run_experiment(experiment_id)


@worker_process_init.connect
def _start_tracing(**_kwargs) -> None:
    # Per child process: the exporter's background thread does not survive a fork.
    tracing.setup_tracing(f"{settings.otel_service_name}-worker")


@worker_process_shutdown.connect
def _flush_tracing(pid=None, **_kwargs) -> None:
    tracing.shutdown_tracing()
    if metrics.multiprocess_dir():
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(pid or os.getpid())


@worker_ready.connect
def _serve_metrics(**_kwargs) -> None:
    if settings.metrics_port and metrics.multiprocess_dir():
        metrics.start_server(settings.metrics_port, metrics.multiprocess_registry())


@worker_ready.connect
def _requeue_stalled_on_start(**_kwargs) -> None:
    # Logging is Celery's here (it redirects stdout/stderr into its loggers).
    try:
        ingestion.requeue_stalled()
    except Exception:
        logger.exception("Could not re-queue stalled documents")
