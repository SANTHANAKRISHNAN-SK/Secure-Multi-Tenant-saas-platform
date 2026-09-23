"""
logging_config.py
------------------
Configures application-wide structured logging. Under ECS Fargate,
stdout/stderr are shipped to CloudWatch Logs automatically by the
awslogs driver configured in the task definition, so we simply log
JSON lines to stdout -- no direct CloudWatch API calls are needed
from inside the container (that would add latency and a hard
dependency on the network path for every log line).
"""

import json
import logging
import sys
import time

from config import config


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON for CloudWatch Logs Insights."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach any extra structured fields passed via logger.info(..., extra={...})
        for key in ("tenant", "user_id", "role", "path", "request_id"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> logging.Logger:
    """Sets up the root application logger. Call once at startup."""
    logger = logging.getLogger("tenant_saas")
    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    # Avoid duplicate handlers if configure_logging() is called twice
    # (e.g. under a WSGI reloader).
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    logger.propagate = False
    return logger


app_logger = configure_logging()
