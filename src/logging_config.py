"""Console logging setup. Call ``configure_logging()`` once at process start."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False

# Third-party loggers that are noisy at INFO.
_QUIET = ("httpx", "httpcore", "neo4j", "urllib3", "sentence_transformers", "transformers")


def configure_logging(level: str = "INFO") -> None:
    """Attach a single stdout handler to the root logger (idempotent).

    Args:
        level: Root log level name, e.g. ``"INFO"`` or ``"DEBUG"``.
    """
    global _CONFIGURED
    if _CONFIGURED:
        logging.getLogger().setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configuring logging on first use."""
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)
