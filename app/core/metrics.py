"""Prometheus metrics.

Served on their own port (METRICS_PORT), not on the API's: the web app
forwards /backend/* to the API, so a /metrics route there would be public.
Prometheus scrapes the API and the worker on the internal network.

Metrics carry no user ids or text: routes are path templates
(/api/documents/{document_id}), and model names, which users choose, are
limited to a bounded set of label values.

The Celery worker runs tasks in child processes; there the metrics go
through prometheus_client's multiprocess mode (PROMETHEUS_MULTIPROC_DIR),
which the worker sets up before the children start.
"""

from __future__ import annotations

import logging
import os
import threading

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger(__name__)

LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)

HTTP_REQUESTS = Counter(
    "ragforge_http_requests_total", "HTTP requests handled by the API.", ["method", "route", "status"]
)
HTTP_DURATION = Histogram(
    "ragforge_http_request_duration_seconds", "Time to handle an HTTP request.", ["method", "route"],
    buckets=LATENCY_BUCKETS,
)
LLM_CALLS = Counter(
    "ragforge_llm_calls_total", "Calls to LLM providers.", ["provider", "model", "operation", "status"]
)
LLM_LATENCY = Histogram(
    "ragforge_llm_latency_seconds", "Duration of successful LLM calls.", ["provider", "operation"],
    buckets=LATENCY_BUCKETS,
)
LLM_TTFT = Histogram(
    "ragforge_llm_time_to_first_token_seconds", "Time to the first streamed token.", ["provider"],
    buckets=LATENCY_BUCKETS,
)
LLM_TOKENS = Counter(
    "ragforge_llm_tokens_total", "Tokens sent to and received from LLM providers.",
    ["provider", "model", "operation", "kind"],
)
LLM_COST = Counter(
    "ragforge_llm_cost_usd_total", "Estimated cost of LLM calls in US dollars (priced models only).",
    ["provider", "model", "operation"],
)
INDEXING = Counter("ragforge_indexing_total", "Document index runs by outcome.", ["outcome"])
INDEXING_DURATION = Histogram(
    "ragforge_indexing_duration_seconds", "Time to chunk, embed and store a document.", buckets=LATENCY_BUCKETS
)
RERANK_DURATION = Histogram(
    "ragforge_rerank_duration_seconds", "Time to rerank retrieved passages.", ["backend"],
    buckets=LATENCY_BUCKETS,
)
RETRIEVAL_DURATION = Histogram(
    "ragforge_retrieval_duration_seconds", "Time to retrieve passages for a question.", ["strategy"],
    buckets=LATENCY_BUCKETS,
)

# Model names are chosen by users; past this many distinct ones, new names
# are counted as "other" so a stream of made-up names cannot grow the series
# without bound.
MAX_MODEL_LABELS = 100
_model_labels: set[str] = set()
_model_lock = threading.Lock()


def model_label(provider: str, model: str | None) -> str:
    if provider == "custom":
        return "self-hosted"  # any name a server accepts; don't label by it
    label = (model or "unknown")[:80]
    with _model_lock:
        if label in _model_labels:
            return label
        if len(_model_labels) >= MAX_MODEL_LABELS:
            return "other"
        _model_labels.add(label)
        return label


def observe_llm_call(
    *,
    provider: str,
    model: str | None,
    operation: str,
    ok: bool,
    latency_ms: float | None,
    ttft_ms: float | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_usd: float | None,
) -> None:
    model = model_label(provider, model)
    LLM_CALLS.labels(provider, model, operation, "ok" if ok else "error").inc()
    if ok and latency_ms is not None:
        LLM_LATENCY.labels(provider, operation).observe(latency_ms / 1000)
    if ttft_ms is not None:
        LLM_TTFT.labels(provider).observe(ttft_ms / 1000)
    if prompt_tokens:
        LLM_TOKENS.labels(provider, model, operation, "prompt").inc(prompt_tokens)
    if completion_tokens:
        LLM_TOKENS.labels(provider, model, operation, "completion").inc(completion_tokens)
    if cost_usd:
        LLM_COST.labels(provider, model, operation).inc(cost_usd)


class DocumentQueueCollector:
    """Documents waiting to be indexed or being indexed, read at scrape time."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def collect(self):
        from sqlalchemy import func

        from app.models.document import Document

        gauge = GaugeMetricFamily("ragforge_documents_queued", "Documents pending or indexing.", labels=["status"])
        session = self._session_factory()
        try:
            counts = dict(
                session.query(Document.status, func.count())
                .filter(Document.status.in_(("pending", "indexing")))
                .group_by(Document.status)
                .all()
            )
        except Exception:
            logger.exception("Could not count queued documents for metrics")
            return
        finally:
            session.close()
        for status in ("pending", "indexing"):
            gauge.add_metric([status], counts.get(status, 0))
        yield gauge


_started_port: int | None = None


def start_server(port: int, registry: CollectorRegistry | None = None) -> bool:
    """Serve /metrics on `port` (once per process). Returns whether it is serving."""
    global _started_port
    if not port:
        return False
    if _started_port is not None:
        return True
    try:
        start_http_server(port, registry=registry) if registry is not None else start_http_server(port)
    except OSError:
        logger.exception("Could not serve metrics", extra={"port": port})
        return False
    _started_port = port
    logger.info("Serving Prometheus metrics", extra={"port": port})
    return True


def multiprocess_registry() -> CollectorRegistry:
    """A registry that merges the metrics every worker child process wrote."""
    from prometheus_client import multiprocess

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return registry


def multiprocess_dir() -> str | None:
    return os.environ.get("PROMETHEUS_MULTIPROC_DIR") or os.environ.get("prometheus_multiproc_dir")


__all__ = [
    "DocumentQueueCollector", "Gauge", "HTTP_DURATION", "HTTP_REQUESTS", "INDEXING", "INDEXING_DURATION",
    "RERANK_DURATION", "RETRIEVAL_DURATION", "model_label", "multiprocess_dir", "multiprocess_registry", "observe_llm_call",
    "start_server",
]
