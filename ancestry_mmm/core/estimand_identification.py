"""Estimand-specific graphical identification (REQ-IDENT-001, Work
Package 3 of `Media-Mix-Lab: Coding LLM Next Steps After PR #267 and
Latest PRD Validation Updates`).

Upstream reference (root `AGENTS.md`'s required upstream-reference
workflow): `networkx` (Context7 `/networkx/networkx`; current stable is
3.6.1 per PyPI, pinned here `>=3.5,<4.0`) provides `is_d_separator`,
`is_minimal_d_separator`, and `find_minimal_d_separator`
(`networkx.algorithms.d_separation`) - the exact graph-theoretic
primitive Pearl's back-door criterion is built from. NetworkX 3.5 removed
the older `d_separated`/`minimum_d_separator` names in favour of these;
this module targets `>=3.5` and uses only the current names. No
Ancestry-specific d-separation algorithm is written by hand here - this
module composes networkx's own vetted implementation, applied to the
standard "remove the treatment's outgoing edges" transformation Pearl's
back-door criterion requires.

`core.causal_graph.validate_causal_graph` (REQ-GRAPH-001) already checks
graph *structure* - bad controls, cycles, roles, prohibited directions.
`core.identification_diagnostics` checks *fitted-model* evidence -
posterior correlation, condition number, coefficient stability. Neither
performs backdoor-path analysis or proposes/validates an adjustment set
for a specific requested estimand against the approved graph. This module
is a third, additional diagnostic layer - it does not replace either of
the other two.

A result from this module is evidence under the assumed graph, never
proof that the graph is true, that no unobserved confounding exists,
that the functional form is valid, or that the effect is empirically
well identified (REQ-IDENT-001 requirement 1's mandated disclaimer).
`EstimandIdentificationResult` deliberately never exposes a bare boolean
"identified" field - only the qualified status vocabulary below plus this
module's own `GRAPHICAL_IDENTIFICATION_DISCLAIMER` string, so a caller
cannot collapse the result into an unqualified pass/fail without also
carrying the disclaimer.

Scope: this module implements Pearl's back-door criterion for an
adjustment-based **total-effect** estimand only (`effect_type="total"`).
A direct or natural-direct effect requires a different identification
criterion (front-door/single-door-style reasoning about mediators) that
this module does not implement - requesting `effect_type="direct"`
returns `IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER` rather
than silently applying the wrong criterion. Likewise, a structural or
linked-model estimand (e.g. Candidate A's capacity-constrained pathway)
is identified through its own structural equations and identifying
constraints, not through this module's adjustment-set check - REQ-
IDENT-001 requirement 4 explicitly separates the two identification
paths.

Deliberately out of scope (see REQ-IDENT-001's own "Explicitly
excluded"/"Unresolved decisions"):

- Which graphical-identification statuses are required versus optional
  for a given use, and the accepted identification strategies for
  structural/linked estimands (Part 7 §48 `VL-026`) - a separate,
  decision-required policy.
- Business/technical labels shown to an analyst (Part 10 §47 `UX-028`).
- Determining whether a required confounder is *available as data* -
  `core.causal_graph.CausalNode` has no "observability" field, so this
  module cannot determine whether a graph node corresponds to an
  observed variable. Every result explicitly records this as a
  limitation rather than silently assuming every node is measured.
- Wiring this evidence into `DiagnosticsArtefact`/the Diagnostics page -
  deferred alongside Work Package 2's same open item, pending a decision
  on how estimand-specific identification results should be persisted
  and displayed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

import networkx as nx

from .causal_graph import CausalGraph, EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY

IDENTIFICATION_STATUS_GRAPH_COMPATIBLE = "graph_compatible"
IDENTIFICATION_STATUS_REVIEW_REQUIRED = "review_required"
IDENTIFICATION_STATUS_NOT_IDENTIFIED_UNDER_GRAPH = "not_identified_under_graph"
IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER = "unsupported_by_current_checker"
IDENTIFICATION_STATUS_NOT_APPLICABLE = "not_applicable"

IDENTIFICATION_STATUSES = (
    IDENTIFICATION_STATUS_GRAPH_COMPATIBLE,
    IDENTIFICATION_STATUS_REVIEW_REQUIRED,
    IDENTIFICATION_STATUS_NOT_IDENTIFIED_UNDER_GRAPH,
    IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER,
    IDENTIFICATION_STATUS_NOT_APPLICABLE,
)

EFFECT_TYPE_TOTAL = "total"
EFFECT_TYPE_DIRECT = "direct"
EFFECT_TYPES = (EFFECT_TYPE_TOTAL, EFFECT_TYPE_DIRECT)

GRAPHICAL_IDENTIFICATION_DISCLAIMER = (
    "This diagnostic validates the requested adjustment logic under the "
    "approved graph. It does not prove that the graph is correct, that no "
    "unobserved confounding exists, that the functional form is valid, or "
    "that the effect is empirically well identified. It also cannot "
    "determine whether a required confounder is actually available as "
    "observed data."
)


def _build_digraph(graph: CausalGraph) -> "nx.DiGraph":
    """Build a plain `networkx.DiGraph` from the approved `CausalGraph` -
    every node, and every edge except `excluded_diagnostic_only` (which
    "compiles to nothing" per REQ-GRAPH-001 and represents no genuine
    causal relationship). This is the only place this module constructs a
    graph; every function below receives the same `nx.DiGraph`, so the
    causal structure used for identification can never silently diverge
    from the approved `CausalGraph` it was built from."""
    g = nx.DiGraph()
    for node in graph.nodes:
        g.add_node(node.node_id)
    for edge in graph.edges:
        if edge.role == EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY:
            continue
        g.add_edge(edge.source_node_id, edge.target_node_id)
    return g


@dataclass(frozen=True)
class EstimandIdentificationResult:
    """The estimand-specific graphical-identification result for one
    requested (treatment, outcome, effect_type) under one approved
    `CausalGraph` version (REQ-IDENT-001 requirement 2).

    Every field is descriptive evidence; none is a proof of causal
    validity - see `GRAPHICAL_IDENTIFICATION_DISCLAIMER`, always present
    on `disclaimer` so a caller cannot access a result without it.
    """

    treatment: str
    outcome: str
    effect_type: str
    graph_id: str
    graph_version: int
    status: str
    proposed_adjustment_set: Tuple[str, ...]
    treatment_descendants_in_adjustment_set: Tuple[str, ...] = ()
    minimal_adjustment_set: Optional[Tuple[str, ...]] = None
    likely_collider_members: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()
    disclaimer: str = GRAPHICAL_IDENTIFICATION_DISCLAIMER

    def __post_init__(self) -> None:
        if not self.treatment or not self.outcome:
            raise ValueError("treatment and outcome are required")
        if self.effect_type not in EFFECT_TYPES:
            raise ValueError(
                f"invalid effect_type {self.effect_type!r}; must be one of {EFFECT_TYPES}"
            )
        if self.status not in IDENTIFICATION_STATUSES:
            raise ValueError(
                f"invalid status {self.status!r}; must be one of {IDENTIFICATION_STATUSES}"
            )

    def to_dict(self) -> dict:
        return {
            "treatment": self.treatment,
            "outcome": self.outcome,
            "effect_type": self.effect_type,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "status": self.status,
            "proposed_adjustment_set": list(self.proposed_adjustment_set),
            "treatment_descendants_in_adjustment_set": list(
                self.treatment_descendants_in_adjustment_set
            ),
            "minimal_adjustment_set": (
                list(self.minimal_adjustment_set)
                if self.minimal_adjustment_set is not None
                else None
            ),
            "likely_collider_members": list(self.likely_collider_members),
            "limitations": list(self.limitations),
            "disclaimer": self.disclaimer,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "EstimandIdentificationResult":
        minimal = values.get("minimal_adjustment_set")
        return cls(
            treatment=values["treatment"],
            outcome=values["outcome"],
            effect_type=values["effect_type"],
            graph_id=values["graph_id"],
            graph_version=values["graph_version"],
            status=values["status"],
            proposed_adjustment_set=tuple(values.get("proposed_adjustment_set") or ()),
            treatment_descendants_in_adjustment_set=tuple(
                values.get("treatment_descendants_in_adjustment_set") or ()
            ),
            minimal_adjustment_set=tuple(minimal) if minimal is not None else None,
            likely_collider_members=tuple(values.get("likely_collider_members") or ()),
            limitations=tuple(values.get("limitations") or ()),
            disclaimer=values.get("disclaimer", GRAPHICAL_IDENTIFICATION_DISCLAIMER),
        )


def assess_backdoor_identification(
    graph: CausalGraph,
    *,
    treatment: str,
    outcome: str,
    proposed_adjustment_set: Tuple[str, ...] = (),
    effect_type: str = EFFECT_TYPE_TOTAL,
) -> EstimandIdentificationResult:
    """Assess whether `proposed_adjustment_set` satisfies Pearl's back-door
    criterion for the total effect of `treatment` on `outcome` under the
    approved `graph` (REQ-IDENT-001).

    Method (composing `networkx.algorithms.d_separation`, never a
    hand-derived d-separation check):

    1. Build the "backdoor graph" - `graph` with every edge out of
       `treatment` removed, isolating paths *into* treatment from the
       causal paths *out of* it.
    2. `is_d_separator(backdoor_graph, {treatment}, {outcome}, proposed_
       adjustment_set)` - does the proposed set block every backdoor path?
    3. Separately, in the *original* graph, no proposed adjustment-set
       member may be a descendant of `treatment` (Pearl's second
       back-door condition) - checked via `networkx.descendants`.
    4. Where the proposed set fails either condition, `find_minimal_d_
       separator` (restricted to exclude treatment's descendants) offers
       a constructive alternative rather than a bare failure.
    5. For each member of the proposed set, check whether removing it
       alone would improve the d-separation result - a member whose
       removal helps is flagged as a likely collider or collider
       descendant opened by conditioning on it.
    """
    if effect_type != EFFECT_TYPE_TOTAL:
        return EstimandIdentificationResult(
            treatment=treatment,
            outcome=outcome,
            effect_type=effect_type,
            graph_id=graph.graph_id,
            graph_version=graph.graph_version,
            status=IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER,
            proposed_adjustment_set=tuple(proposed_adjustment_set),
            limitations=(
                "This checker implements Pearl's back-door criterion for a "
                "total-effect, adjustment-based estimand only. Direct/"
                "natural-direct effect identification requires a different "
                "criterion this module does not implement.",
            ),
        )

    g = _build_digraph(graph)
    if treatment not in g or outcome not in g:
        return EstimandIdentificationResult(
            treatment=treatment,
            outcome=outcome,
            effect_type=effect_type,
            graph_id=graph.graph_id,
            graph_version=graph.graph_version,
            status=IDENTIFICATION_STATUS_NOT_APPLICABLE,
            proposed_adjustment_set=tuple(proposed_adjustment_set),
            limitations=(
                f"treatment={treatment!r} and/or outcome={outcome!r} are not "
                "nodes in the approved causal graph.",
            ),
        )
    if not nx.is_directed_acyclic_graph(g):
        return EstimandIdentificationResult(
            treatment=treatment,
            outcome=outcome,
            effect_type=effect_type,
            graph_id=graph.graph_id,
            graph_version=graph.graph_version,
            status=IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER,
            proposed_adjustment_set=tuple(proposed_adjustment_set),
            limitations=(
                "The approved graph (excluding excluded_diagnostic_only "
                "edges) is not acyclic - d-separation analysis requires a "
                "DAG and cannot be performed. This should not occur for a "
                "graph that passed core.causal_graph.validate_causal_graph's "
                "own acyclicity check; report this as a data inconsistency.",
            ),
        )

    proposed = frozenset(proposed_adjustment_set)
    treatment_descendants = nx.descendants(g, treatment)
    descendants_in_set = tuple(sorted(proposed & treatment_descendants))

    backdoor_graph = g.copy()
    backdoor_graph.remove_edges_from(list(g.out_edges(treatment)))

    is_blocked = nx.is_d_separator(backdoor_graph, {treatment}, {outcome}, proposed)

    likely_colliders = []
    if proposed:
        for candidate in sorted(proposed):
            reduced = proposed - {candidate}
            reduced_blocks = nx.is_d_separator(
                backdoor_graph, {treatment}, {outcome}, reduced
            )
            if reduced_blocks and not is_blocked:
                likely_colliders.append(candidate)

    minimal_adjustment_set: Optional[Tuple[str, ...]] = None
    limitations = []
    if not is_blocked or descendants_in_set:
        restricted = set(g.nodes) - treatment_descendants - {treatment, outcome}
        try:
            minimal = nx.find_minimal_d_separator(
                backdoor_graph, {treatment}, {outcome}, restricted=restricted
            )
            minimal_adjustment_set = tuple(sorted(minimal))
        except nx.NetworkXError:
            minimal_adjustment_set = None
            limitations.append(
                "No adjustment set excluding treatment's descendants could "
                "separate treatment and outcome in the backdoor graph - an "
                "open backdoor path may be unblockable by conditioning "
                "alone under this graph."
            )

    limitations.append(
        "This checker cannot determine whether every node in the approved "
        "graph corresponds to an observed, measurable variable - an "
        "adjustment set that is graph-compatible may still be practically "
        "unavailable if a required confounder is unobserved."
    )

    if descendants_in_set:
        status = IDENTIFICATION_STATUS_NOT_IDENTIFIED_UNDER_GRAPH
    elif not is_blocked:
        status = IDENTIFICATION_STATUS_NOT_IDENTIFIED_UNDER_GRAPH
    elif likely_colliders:
        # Should not occur when is_blocked is True and no descendants are
        # present (a truly blocking set cannot simultaneously contain a
        # member whose removal is required for blocking) - kept as a
        # defensive review-required path rather than asserted impossible.
        status = IDENTIFICATION_STATUS_REVIEW_REQUIRED
    else:
        status = IDENTIFICATION_STATUS_GRAPH_COMPATIBLE

    return EstimandIdentificationResult(
        treatment=treatment,
        outcome=outcome,
        effect_type=effect_type,
        graph_id=graph.graph_id,
        graph_version=graph.graph_version,
        status=status,
        proposed_adjustment_set=tuple(sorted(proposed)),
        treatment_descendants_in_adjustment_set=descendants_in_set,
        minimal_adjustment_set=minimal_adjustment_set,
        likely_collider_members=tuple(likely_colliders),
        limitations=tuple(limitations),
    )
