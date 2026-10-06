import logging
import json
import io
from app.core.logging import setup_logging, JSONFormatter

def test_json_logging():
    # Capture log output
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(JSONFormatter())
    
    logger = logging.getLogger("test_logger")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.addHandler(handler)
    
    logger.info("Test message")
    
    log_output = log_stream.getvalue().strip()
    
    try:
        log_record = json.loads(log_output)
    except json.JSONDecodeError:
        assert False, f"Log output is not valid JSON: {log_output}"
        
    assert "timestamp" in log_record
    assert log_record["level"] == "INFO"
    assert log_record["name"] == "test_logger"
    assert log_record["message"] == "Test message"


def _log_line(**extra):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger("test_logger_extra")
    logger.setLevel(logging.INFO)
    logger.handlers = [handler]
    logger.propagate = False
    logger.info("request completed", extra=extra)
    return json.loads(stream.getvalue().strip())


def test_extra_fields_and_a_utc_timestamp_are_written():
    record = _log_line(request_id="abc123", status=200, elapsed_ms=12.5, path="/api/documents")
    assert record["request_id"] == "abc123" and record["status"] == 200 and record["elapsed_ms"] == 12.5
    assert record["path"] == "/api/documents"
    assert record["timestamp"].endswith("Z") and "+" not in record["timestamp"]
    # Standard LogRecord attributes are not dumped into the line.
    assert "lineno" not in record and "args" not in record and "trace_id" not in record


def test_the_active_trace_is_on_the_log_line():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app.core import tracing

    tracing.setup_tracing("test", extra_exporters=[InMemorySpanExporter()])
    with tracing.span("work") as current:
        record = _log_line(document_id=7)
    context = current.get_span_context()
    assert record["trace_id"] == format(context.trace_id, "032x")
    assert record["span_id"] == format(context.span_id, "016x")
    assert record["document_id"] == 7
