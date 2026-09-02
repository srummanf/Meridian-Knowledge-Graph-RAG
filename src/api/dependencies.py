"""Datastore health checks, shared by ``GET /health`` and ``POST /query``.

``POST /query`` depends on ``require_datastores`` so a DB outage surfaces as a
clean 503 instead of a stack trace mid-pipeline (rules.md §1).
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from src.config import settings
from src.graph.client import graph_client
from src.logging_config import get_logger
from src.utils.errors import GraphUnavailableError

log = get_logger("api.deps")


def _check_neo4j() -> None:
    graph_client().query("RETURN 1 AS ok")


def _check_postgres() -> None:
    engine = create_engine(settings.postgres_dsn)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def datastore_status() -> dict[str, str]:
    """``{"neo4j": "ok"|"down: ...", "postgres": ...}`` — never raises."""
    status: dict[str, str] = {}
    for name, check in (("neo4j", _check_neo4j), ("postgres", _check_postgres)):
        try:
            check()
            status[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - report, don't propagate
            log.warning("%s health check failed: %s", name, exc)
            status[name] = f"down: {exc}"
    return status


def require_datastores() -> None:
    """FastAPI dependency: raise :class:`GraphUnavailableError` if a DB is down."""
    status = datastore_status()
    down = {k: v for k, v in status.items() if v != "ok"}
    if down:
        raise GraphUnavailableError(f"datastore(s) unavailable: {down}")
