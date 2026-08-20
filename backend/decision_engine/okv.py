"""
Operational Knowledge Value (OKV)
====================================
Cost-normalized Expected Value of Information for scout deployment decisions.

Definition:
    EVI(s) = E_Y [ max_a E_{x|Y} [U(a, x)] ] - max_a E_x [U(a, x)]
    OKV(s) = EVI(s) / c(s)

Where:
    s      = candidate scout node (a graph node_id to observe)
    Y      = random observation outcome (SAFE | DANGER) from scouting s
    P(Y=SAFE)   = 1 - node.p_danger  (current prior)
    P(Y=DANGER) = node.p_danger
    c(s)   = travel cost to reach s and perform observation
             = (haversine_distance / scout_speed) × time_value + fuel_cost
    η      = sensor accuracy (from sensor model defaults)

    After observation Y, the belief at node s is updated via Bayes' rule:
        P(danger | Y=SAFE)   = p × (1-η) / [p(1-η) + (1-p)η]
        P(danger | Y=DANGER) = p × η     / [pη + (1-p)(1-η)]
    This post-observation belief propagates to route confidence on all paths
    through s, changing the utility of each portfolio.

OKV Interpretation:
    OKV > 1.0  → Each unit of scout cost yields > 1 unit of utility gain.
    OKV ∈ [0.5, 1.0] → Marginal gain. Scout if idle assets available.
    OKV < 0.5  → Scouting costs more than the information is worth.
    OKV < 0    → Scouting would degrade decision quality (EVI < 0, rare).

Scout Scheduling Policy:
    Rank all candidate nodes by descending OKV.
    Dispatch scouts in OKV order until all idle scouts are assigned.
    Re-evaluate after each observation lands (dynamic replanning).

References:
    - Raiffa & Schlaifer (1961), Applied Statistical Decision Theory.
    - Pearl (1988), Probabilistic Reasoning in Intelligent Systems.
    - Villani & Cugnasca (2024), POMDP-based UAV routing for SAR.
"""

import math
import copy
import random
from typing import List, Dict, Any, Optional, Tuple

import networkx as nx

from backend.decision_engine.dri import _portfolio_utility, _scenario_utility, _sample_scenarios


# ---------------------------------------------------------------------------
# Bayesian update (inlined to avoid circular dependency)
# ---------------------------------------------------------------------------

_SENSOR_ETA = 0.85   # Default UAV/scout sensor accuracy
_MIN_P      = 1e-4
_MAX_P      = 1.0 - 1e-4


def _bayes_update(p_prior: float, obs: str, eta: float = _SENSOR_ETA) -> float:
    """Binary Bayesian update. obs ∈ {'SAFE', 'DANGER'}."""
    if obs == "SAFE":
        num = p_prior * (1.0 - eta)
        den = p_prior * (1.0 - eta) + (1.0 - p_prior) * eta
    else:
        num = p_prior * eta
        den = p_prior * eta + (1.0 - p_prior) * (1.0 - eta)
    if den == 0:
        return p_prior
    return max(_MIN_P, min(_MAX_P, num / den))


# ---------------------------------------------------------------------------
# Utility re-estimation after observation (post-observation world)
# ---------------------------------------------------------------------------

def _post_obs_portfolio_utility(
    portfolio:   Dict[str, Any],
    observed_node: str,
    obs_outcome: str,      # "SAFE" | "DANGER"
    belief_graph: nx.Graph,
    eta: float = _SENSOR_ETA,
) -> float:
    """
    Estimates portfolio utility after updating the belief at `observed_node`.
    We locally patch p_danger and confidence on the observed node and its incident
    edges, then recompute portfolio utility using a lightweight fast path
    (no full re-routing; we adjust confidence proportionally).
    """
    node_data = belief_graph.nodes.get(observed_node, {})
    p_prior   = node_data.get("p_danger", 0.3)

    # Post-observation updated belief
    p_post    = _bayes_update(p_prior, obs_outcome, eta)
    delta_p   = p_post - p_prior                         # change in danger belief

    # Confidence update: higher confidence after observation
    conf_gain = (1.0 - abs(delta_p)) * 0.15 if obs_outcome == "SAFE" else -0.05
    new_conf  = max(0.0, min(1.0, node_data.get("confidence", 0.5) + conf_gain))

    # How many portfolio assignments route through this node?
    assignments = portfolio.get("assignments", [])
    affected_count = sum(
        1 for a in assignments if observed_node in a.get("path", [])
    )

    # Adjust the base utility
    base_util = _portfolio_utility(portfolio)

    # Routing benefit: if SAFE, paths through observed_node become more reliable
    if obs_outcome == "SAFE" and affected_count > 0:
        route_bonus = affected_count * conf_gain * 15.0
    elif obs_outcome == "DANGER" and affected_count > 0:
        # Paths through danger node now need re-routing — utility penalty
        route_bonus = affected_count * delta_p * (-20.0)
    else:
        route_bonus = 0.0

    return base_util + route_bonus


# ---------------------------------------------------------------------------
# Travel cost model c(s)
# ---------------------------------------------------------------------------

def _travel_cost(
    source:      str,
    target:      str,
    belief_graph: nx.Graph,
    scout_speed_kmh: float = 60.0,   # km/h for ground scout (UAV uses 120)
    time_value:  float     = 2.0,    # utility per minute spent travelling
    fuel_per_km: float     = 0.5,    # utility cost per km of fuel
) -> float:
    """
    c(s) = (distance_km / speed_kmh × 60 minutes) × time_value + dist_km × fuel_per_km
    Returns combined time+fuel cost in utility units.
    """
    try:
        path_nodes = nx.shortest_path(belief_graph, source, target, weight="distance")
        dist_m = sum(
            belief_graph.edges[path_nodes[i], path_nodes[i + 1]].get("distance", 500.0)
            for i in range(len(path_nodes) - 1)
        )
    except Exception:
        # Rough haversine fallback using stored lat/lon
        s_data = belief_graph.nodes.get(source, {})
        t_data = belief_graph.nodes.get(target, {})
        lat1, lon1 = s_data.get("lat", 0), s_data.get("lon", 0)
        lat2, lon2 = t_data.get("lat", 0), t_data.get("lon", 0)
        R = 6_371_000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        dist_m = 2.0 * R * math.asin(math.sqrt(max(0.0, a)))

    dist_km      = dist_m / 1000.0
    travel_time  = (dist_km / max(0.1, scout_speed_kmh)) * 60.0   # minutes
    return travel_time * time_value + dist_km * fuel_per_km


# ---------------------------------------------------------------------------
# OKV Engine
# ---------------------------------------------------------------------------

class OperationalKnowledgeValue:
    """
    Computes OKV(s) = EVI(s) / c(s) for all candidate scout nodes.

    Algorithm per node s:
        1. baseline = max_a E_x[U(a, x)]   (approximated by best portfolio utility)
        2. For each observation outcome Y ∈ {SAFE, DANGER}:
               P(Y) = node.p_danger if Y=DANGER, else 1 - node.p_danger
               post_EU(Y) = max_a utility(a | observation Y at s)
        3. EVI(s) = Σ_Y P(Y) × post_EU(Y) - baseline
        4. c(s)   = travel cost model
        5. OKV(s) = EVI(s) / c(s)
    """

    @classmethod
    def compute_all(
        cls,
        belief_graph:       nx.Graph,
        portfolios:         List[Dict[str, Any]],
        scout_base_node:    str,
        candidate_nodes:    Optional[List[str]] = None,
        n_top:              int   = 10,
        eta:                float = _SENSOR_ETA,
        scout_speed_kmh:    float = 60.0,
    ) -> Dict[str, Any]:
        """
        Computes OKV for all candidate scout target nodes.

        Args:
            belief_graph:   Current belief graph.
            portfolios:     List of ranked portfolios from DecisionOptimizer.
            scout_base_node: The base node where scouts are stationed.
            candidate_nodes: Nodes to evaluate. Default: all uncertain nodes.
            n_top:          Return top-N by OKV (performance limit).
            eta:            Sensor accuracy (0.85 default for UAV).
            scout_speed_kmh: Scout vehicle speed for cost model.

        Returns:
            Dict with okv_ranking, baseline_eu, total_candidate_nodes, policy.
        """
        if not portfolios:
            return {"error": "No portfolios to evaluate.", "okv_ranking": []}

        # Baseline: best expected utility without any additional observation
        baseline_eu = max(_portfolio_utility(p) for p in portfolios)

        # Default: evaluate uncertain, non-base nodes
        if candidate_nodes is None:
            candidate_nodes = [
                n for n, d in belief_graph.nodes(data=True)
                if d.get("confidence", 1.0) < 0.75
                   and n != scout_base_node
                   and d.get("node_type") not in ("SHELTER", "HOSPITAL")
            ]
        candidate_nodes = candidate_nodes[:50]   # Hard cap for performance

        if not candidate_nodes:
            return {
                "okv_ranking": [],
                "baseline_eu": round(baseline_eu, 4),
                "total_candidate_nodes": 0,
                "policy": "No uncertain nodes to scout. Proceed with execution.",
            }

        results = []

        for node_id in candidate_nodes:
            node_data  = belief_graph.nodes.get(node_id, {})
            p_danger   = node_data.get("p_danger", 0.3)
            confidence = node_data.get("confidence", 0.5)

            # Skip near-certain nodes (wasted scout)
            if confidence > 0.9:
                continue

            # Prior observation probabilities
            p_obs_safe   = max(0.01, 1.0 - p_danger)
            p_obs_danger = max(0.01, p_danger)
            # Normalise
            total_p = p_obs_safe + p_obs_danger
            p_obs_safe   /= total_p
            p_obs_danger /= total_p

            # Post-observation expected utility for each outcome
            eu_given_safe   = max(
                _post_obs_portfolio_utility(p, node_id, "SAFE",   belief_graph, eta)
                for p in portfolios
            )
            eu_given_danger = max(
                _post_obs_portfolio_utility(p, node_id, "DANGER", belief_graph, eta)
                for p in portfolios
            )

            # EVI(s) = E_Y[max_a EU(a|Y)] - baseline
            eu_after = p_obs_safe * eu_given_safe + p_obs_danger * eu_given_danger
            evi = eu_after - baseline_eu

            # c(s) — travel cost
            cost = _travel_cost(
                scout_base_node, node_id, belief_graph,
                scout_speed_kmh=scout_speed_kmh
            )
            cost = max(0.1, cost)   # prevent zero-division

            okv = evi / cost

            results.append({
                "node_id":      node_id,
                "node_type":    node_data.get("node_type", "JUNCTION"),
                "p_danger":     round(p_danger, 4),
                "confidence":   round(confidence, 4),
                "evi":          round(evi, 4),
                "cost":         round(cost, 4),
                "okv":          round(okv, 4),
                "eu_if_safe":   round(eu_given_safe, 4),
                "eu_if_danger": round(eu_given_danger, 4),
                "eu_expected_after": round(eu_after, 4),
                "priority":     cls._priority_label(okv),
                "rationale":    cls._rationale(node_id, okv, evi, cost, p_danger, node_data),
            })

        # Sort by OKV descending
        results.sort(key=lambda r: r["okv"], reverse=True)
        top_n = results[:n_top]

        policy = cls._scouting_policy(top_n, baseline_eu)

        return {
            "okv_ranking":           top_n,
            "baseline_eu":           round(baseline_eu, 4),
            "total_candidate_nodes": len(results),
            "top_scout_target":      top_n[0]["node_id"] if top_n else None,
            "top_okv":               top_n[0]["okv"] if top_n else 0.0,
            "policy":                policy,
            "eta":                   eta,
        }

    @staticmethod
    def _priority_label(okv: float) -> str:
        if okv >= 1.0:  return "HIGH"
        if okv >= 0.5:  return "MEDIUM"
        if okv >= 0.0:  return "LOW"
        return "NEGATIVE"

    @staticmethod
    def _rationale(
        node_id: str, okv: float, evi: float, cost: float,
        p_danger: float, node_data: dict
    ) -> str:
        pop   = node_data.get("population", 0) or 0
        triage = (node_data.get("triage_immediate", 0) or 0)
        return (
            f"Node {node_id}: p_danger={p_danger:.2f}, "
            f"EVI={evi:.2f}, c={cost:.2f}, OKV={okv:.2f}. "
            f"Pop={pop}, triage={triage}. "
            + ("Scout immediately (high OKV)." if okv >= 1.0
               else "Scout if idle asset available." if okv >= 0.5
               else "Scout only if no higher-OKV targets remain." if okv >= 0.0
               else "Do not scout — information gain does not justify cost.")
        )

    @staticmethod
    def _scouting_policy(ranking: List[Dict], baseline_eu: float) -> str:
        if not ranking:
            return "All nodes are sufficiently certain. No scouting required."
        top = ranking[0]
        if top["okv"] < 0.0:
            return "All scouting options have negative OKV. Execute current plan."
        if top["okv"] < 0.5:
            return (
                f"Marginal scouting gain. Best node={top['node_id']} "
                f"(OKV={top['okv']:.2f}). Scout only if idle assets available."
            )
        return (
            f"Dispatch scout to node '{top['node_id']}' (OKV={top['okv']:.2f}). "
            f"Expected utility gain: {top['evi']:.2f} at cost {top['cost']:.2f}. "
            f"Scouting {len([r for r in ranking if r['okv'] > 0.5])} high-priority nodes recommended."
        )
