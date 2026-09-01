"""One exception hierarchy for the whole app.

``src/api`` maps these to HTTP codes in one place (rules.md §1). Anything the
pipeline raises on its own should inherit :class:`ApplicationError`.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for every error this project raises deliberately."""


class ExtractionError(ApplicationError):
    """A chunk could not be extracted into a valid ``ExtractionResult``.

    Raised after the retry budget is exhausted. ``errors`` holds the validation
    messages from the final attempt.
    """

    def __init__(self, chunk_id: str, errors: list[str]) -> None:
        self.chunk_id = chunk_id
        self.errors = list(errors)
        joined = "; ".join(self.errors) or "unknown error"
        super().__init__(f"extraction failed for {chunk_id!r} after retries: {joined}")


class LLMUnavailableError(ApplicationError):
    """Both LLM providers failed. ``/query`` -> 503, ingestion aborts."""


class GraphUnavailableError(ApplicationError):
    """Neo4j is unreachable. ``/query`` -> 503."""


class RetrievalError(ApplicationError):
    """A retriever failed in a way the pipeline cannot fall back from."""
