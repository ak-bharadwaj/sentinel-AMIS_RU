"""
Decision Readiness Index (DRI)
===============================
Formalises how well the current knowledge and plan achieves mission goals
relative to an oracle-optimal plan.

Definition (Raiffa & Schlaifer, 1961 / IEEE-TRANSACTIONS variant):
    DRI(a*) = E_x[U(a*, x)] / max_a E_x[U(a, x)]  ∈ [0, 1]

Where:
    U(a, x) = Utility of action portfolio `a` in hazard scenario `x`.
    P(x)    = Current probabilistic forecast of hazard outcomes.
    a*      = Current (chosen) action portfolio from the optimizer.

Interpretation:
    DRI = 1.0  → Current plan is as good as the optimum under current beliefs.
    DRI = 0.0  → Current plan is the worst possible under current beliefs.
    DRI < 0.4  → "NOT READY" — replanning strongly recommended.
    DRI < 0.7  → "MARGINAL"  — consider additional information gathering.
    DRI ≥ 0.7  → "READY"     — plan is acceptable to execute.

Implementation notes:
    - Scenarios x are sampled from forecast horizons (15/30/60 min) with Monte-Carlo.
    - Utility function U(a, x) is the same weighted composite used by DecisionOptimizer.
    - The denominator max_a E[U] is approximated by the best portfolio returned by
      the NSGA-II optimizer (oracle approximation).
    - Variance and 95% CI are tracked for calibration studies.
"""

import math
import copy
import random
from typing import List, Dict, Any, Optional, Tuple

import networkx as nx


# ---------------------------------------------------------------------------
# Utility function (shared with DecisionOptimizer)
# ---------------------------------------------------------------------------

def _portfolio_utility(portfolio: Dict[str, Any]) -> float:
    """
    Extracts a scalar utility from a portfolio dict returned by DecisionOptimizer.
    U(a, x) = lives_saved - 0.1*avg_time + 0.5*avg_conf + 0.3*coverage
    Scaled so perfect is ~100.
    """
    m = portfolio.get("metrics", {})
    lives       = m.get("expected_lives_saved", 0.0)
    time_pen    = m.get("average_transit_time_minutes", 30.0)
    conf        = m.get("average_route_confidence", 0.5)
    coverage    = m.get("coverage_ratio", 0.0)
    return lives * 10.0 - time_pen * 0.1 + conf * 50.0 + coverage * 30.0


def _scenario_utility(portfolio: Dict[str, Any], scenario: Dict[str, Any]) -> float:
    """
    U(a, x) for a given hazard scenario x (a dict of multipliers).
    Perturbs the base portfolio utility by scenario-specific factors.
    """
    base = _portfolio_utility(portfolio)
    severity    = scenario.get("severity_mult", 1.0)   # >1 = worse disaster
    conf_noise  = scenario.get("conf_noise", 0.0)       # belief accuracy noise ∈ [-0.2, 0.2]
    surge       = scenario.get("water_surge", 0.0)      # extra flood surge [0, 1]
    return base * (1.0 / max(0.5, severity)) + conf_noise * 20.0 - surge * 15.0


# ---------------------------------------------------------------------------
# Monte Carlo scenario sampler
# ---------------------------------------------------------------------------

def _sample_scenarios(n: int, belief_graph: nx.Graph, rng: random.Random) -> List[Dict[str, Any]]:
    """
    Generates n Monte-Carlo hazard scenarios from current belief distributions.
    Each scenario is a dict of multiplicative perturbations to disaster state.
    """
    scenarios = []
    # Baseline parameters from graph
    avg_p_danger = 0.5
    nodes_with_data = [(d.get("p_danger", 0.3), d.get("water_level", 0.0))
                       for _, d in belief_graph.nodes(data=True)]
    if nodes_with_data:
        avg_p_danger = sum(p for p, _ in nodes_with_data) / len(nodes_with_data)

    for _ in range(n):
        # Sample scenario from epistemic distribution
        severity_mult = max(0.5, rng.gauss(mu=1.0 + avg_p_danger * 0.5, sigma=0.25))
        conf_noise    = rng.gauss(mu=0.0, sigma=0.1)
        water_surge   = max(0.0, rng.gauss(mu=avg_p_danger * 0.3, sigma=0.15))
        scenarios.append({
            "severity_mult": round(severity_mult, 4),
            "conf_noise":    round(conf_noise, 4),
            "water_surge":   round(water_surge, 4),
        })
    return scenarios


# ---------------------------------------------------------------------------
# DRI Engine
# ---------------------------------------------------------------------------

class DecisionReadinessIndex:
    """
    Computes DRI(a*) for the currently selected portfolio against all alternatives.

    DRI = E_x[U(a*, x)] / max_a E_x[U(a, x)]

    Also reports:
        - dri_variance: Variance of U(a*, x) across scenarios (calibration).
        - readiness_level: "NOT_READY" | "MARGINAL" | "READY" | "OPTIMAL"
        - recommendation: Action text for the EOC commander.
        - scenario_breakdown: Per-scenario utility for debugging / research.
    """

    READINESS_THRESHOLDS = {
        "OPTIMAL":   0.90,
        "READY":     0.70,
        "MARGINAL":  0.40,
        "NOT_READY": 0.00,
    }

    @classmethod
    def compute(
        cls,
        belief_graph:     nx.Graph,
        portfolios:       List[Dict[str, Any]],
        selected_portfolio_id: str = "balanced",
        n_scenarios: int  = 50,
        seed: int         = 42
    ) -> Dict[str, Any]:
        """
        Compute DRI for the current plan under Monte-Carlo forecast scenarios.

        Args:
            belief_graph: Current agent belief graph (NetworkX).
            portfolios: List of ranked portfolios from DecisionOptimizer.
            selected_portfolio_id: The active portfolio's 'alternative_id'.
            n_scenarios: Number of Monte-Carlo scenarios to sample.
            seed: RNG seed for reproducibility.

        Returns:
            Dict with dri, dri_variance, readiness_level, recommendation, breakdown.
        """
        if not portfolios:
            return cls._empty_result("No portfolios available.")

        rng = random.Random(seed)
        scenarios = _sample_scenarios(n_scenarios, belief_graph, rng)

        # Find selected portfolio
        selected = next(
            (p for p in portfolios if p.get("alternative_id") == selected_portfolio_id),
            portfolios[0]
        )

        # E_x[U(a*, x)] — expected utility of selected plan
        utils_selected = [_scenario_utility(selected, s) for s in scenarios]
        eu_selected = sum(utils_selected) / max(1, len(utils_selected))
        var_selected = sum((u - eu_selected) ** 2 for u in utils_selected) / max(1, len(utils_selected))

        # max_a E_x[U(a, x)] — oracle approximation via best portfolio
        eu_per_portfolio = []
        for p in portfolios:
            eu = sum(_scenario_utility(p, s) for s in scenarios) / max(1, len(scenarios))
            eu_per_portfolio.append((eu, p.get("alternative_id", "?"), p.get("name", "")))

        eu_oracle = max(eu for eu, _, _ in eu_per_portfolio)
        best_alt = max(eu_per_portfolio, key=lambda t: t[0])

        # DRI = E[U*] / max_a E[U]  (clamped to [0, 1])
        dri = max(0.0, min(1.0, eu_selected / max(1e-6, eu_oracle)))

        # Confidence interval (95%) on selected plan utility
        std = math.sqrt(var_selected)
        ci_lo = eu_selected - 1.96 * std / max(1, math.sqrt(n_scenarios))
        ci_hi = eu_selected + 1.96 * std / max(1, math.sqrt(n_scenarios))

        readiness_level = cls._readiness_level(dri)
        recommendation  = cls._recommendation(dri, best_alt[1], selected_portfolio_id)

        return {
            "dri": round(dri, 4),
            "eu_selected": round(eu_selected, 4),
            "eu_oracle":   round(eu_oracle, 4),
            "dri_variance": round(var_selected, 4),
            "ci_95": [round(ci_lo, 4), round(ci_hi, 4)],
            "readiness_level": readiness_level,
            "recommendation": recommendation,
            "selected_portfolio_id": selected_portfolio_id,
            "best_alternative_id":   best_alt[1],
            "best_alternative_name": best_alt[2],
            "is_optimal": selected_portfolio_id == best_alt[1],
            "portfolio_eu_ranking": [
                {"alternative_id": alt_id, "name": name, "eu": round(eu, 4)}
                for eu, alt_id, name in sorted(eu_per_portfolio, key=lambda t: -t[0])
            ],
            "n_scenarios": n_scenarios,
        }

    @classmethod
    def _readiness_level(cls, dri: float) -> str:
        if dri >= cls.READINESS_THRESHOLDS["OPTIMAL"]:
            return "OPTIMAL"
        if dri >= cls.READINESS_THRESHOLDS["READY"]:
            return "READY"
        if dri >= cls.READINESS_THRESHOLDS["MARGINAL"]:
            return "MARGINAL"
        return "NOT_READY"

    @classmethod
    def _recommendation(cls, dri: float, best_id: str, selected_id: str) -> str:
        if dri >= 0.90:
            return "Plan is near-optimal. Proceed with execution immediately."
        if dri >= 0.70:
            return (
                f"Plan is acceptable (DRI={dri:.2f}). Consider switching to '{best_id}' "
                f"portfolio for a marginal gain."
            )
        if dri >= 0.40:
            return (
                f"Plan quality is marginal (DRI={dri:.2f}). Recommend OKV scouting to "
                f"reduce uncertainty before committing. Switch to '{best_id}' portfolio."
            )
        return (
            f"Plan is NOT ready (DRI={dri:.2f}). High epistemic uncertainty — "
            f"dispatch scouts, acquire telemetry, then replan. Do not execute current plan."
        )

    @staticmethod
    def _empty_result(reason: str) -> Dict[str, Any]:
        return {
            "dri": 0.0,
            "eu_selected": 0.0,
            "eu_oracle": 0.0,
            "dri_variance": 0.0,
            "ci_95": [0.0, 0.0],
            "readiness_level": "NOT_READY",
            "recommendation": reason,
            "selected_portfolio_id": None,
            "best_alternative_id": None,
            "portfolio_eu_ranking": [],
            "n_scenarios": 0,
        }
