"""Structured job logging (PRD NFR-9 관측성).

Every collector emits key/value events so coverage and failure can be counted
per source without parsing prose.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Install a structlog pipeline over stdlib logging. Idempotent."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    # A Windows console defaults to the machine's ANSI codepage (cp949 on the
    # development machine), and one non-ASCII character in a log line then
    # raises UnicodeEncodeError from inside the handler and takes the whole job
    # down. Encoding stays whatever the terminal declared; only the error
    # policy changes, so CI's UTF-8 output is untouched.
    reconfigure = getattr(getattr(handler, "stream", None), "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="backslashreplace")
    logging.basicConfig(handlers=[handler], level=getattr(logging, level.upper(), logging.INFO))

    # httpx logs every request at INFO including the full URL, and Congress.gov
    # carries `api_key` in the query string — that would print a live
    # credential into CI logs on every call. Our own logging redacts; httpx's
    # does not, so it is silenced below WARNING.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for a collector or loader module."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
