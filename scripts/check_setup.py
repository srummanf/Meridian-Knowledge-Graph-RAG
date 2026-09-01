"""Phase 0 gate check.

Verifies both databases are reachable and both LLM providers + local embeddings
work. Run after ``docker-compose up`` and filling in ``.env``:

    python scripts/check_setup.py
"""

from __future__ import annotations

import sys

from src.config import EMBED_DIM, build_chat_model, embeddings, settings
from src.logging_config import configure_logging, get_logger

configure_logging(settings.log_level)
log = get_logger("check_setup")


def check_neo4j() -> bool:
    from neo4j import GraphDatabase

    try:
        with GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password)
        ) as driver:
            driver.verify_connectivity()
            with driver.session() as session:
                assert session.run("RETURN 1 AS ok").single()["ok"] == 1
        return True
    except Exception as exc:  # noqa: BLE001 - report and continue
        log.error("neo4j: %s", exc)
        return False


def check_postgres() -> bool:
    import psycopg

    try:
        with psycopg.connect(settings.psycopg_dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT extname FROM pg_available_extensions WHERE name = 'vector'")
                if cur.fetchone() is None:
                    log.error("postgres: 'vector' extension not available in this image")
                    return False
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("postgres: %s", exc)
        return False


def check_embeddings() -> bool:
    try:
        vec = embeddings().embed_query("meridian knowledge graph")
        if len(vec) != EMBED_DIM:
            log.error("embeddings: expected dim %d, got %d", EMBED_DIM, len(vec))
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("embeddings: %s", exc)
        return False


def check_provider(provider: str) -> bool:
    try:
        model = build_chat_model(provider, router=True)
        reply = model.invoke("Reply with exactly one word: pong")
        text = getattr(reply, "content", str(reply)).strip()
        log.info("%s -> %r", provider, text[:60])
        return bool(text)
    except Exception as exc:  # noqa: BLE001
        log.error("%s: %s", provider, exc)
        return False


def main() -> int:
    checks = {
        "neo4j reachable": check_neo4j(),
        "postgres reachable + pgvector available": check_postgres(),
        f"embeddings (bge-small, {EMBED_DIM}d)": check_embeddings(),
        "groq responds": check_provider("groq"),
        "google (gemini) responds": check_provider("google"),
    }

    print()
    for name, ok in checks.items():
        print(f"  [{'OK  ' if ok else 'FAIL'}] {name}")

    passed = all(checks.values())
    print(f"\nPhase 0 gate: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
