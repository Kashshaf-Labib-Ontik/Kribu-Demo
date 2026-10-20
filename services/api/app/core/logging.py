"""Standard-library logging with request correlation.

Never log access tokens, prompts, document text, or resource content.
"""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.core.request_context import current_correlation_id, current_request_id

LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "correlation_id=%(correlation_id)s request_id=%(request_id)s %(message)s"
)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = current_correlation_id() or "-"
        record.request_id = current_request_id() or "-"
        return True


def configure_logging(settings: Settings) -> None:
    """Attach one correlated handler to the ``app`` logger (idempotent)."""
    logger = logging.getLogger("app")
    logger.setLevel(settings.log_level)
    if any(isinstance(handler, _CorrelatedHandler) for handler in logger.handlers):
        return
    handler = _CorrelatedHandler()
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False


class _CorrelatedHandler(logging.StreamHandler):  # type: ignore[type-arg]
    pass
