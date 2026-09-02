"""Classify a question into VECTOR / GRAPH / HYBRID / REFUSE (architecture.md §6).

Hand-written (rules.md §5.1): one small structured-output call with a few-shot
prompt, then the ``confidence < HYBRID_CONFIDENCE_FLOOR -> HYBRID`` downgrade.
Every decision is logged — Phase 5 reads that log.

Route meanings:

- **VECTOR** — the answer is a single fact stated in one place: a definition,
  "what is X", "what does X do", a property of one entity.
- **GRAPH** — the answer needs following relationships: "which Xs do Y",
  multi-hop chains ("if X breaks, what is affected"), multi-constraint filters,
  or counting / aggregation over relationships.
- **HYBRID** — needs both a definitional passage *and* a relationship traversal.
  Also produced by the confidence floor: an uncertain classification does both
  rather than gambling on one.
- **REFUSE** — opinion, recommendation, a comparison the corpus does not make, a
  prediction, or anything outside an architecture / ownership wiki.

The few-shot examples are lifted from ``data/benchmark/questions.md`` (B01, B02,
B04, B09, B17, B18, B25, B28, B29, B30) plus two written here; the labelled eval
set in ``tests/fixtures/routing_eval.json`` deliberately uses *different*
questions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import router_model
from src.logging_config import get_logger
from src.models.routing import HYBRID_CONFIDENCE_FLOOR, RoutingDecision

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable

log = get_logger("router")

_SYSTEM_PROMPT = """\
You route a question about Meridian's internal architecture wiki (a fictional
fintech: payments + merchant analytics) to the retrieval strategy that answers
it best. Return a RoutingDecision.

Routes:
- VECTOR: the answer sits in ONE document. Definitions ("what is X"), "what does
  X do", a property of one entity, AND "what is X and how/where is it used" when
  that entity's own doc states both the definition and its usage — a short list
  read from one page is still VECTOR, not a traversal.
- GRAPH: the answer requires combining facts ACROSS documents — "which Xs <verb>
  Y" (scan every X), multi-hop chains ("if X is exploited, which products are
  affected"), multi-constraint filters ("handles PCI data AND runs on EKS"), or
  counting / "how many" / "which has the most".
- HYBRID: genuinely needs a definitional passage AND a cross-document traversal.
  Rare — prefer VECTOR or GRAPH unless both are clearly required.
- REFUSE: opinion or recommendation ("should we...", "is X better than Y"), a
  comparison the wiki does not make, a prediction ("next year", "will it scale"),
  or a topic outside an architecture/ownership wiki — cost, budget, spend,
  pricing, headcount, roadmap, timelines.

confidence: your certainty in the route, 0-1. Use < 0.70 only when the question
is genuinely ambiguous between routes.
entities_detected: the Meridian entities named in the question.
reasoning: one sentence.

Examples:
Q: What is the Auth Service?
{"route":"VECTOR","confidence":0.97,"reasoning":"Definitional; one passage in the auth-service doc.","entities_detected":["Auth Service"]}
Q: What is Kafka used for at Meridian?
{"route":"VECTOR","confidence":0.95,"reasoning":"Single usage fact from the Kafka doc.","entities_detected":["Kafka"]}
Q: What does CVE-2021-44228 (Log4Shell) do?
{"route":"VECTOR","confidence":0.96,"reasoning":"Definition of one vulnerability.","entities_detected":["CVE-2021-44228"]}
Q: What is JWT and how does Meridian use it?
{"route":"VECTOR","confidence":0.93,"reasoning":"The jwt doc states both the definition and Meridian's usage; no cross-document traversal.","entities_detected":["JWT"]}
Q: Which services use PostgreSQL?
{"route":"GRAPH","confidence":0.96,"reasoning":"Every Service with a USES edge to PostgreSQL.","entities_detected":["PostgreSQL"]}
Q: If Log4Shell is exploited, which Meridian products are affected?
{"route":"GRAPH","confidence":0.94,"reasoning":"Multi-hop: CVE -> library -> service -> product.","entities_detected":["CVE-2021-44228"]}
Q: Which teams own a service that consumes an API owned by the Payments Team?
{"route":"GRAPH","confidence":0.93,"reasoning":"Traversal across OWNED_BY and CONSUMES edges.","entities_detected":["Payments Team"]}
Q: How many services are deployed on AWS EKS?
{"route":"GRAPH","confidence":0.95,"reasoning":"Aggregation over DEPLOYED_ON edges.","entities_detected":["AWS EKS"]}
Q: Is PostgreSQL better than MySQL for Meridian?
{"route":"REFUSE","confidence":0.9,"reasoning":"Comparative opinion the corpus does not make.","entities_detected":["PostgreSQL"]}
Q: Should the Payments Team rewrite the Ledger Service in Go?
{"route":"REFUSE","confidence":0.92,"reasoning":"Recommendation with no basis in the wiki.","entities_detected":["Payments Team","Ledger Service"]}
Q: What will Meridian's transaction volume be next year?
{"route":"REFUSE","confidence":0.95,"reasoning":"A business forecast, not architecture.","entities_detected":[]}
Q: How much does Meridian spend on AWS each month?
{"route":"REFUSE","confidence":0.94,"reasoning":"A cost figure; the wiki documents architecture and ownership, not finances.","entities_detected":["AWS"]}
"""


def _apply_confidence_floor(decision: RoutingDecision) -> RoutingDecision:
    """rules.md §5.1: an uncertain route becomes HYBRID (run both, decide later)."""
    if decision.route != "HYBRID" and decision.confidence < HYBRID_CONFIDENCE_FLOOR:
        return decision.model_copy(update={"route": "HYBRID"})
    return decision


def route_question(
    question: str, *, model: Runnable | None = None
) -> RoutingDecision:
    """Classify one question. Returns the (possibly floor-adjusted) decision."""
    llm = model if model is not None else router_model(RoutingDecision)
    raw: RoutingDecision = llm.invoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=question)]
    )
    decision = _apply_confidence_floor(raw)

    floored = "" if decision.route == raw.route else f" (floored from {raw.route})"
    log.info(
        "route %r -> %s conf=%.2f%s", question, decision.route, raw.confidence, floored
    )
    return decision
