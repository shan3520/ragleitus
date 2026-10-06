"""OpenTelemetry traces, sent over OTLP and/or to Langfuse.

Off unless configured: with no OTEL_EXPORTER_OTLP_ENDPOINT and no Langfuse
keys, the tracer is OpenTelemetry's no-op one and spans cost nothing.

- OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://jaeger:4318): any OTLP/HTTP
  collector or backend (Jaeger, Tempo, Honeycomb, an OpenTelemetry Collector).
- LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY (+ LANGFUSE_HOST): Langfuse's
  OTLP endpoint, /api/public/otel, authenticated with the key pair. Spans
  follow the OpenTelemetry GenAI conventions (gen_ai.*), which Langfuse
  reads as generations with model, token usage and cost.

Spans carry ids, models, token counts and timings. Prompt and answer text
are added only with TRACE_CONTENT=true. Keys are never put on spans.
"""

from __future__ import annotations

import base64
import logging
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

from app.core.config import settings

logger = logging.getLogger(__name__)

tracer = trace.get_tracer("ragleitus")

_provider: TracerProvider | None = None


def exporter_targets() -> list[tuple[str, dict[str, str]]]:
    """Where spans go: (OTLP/HTTP traces endpoint, headers) for each configured backend."""
    targets: list[tuple[str, dict[str, str]]] = []
    if settings.otel_exporter_otlp_endpoint:
        targets.append((settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces", {}))
    public, secret = settings.langfuse_public_key.get_secret_value(), settings.langfuse_secret_key.get_secret_value()
    if public and secret:
        token = base64.b64encode(f"{public}:{secret}".encode()).decode()
        targets.append(
            (settings.langfuse_host.rstrip("/") + "/api/public/otel/v1/traces", {"Authorization": f"Basic {token}"})
        )
    return targets


def exporters() -> list[SpanExporter]:
    """The configured exporters (none when tracing is off)."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return [OTLPSpanExporter(endpoint=endpoint, headers=headers) for endpoint, headers in exporter_targets()]


def setup_tracing(service_name: str | None = None, extra_exporters: list[SpanExporter] | None = None, batch: bool = True) -> bool:
    """Install a tracer provider if any exporter is configured. Returns whether tracing is on.

    `extra_exporters` (tests) are added synchronously; configured exporters
    send in the background in batches.
    """
    global _provider
    configured = exporters()
    if not configured and not extra_exporters:
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name or settings.otel_service_name}))
    for exporter in configured:
        provider.add_span_processor(BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter))
    for exporter in extra_exporters or []:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    if _provider is None:
        trace.set_tracer_provider(provider)
    else:  # already set once in this process (tests): route spans to the new one
        _provider.shutdown()
    _provider = provider
    _ProxyTracer.provider = provider
    logger.info("Tracing on", extra={"exporters": len(configured) + len(extra_exporters or [])})
    return True


def shutdown_tracing() -> None:
    if _provider is not None:
        _provider.shutdown()


class _ProxyTracer:
    """Hands out tracers from the provider set up last (OpenTelemetry only
    lets the global provider be set once per process)."""

    provider: TracerProvider | None = None


def _tracer():
    return _ProxyTracer.provider.get_tracer("ragleitus") if _ProxyTracer.provider else tracer


def tracing_enabled() -> bool:
    return _ProxyTracer.provider is not None


@contextmanager
def span(name: str, **attributes):
    """A span with the given attributes (None values are left out)."""
    with _tracer().start_as_current_span(name) as current:
        set_attributes(current, **attributes)
        yield current


def start_span(name: str, **attributes):
    """A span that is not made current; end it yourself. For async generators,
    where a current span would not survive across yields."""
    started = _tracer().start_span(name)
    set_attributes(started, **attributes)
    return started


def set_attributes(current, **attributes) -> None:
    for key, value in attributes.items():
        if value is not None:
            current.set_attribute(key.replace("__", "."), value)


def record_content(current, *, prompt: str | None = None, completion: str | None = None) -> None:
    """Prompt and answer text on a span, only when TRACE_CONTENT is on."""
    if not settings.trace_content:
        return
    if prompt is not None:
        current.set_attribute("gen_ai.prompt", prompt[:20_000])
        current.set_attribute("input.value", prompt[:20_000])
    if completion is not None:
        current.set_attribute("gen_ai.completion", completion[:20_000])
        current.set_attribute("output.value", completion[:20_000])


def current_trace_ids() -> tuple[str, str] | None:
    """(trace id, span id) of the active span, as hex, for log lines."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")


def instrument_app(app) -> None:
    """Server spans for every request, when tracing is on."""
    if not tracing_enabled():
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, tracer_provider=_ProxyTracer.provider, excluded_urls="health")
