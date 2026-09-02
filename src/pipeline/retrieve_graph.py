"""Graph retrieval: question -> resolved node ids -> Cypher template -> sentences.

The hand-written centrepiece (architecture.md §6, rules.md §5.2, §5.5). Exactly
**one** LLM call per question — a structured-output call that fills a
:class:`GraphQueryPlan` (which entities the question anchors on, what edge, which
direction, what shape). Everything after that is deterministic:

1. resolve each anchor mention to a node id (canonical name / alias / fuzzy);
2. pick the read template for ``plan.intent`` from ``src.graph.queries``;
3. run it via ``Neo4jGraph.query`` with named parameters — the model never sees
   or writes Cypher (no ``GraphCypherQAChain``);
4. turn each result row into a sentence with a per-relationship-type phrase.

An unresolved anchor or an empty result is not an error — it returns an empty
:class:`GraphRetrieval`, and the pipeline falls back to vector search.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.config import router_model
from src.graph.client import graph_client
from src.graph.queries import (
    BLAST_RADIUS,
    COUNT_NEIGHBORS,
    NEIGHBORS,
    PATH_BETWEEN,
    RESOLVE_ENTITY,
    RESOLVE_ENTITY_FUZZY,
    TWO_CONSTRAINT,
)
from src.logging_config import get_logger
from src.models.answer import GraphFact
from src.models.domain import DataConcern, EntityType, RelationType, slugify

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable
    from langchain_neo4j import Neo4jGraph

log = get_logger("retrieve_graph")

Intent = Literal[
    "neighbors", "count", "two_constraint", "path", "blast_radius", "lookup"
]
Direction = Literal["from_anchor", "to_anchor", "either"]

_CONCERNS: tuple[str, ...] = DataConcern.__args__  # type: ignore[attr-defined]

# rules.md §5.5: an edge becomes a sentence. "{source} <verb> {target}."
_REL_VERB: dict[str, str] = {
    "PART_OF": "is part of",
    "DEPENDS_ON": "depends on",
    "USES": "uses",
    "EXPOSES": "exposes",
    "CONSUMES": "consumes",
    "COMMUNICATES_VIA": "communicates via",
    "SECURED_BY": "is secured by",
    "DEPLOYED_ON": "is deployed on",
    "OWNED_BY": "is owned by",
    "HANDLES": "handles",
    "AFFECTS": "affects",
    "ALTERNATIVE_TO": "is an alternative to",
}

# Plural / base form for a "N services <verb> X" count sentence.
_REL_VERB_PLURAL: dict[str, str] = {
    "PART_OF": "are part of",
    "DEPENDS_ON": "depend on",
    "USES": "use",
    "EXPOSES": "expose",
    "CONSUMES": "consume",
    "COMMUNICATES_VIA": "communicate via",
    "SECURED_BY": "are secured by",
    "DEPLOYED_ON": "are deployed on",
    "OWNED_BY": "are owned by",
    "HANDLES": "handle",
    "AFFECTS": "affect",
    "ALTERNATIVE_TO": "are alternatives to",
}


def _verb(rel: str) -> str:
    return _REL_VERB.get(rel, rel.lower().replace("_", " "))


def _sentence(rel: str, source: str, target: str) -> str:
    return f"{source} {_verb(rel)} {target}."


class GraphQueryPlan(BaseModel):
    """The LLM's read of a question — enough to choose and parameterise a query."""

    intent: Intent
    anchors: list[str] = Field(
        min_length=1,
        description="Entity names the question is about, e.g. ['PostgreSQL'].",
    )
    relationship: RelationType | None = Field(
        default=None, description="The edge type in play, if the question implies one."
    )
    direction: Direction = Field(
        default="either",
        description=(
            "'to_anchor' for 'which X <rel> ANCHOR', 'from_anchor' for "
            "'what does ANCHOR <rel>', else 'either'."
        ),
    )
    neighbor_type: EntityType | None = Field(
        default=None, description="Restrict results to this entity type if stated."
    )
    second_anchor: str | None = Field(
        default=None, description="Second entity, for 'path' and 'two_constraint'."
    )
    second_relationship: RelationType | None = Field(
        default=None, description="The second edge type, for 'two_constraint'."
    )


class GraphRetrieval(BaseModel):
    """What graph retrieval hands to the merge / synthesis steps."""

    facts: list[GraphFact] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    node_names: list[str] = Field(default_factory=list)
    plan: GraphQueryPlan | None = None
    template: str = ""
    resolved_anchors: dict[str, str] = Field(default_factory=dict)
    query_ms: float = 0.0  # Cypher execution only (excludes the plan LLM call)


_SYSTEM_PROMPT = """\
You read a question about Meridian's architecture graph and describe how to query
it. Return a GraphQueryPlan. You do NOT write Cypher.

Node types: Product, Service, API, Library, Language, Database, CloudService,
Protocol, SecurityMechanism, Team, Vulnerability. Edge types and direction
(A->B): service PART_OF product; service DEPENDS_ON library; service USES
database/cloudservice; service EXPOSES api; service CONSUMES api (owned by
another service); api COMMUNICATES_VIA protocol; api/service SECURED_BY
mechanism; service/database DEPLOYED_ON cloudservice; service/product/api
OWNED_BY team; service HANDLES a data concern ("PII", "PCI cardholder data",
"financial records", ...); vulnerability AFFECTS library/database.

intent:
- neighbors: "which X <rel> Y" or "what does Y <rel>". Set relationship and
  direction: 'to_anchor' if the anchor is the target ("which services USE
  PostgreSQL"), 'from_anchor' if the anchor is the source ("what does the Billing
  Service DEPEND ON").
- count: like neighbors, but the question asks "how many".
- two_constraint: "X that <rel1> A AND <rel2> B" — A in anchors, B in
  second_anchor, both relationship and second_relationship set.
- path: "how does A relate to B" / "through which chain" — A in anchors, B in
  second_anchor.
- blast_radius: "if <vulnerability> is exploited, what is affected" — the CVE in
  anchors.
- lookup: "what is X", answered from the graph — just anchors.

anchors: the entity names exactly as written; the resolver handles casing and
aliases.

Examples:
Q: Which services use PostgreSQL?
{"intent":"neighbors","anchors":["PostgreSQL"],"relationship":"USES","direction":"to_anchor","neighbor_type":"Service","second_anchor":null,"second_relationship":null}
Q: What does the Billing Service depend on?
{"intent":"neighbors","anchors":["Billing Service"],"relationship":"DEPENDS_ON","direction":"from_anchor","neighbor_type":null,"second_anchor":null,"second_relationship":null}
Q: Which services consume the Ledger API?
{"intent":"neighbors","anchors":["Ledger API"],"relationship":"CONSUMES","direction":"to_anchor","neighbor_type":"Service","second_anchor":null,"second_relationship":null}
Q: What is the Payments Platform made of?
{"intent":"neighbors","anchors":["Payments Platform"],"relationship":"PART_OF","direction":"to_anchor","neighbor_type":null,"second_anchor":null,"second_relationship":null}
Q: How many services are deployed on AWS EKS?
{"intent":"count","anchors":["AWS EKS"],"relationship":"DEPLOYED_ON","direction":"to_anchor","neighbor_type":"Service","second_anchor":null,"second_relationship":null}
Q: Which services both handle PCI cardholder data and are deployed on AWS EKS?
{"intent":"two_constraint","anchors":["PCI cardholder data"],"relationship":"HANDLES","direction":"either","neighbor_type":"Service","second_anchor":"AWS EKS","second_relationship":"DEPLOYED_ON"}
Q: If Log4Shell is exploited, which Meridian products are affected?
{"intent":"blast_radius","anchors":["CVE-2021-44228"],"relationship":null,"direction":"either","neighbor_type":null,"second_anchor":null,"second_relationship":null}
Q: Through which chain does the Analytics Suite get ledger data?
{"intent":"path","anchors":["Analytics Suite"],"relationship":null,"direction":"either","neighbor_type":null,"second_anchor":"Ledger Service","second_relationship":null}
"""


def _plan_query(question: str, model: Runnable | None) -> GraphQueryPlan:
    llm = model if model is not None else router_model(GraphQueryPlan)
    return llm.invoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=question)]
    )


def _concern_id(name: str) -> str | None:
    for concern in _CONCERNS:
        if concern.lower() == name.strip().lower():
            return f"concern:{slugify(concern)}"
    return None


def resolve_mention(name: str, client: Neo4jGraph) -> str | None:
    """A question's entity mention -> a node id. ``None`` if nothing matches."""
    concern = _concern_id(name)
    if concern is not None:
        return concern
    for template in (RESOLVE_ENTITY, RESOLVE_ENTITY_FUZZY):
        rows = client.query(template, {"name": name})
        if rows:
            return rows[0]["id"]
    return None


def _fact(text: str, row: dict) -> GraphFact:
    return GraphFact(
        text=text,
        source_chunk_id=row.get("source_chunk_id") or "",
        evidence=row.get("evidence") or "",
    )


Node = tuple[str, str]  # (id, name)


def _dedupe_facts(facts: list[GraphFact]) -> list[GraphFact]:
    """Same edge from several chunks -> one sentence (first chunk keeps the cite)."""
    seen: dict[str, GraphFact] = {}
    for fact in facts:
        seen.setdefault(fact.text, fact)
    return list(seen.values())


def _neighbor_facts(rows: list[dict]) -> tuple[list[GraphFact], list[Node]]:
    facts, nodes = [], []
    for row in rows:
        if row["direction"] == "from_anchor":
            text = _sentence(row["rel"], row["anchor_name"], row["name"])
        else:
            text = _sentence(row["rel"], row["name"], row["anchor_name"])
        facts.append(_fact(text, row))
        if row.get("id"):
            nodes.append((row["id"], row["name"]))
    return _dedupe_facts(facts), nodes


def _two_constraint_facts(rows: list[dict]) -> tuple[list[GraphFact], list[Node]]:
    facts, nodes = [], []
    for row in rows:
        text = (
            f"{row['name']} {_verb(row['rel1'])} {row['anchor1']} "
            f"and {_verb(row['rel2'])} {row['anchor2']}."
        )
        facts.append(_fact(text, row))
        nodes.append((row["id"], row["name"]))
    return _dedupe_facts(facts), nodes


def _path_facts(rows: list[dict]) -> tuple[list[GraphFact], list[Node]]:
    facts = [
        _fact(_sentence(row["rel"], row["source"], row["target"]), row) for row in rows
    ]
    return _dedupe_facts(facts), []


def _blast_radius_facts(rows: list[dict]) -> tuple[list[GraphFact], list[Node]]:
    facts: list[GraphFact] = []
    names: list[str] = []
    for row in rows:
        lib = row["affected_library"]
        versions = (
            f" (versions {row['affected_versions']})"
            if row.get("affected_versions")
            else ""
        )
        facts.append(_fact(f"The vulnerability affects {lib}{versions}.", row))
        for svc in filter(None, row.get("services", [])):
            facts.append(_fact(f"{svc} depends on {lib}.", row))
            names.append(svc)
        for prod in filter(None, row.get("products", [])):
            facts.append(
                _fact(f"{prod} contains a service exposed to this vulnerability.", row)
            )
            names.append(prod)
    return _dedupe_facts(facts), [("", name) for name in names]


def _count_sentence(
    n: int, plan: GraphQueryPlan, anchor: str, members: list[GraphFact]
) -> GraphFact:
    subject = f"{plan.neighbor_type.lower()}s" if plan.neighbor_type else "entities"
    verb = (
        _REL_VERB_PLURAL.get(plan.relationship, "relate to")
        if plan.relationship
        else "relate to"
    )
    # The tally is derived from the member edges — cite the first one so the
    # claim is grounded in a real chunk (synthesis needs every claim citable).
    cite = members[0] if members else GraphFact(text="x")
    return GraphFact(
        text=f"{n} {subject} {verb} {anchor}.",
        source_chunk_id=cite.source_chunk_id,
        evidence=cite.evidence,
    )


def retrieve_graph(
    question: str,
    *,
    model: Runnable | None = None,
    client: Neo4jGraph | None = None,
) -> GraphRetrieval:
    """Answer ``question`` from the graph. Empty result on any miss (not an error)."""
    client = client or graph_client()
    try:
        plan = _plan_query(question, model)
    except Exception as exc:  # noqa: BLE001 - a flaky plan call must not break the pipeline
        log.warning("route graph: %r — plan call failed (%s); vector fallback", question, exc)
        return GraphRetrieval()

    started = time.perf_counter()  # time the Cypher, not the plan LLM call
    mentions = list(plan.anchors)
    if plan.second_anchor:
        mentions.append(plan.second_anchor)
    resolved = {name: resolve_mention(name, client) for name in mentions}
    resolved_anchors = {k: (v or "") for k, v in resolved.items()}

    anchor_id = resolved.get(plan.anchors[0])
    if anchor_id is None:
        log.info(
            "route graph: %r — anchor %r did not resolve", question, plan.anchors[0]
        )
        return GraphRetrieval(plan=plan, resolved_anchors=resolved_anchors)

    second_id = resolved.get(plan.second_anchor) if plan.second_anchor else None
    params = {
        "anchor_id": anchor_id,
        "rel": plan.relationship,
        "direction": plan.direction,
        "neighbor_type": plan.neighbor_type,
        "second_rel": plan.second_relationship,
        "second_anchor_id": second_id,
    }

    if plan.intent == "count":
        # list the members (NEIGHBORS) and lead with the tally.
        member_facts, nodes = _neighbor_facts(client.query(NEIGHBORS, params))
        total = client.query(COUNT_NEIGHBORS, params)[0]["count"]
        facts = [
            _count_sentence(total, plan, plan.anchors[0], member_facts),
            *member_facts,
        ]
        template = "count"
    elif plan.intent == "two_constraint" and second_id:
        facts, nodes = _two_constraint_facts(client.query(TWO_CONSTRAINT, params))
        template = "two_constraint"
    elif plan.intent == "path" and second_id:
        facts, nodes = _path_facts(client.query(PATH_BETWEEN, params))
        template = "path"
    elif plan.intent == "blast_radius":
        facts, nodes = _blast_radius_facts(client.query(BLAST_RADIUS, params))
        template = "blast_radius"
    else:  # neighbors / lookup
        if plan.intent == "lookup":
            params["rel"] = params["direction"] = params["neighbor_type"] = None
        facts, nodes = _neighbor_facts(client.query(NEIGHBORS, params))
        template = plan.intent

    seen_ids, ids, names = set(), [], []
    for node_id, name in nodes:
        key = node_id or name
        if key not in seen_ids:
            seen_ids.add(key)
            ids.append(node_id)
            names.append(name)

    query_ms = (time.perf_counter() - started) * 1000
    log.info(
        "route graph: %r -> %s (%d facts, %d nodes, %.1fms) anchor=%s",
        question,
        template,
        len(facts),
        len(names),
        query_ms,
        anchor_id,
    )
    return GraphRetrieval(
        facts=facts,
        node_ids=[i for i in ids if i],
        node_names=names,
        plan=plan,
        template=template,
        resolved_anchors=resolved_anchors,
        query_ms=query_ms,
    )
