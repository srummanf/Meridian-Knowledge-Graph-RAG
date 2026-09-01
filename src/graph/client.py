"""Neo4j connection (via LangChain's ``Neo4jGraph``) plus schema setup.

``Neo4jGraph`` owns the driver and the ``.query(cypher, params)`` call; this
module just constructs it from settings and applies the constraints/indexes in
:data:`~src.graph.queries.SCHEMA_STATEMENTS`.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from src.config import settings
from src.graph.queries import SCHEMA_STATEMENTS, WIPE
from src.logging_config import get_logger

if TYPE_CHECKING:
    from langchain_neo4j import Neo4jGraph

log = get_logger("graph")


@functools.lru_cache(maxsize=1)
def graph_client() -> Neo4jGraph:
    """The shared :class:`Neo4jGraph`. Cached — one driver per process."""
    from langchain_neo4j import Neo4jGraph

    return Neo4jGraph(
        url=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password,
        refresh_schema=False,
    )


def ensure_schema(client: Neo4jGraph | None = None) -> None:
    """Create the id constraints and lookup indexes (idempotent)."""
    client = client or graph_client()
    for statement in SCHEMA_STATEMENTS:
        client.query(statement)
    log.info("neo4j schema ensured (%d statements)", len(SCHEMA_STATEMENTS))


def wipe(client: Neo4jGraph | None = None) -> None:
    """Delete every node and relationship. For a clean rebuild or tests."""
    client = client or graph_client()
    client.query(WIPE)
    log.warning("neo4j wiped (all nodes + relationships deleted)")
