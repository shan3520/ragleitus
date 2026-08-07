import logging
import json
import io
from src.core.logging import setup_logging, JSONFormatter

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
