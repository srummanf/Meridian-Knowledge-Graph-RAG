"""FastAPI app: ``POST /query`` and ``GET /health`` (architecture.md §5).

``/query`` invokes the compiled LangGraph answer pipeline
(``src.pipeline.graph.answer_question``) and shapes its result:

- normal answer            -> 200 :class:`GroundedAnswer`
- router returned REFUSE    -> 422 ``{error: out_of_scope, reason, message}``
- empty / oversized input   -> 400
- Neo4j or Postgres down    -> 503  (via the ``require_datastores`` dependency)

The app owns no provider clients — everything goes through ``src.config`` and the
pipeline singletons.
"""

from __future__ import annotations

import time

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.dependencies import datastore_status, require_datastores
from src.api.schemas import ErrorBody, HealthResponse, OutOfScope, QueryRequest
from src.logging_config import configure_logging, get_logger
from src.models.answer import GroundedAnswer
from src.pipeline.graph import answer_question
from src.utils.errors import ApplicationError, GraphUnavailableError, LLMUnavailableError

configure_logging()
log = get_logger("api")

app = FastAPI(title="Meridian Knowledge Graph RAG", version="0.4.0")

_REFUSAL_MESSAGE = (
    "I answer questions about Meridian's architecture and ownership, not "
    "opinions, recommendations, forecasts, or costs."
)


@app.exception_handler(RequestValidationError)
async def _bad_input(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Malformed / empty / oversized body -> 400 (architecture.md §5)."""
    detail = "; ".join(f"{'.'.join(map(str, e['loc'][1:]))}: {e['msg']}" for e in exc.errors())
    return JSONResponse(
        status_code=400, content={"error": "bad_request", "message": detail or "invalid request body"}
    )


@app.exception_handler(ApplicationError)
async def _application_error(_request, exc: ApplicationError) -> JSONResponse:
    downstream = isinstance(exc, (GraphUnavailableError, LLMUnavailableError))
    status = 503 if downstream else 500
    return JSONResponse(
        status_code=status,
        content={"error": "unavailable" if downstream else "internal", "message": str(exc)},
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness + datastore reachability. 200 even if a store is down (body says so)."""
    status = datastore_status()
    overall = "ok" if all(v == "ok" for v in status.values()) else "degraded"
    return HealthResponse(status=overall, neo4j=status["neo4j"], postgres=status["postgres"])


@app.post(
    "/query",
    response_model=GroundedAnswer,
    responses={400: {"model": ErrorBody}, 422: {"model": OutOfScope}, 503: {"model": ErrorBody}},
    dependencies=[Depends(require_datastores)],
)
def query(request: QueryRequest):
    """Answer one question with validated citations."""
    question = request.question.strip()
    if not question:
        return JSONResponse(
            status_code=400,
            content=ErrorBody(error="bad_request", message="question must not be blank").model_dump(),
        )

    started = time.perf_counter()
    state = answer_question(question)
    elapsed_ms = (time.perf_counter() - started) * 1000

    if state.get("route_used") == "REFUSE":
        decision = state.get("decision")
        reason = decision.reasoning if decision else "out of scope"
        log.info("query refused: %r (%s)", question, reason)
        return JSONResponse(
            status_code=422,
            content=OutOfScope(reason=reason, message=_REFUSAL_MESSAGE).model_dump(),
        )

    answer: GroundedAnswer = state["answer"]
    answer = answer.model_copy(update={"latency_ms": elapsed_ms})
    log.info(
        "query ok: %r -> %s, %d citations, %.0fms",
        question,
        answer.routing_used,
        len(answer.citations),
        elapsed_ms,
    )
    return answer
