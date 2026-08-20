"""
Execution Governance Layer — Explainability Engine (XE)
========================================================
Single responsibility: transform a DAPResult into human-readable
rationale strings. No computation of any kind.

Three output formats:
1. plain_english() — One-paragraph summary for the EOC dashboard.
   Written as a commander would speak. No greek letters. No math.
2. technical_breakdown() — Full dimension-by-dimension report for
   the XAI panel. Includes regret values and phase information.
3. xai_event() — Structured dict for the frontend event log.

The XE is the only module that reads node names, so it imports
world_state for human-readable labels. All other EGL modules use
raw node IDs only.
"""

from __future__ import annotations

from typing import Any, Dict

from backend.execution_governance.dap import DAPResult

# Dimension labels for readability
_DIM_LABELS = {
    "epsilon": "Intelligence Confidence",
    "sigma":   "Crew Safety",
    "kappa":   "Communications",
    "rho":     "Resource Sufficiency",
    "delta":   "Source Independence",
}

# Outcome descriptions
_OUTCOME_DESC = {
    "EXECUTE":        "✅ DISPATCH AUTHORIZED",
    "STAGED_EXECUTE": "⏸️ STAGED DISPATCH — proceed to staging point, await re-evaluation",
    "DEFER":          "⏳ DISPATCH DEFERRED — additional reconnaissance recommended",
    "ESCALATE":       "🚨 COMMANDER DECISION REQUIRED",
}


class ExplainabilityEngine:
    """
    Generates human-readable explanations from DAPResult.

    No state. No side effects. All methods are pure functions
    of their inputs.
    """

    # ------------------------------------------------------------------
    # Format 1: Plain English (for dashboard)
    # ------------------------------------------------------------------

    @staticmethod
    def plain_english(
        result:      DAPResult,
        agent_id:    str,
        target_node: str,
    ) -> str:
        """
        One-paragraph summary written as a fireground commander would speak.

        Examples:
        - EXECUTE: "Dispatching RESCUE-3 to Maple Street. Route confidence 78%.
                    Delay risk (1.84) outweighs crew risk (0.92). Golden hour active."
        - DEFER:   "Holding RESCUE-3. Road confidence on route to node_42 is only 41%.
                    Scout verification requested. Reassessing next cycle."
        - ESCALATE:"Commander decision required for RESCUE-3 targeting node_42.
                    Both action risk (1.84) and delay risk (1.79) are critical.
                    60-second decision window is open."
        """
        # Resolve human-readable target name
        target_name = _get_node_name(target_node)

        # Identify the weakest dimension (lowest score)
        dims = {
            "intelligence confidence": result.epsilon,
            "crew safety":             result.sigma,
            "communications":          result.kappa,
            "resource levels":         result.rho,
            "source independence":     result.delta,
        }
        weakest_name = min(dims, key=dims.get)
        weakest_val  = dims[weakest_name]

        # Build the sentence
        if result.veto:
            return (
                f"⛔ {agent_id} BLOCKED from dispatching to {target_name}. "
                f"Safety veto: {result.veto}."
            )

        if result.outcome == "EXECUTE":
            return (
                f"Dispatching {agent_id} to {target_name}. "
                f"Route confidence {result.epsilon * 100:.0f}%. "
                f"Delay risk ({result.regret_wait:.2f}) outweighs action risk ({result.regret_act:.2f}). "
                f"{'Golden hour active — expedited.' if result.phase == 'GOLDEN_HOUR' else f'Phase: {result.phase.replace('_', ' ').title()}.'}"
            )

        if result.outcome == "STAGED_EXECUTE":
            return (
                f"Staging {agent_id} toward {target_name} (high-commitment action, I={result.irreversibility:.2f}). "
                f"Agent will pause at the 33% point for updated intelligence. "
                f"Weakest factor: {weakest_name} at {weakest_val * 100:.0f}%. "
                f"Full dispatch contingent on re-evaluation."
            )

        if result.outcome == "DEFER":
            return (
                f"Holding {agent_id}. Dispatch to {target_name} deferred. "
                f"Primary concern: {weakest_name} is only {weakest_val * 100:.0f}%. "
                f"Action risk ({result.regret_act:.2f}) exceeds delay risk ({result.regret_wait:.2f}). "
                f"Scout verification recommended before retry."
            )

        if result.outcome == "ESCALATE":
            return (
                f"Commander decision required: {agent_id} → {target_name}. "
                f"Action risk ({result.regret_act:.2f}) and delay risk ({result.regret_wait:.2f}) "
                f"are both critical and within margin ({result.effective_margin:.2f}). "
                f"Weakest factor: {weakest_name} at {weakest_val * 100:.0f}%. "
                f"Awaiting your decision."
            )

        return f"EGL decision for {agent_id}: {result.outcome}."

    # ------------------------------------------------------------------
    # Format 2: Technical breakdown (for XAI panel)
    # ------------------------------------------------------------------

    @staticmethod
    def technical_breakdown(result: DAPResult) -> str:
        """
        Multi-line technical summary including all dimensions, regret
        values, phase, and ethical profile info.
        """
        lines = [
            f"=== DAP Technical Report ===",
            f"Outcome:     {result.outcome}",
            f"Phase:       {result.phase}",
            f"",
            f"--- Adequacy Dimensions ---",
            f"  ε (Epistemic Readiness):    {result.epsilon:.4f}",
            f"  σ (Crew Safety Index):      {result.sigma:.4f}",
            f"  κ (Comms Reliability):      {result.kappa:.4f}",
            f"  ρ (Resource Sufficiency):   {result.rho:.4f}",
            f"  δ (Source Diversity):       {result.delta:.4f}",
            f"  τ_avg (Sensor Trust):       {result.tau_avg:.4f}",
            f"  Composite (geometric mean): {result.composite_score:.4f}",
            f"",
            f"--- Regret Analysis ---",
            f"  R_act  (risk of acting):    {result.regret_act:.4f}",
            f"  R_wait (risk of waiting):   {result.regret_wait:.4f}",
            f"  Effective margin (m):       {result.effective_margin:.4f}",
            f"  R_wait - R_act:             {result.regret_wait - result.regret_act:.4f}",
            f"  |diff| vs margin:           {'R_wait dominates → EXECUTE' if result.regret_wait > result.regret_act + result.effective_margin else 'R_act dominates → DEFER' if result.regret_act > result.regret_wait + result.effective_margin else 'Within margin → ESCALATE'}",
            f"",
            f"--- Context ---",
            f"  Irreversibility (I):        {result.irreversibility:.2f}",
            f"  Access Equity Mult. (AEM):  {result.aem:.4f}",
            f"  Veto:                       {result.veto or 'None'}",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Format 3: Structured dict (for frontend XAI event log)
    # ------------------------------------------------------------------

    @staticmethod
    def xai_event(
        result:      DAPResult,
        agent_id:    str,
        target_node: str,
        rationale:   str,
    ) -> Dict[str, Any]:
        """
        Structured dictionary for the frontend event log.
        Compatible with the existing add_xai_event() pattern in engine.py.
        """
        return {
            "type":             "egl_decision",
            "outcome":          result.outcome,
            "outcome_label":    _OUTCOME_DESC.get(result.outcome, result.outcome),
            "agent_id":         agent_id,
            "target_node":      target_node,
            "target_name":      _get_node_name(target_node),
            "phase":            result.phase,
            "epsilon":          round(result.epsilon, 3),
            "sigma":            round(result.sigma, 3),
            "kappa":            round(result.kappa, 3),
            "rho":              round(result.rho, 3),
            "delta":            round(result.delta, 3),
            "tau_avg":          round(result.tau_avg, 3),
            "aem":              round(result.aem, 3),
            "regret_act":       round(result.regret_act, 3),
            "regret_wait":      round(result.regret_wait, 3),
            "irreversibility":  round(result.irreversibility, 3),
            "effective_margin": round(result.effective_margin, 3),
            "composite_score":  round(result.composite_score, 3),
            "veto":             result.veto,
            "rationale":        rationale,
        }

    # ------------------------------------------------------------------
    # Dimension-level alert (for individual dimension warnings)
    # ------------------------------------------------------------------

    @staticmethod
    def dimension_alerts(result: DAPResult) -> list:
        """
        Returns a list of alert messages for dimensions below critical
        thresholds. Empty list means all dimensions are acceptable.

        Alert thresholds:
        - ε < 0.40: "Intelligence gap"
        - σ < 0.30: "Crew safety at risk"
        - κ < 0.40: "Communications degraded"
        - ρ < 0.30: "Resource shortage"
        - δ < 0.20: "Correlated evidence — source diversity needed"
        """
        alerts = []
        if result.epsilon < 0.40:
            alerts.append({
                "dimension": "epsilon",
                "label": "Intelligence Confidence",
                "value": round(result.epsilon, 3),
                "severity": "critical" if result.epsilon < 0.20 else "warning",
                "message": f"Intelligence confidence is only {result.epsilon * 100:.0f}%. "
                           f"Target node has insufficient observation history.",
            })
        if result.sigma < 0.30:
            alerts.append({
                "dimension": "sigma",
                "label": "Crew Safety",
                "value": round(result.sigma, 3),
                "severity": "critical",
                "message": f"Crew safety index is {result.sigma * 100:.0f}%. "
                           f"Route traverses high-danger zones.",
            })
        if result.kappa < 0.40:
            alerts.append({
                "dimension": "kappa",
                "label": "Communications",
                "value": round(result.kappa, 3),
                "severity": "warning",
                "message": f"Comms reliability is {result.kappa * 100:.0f}%. "
                           f"Crew may lose contact with EOC en route.",
            })
        if result.rho < 0.30:
            alerts.append({
                "dimension": "rho",
                "label": "Resource Sufficiency",
                "value": round(result.rho, 3),
                "severity": "critical" if result.rho < 0.15 else "warning",
                "message": f"Resource sufficiency is {result.rho * 100:.0f}%. "
                           f"{'Fuel critical.' if result.rho < 0.15 else 'Fleet reserve low.'}",
            })
        if result.delta < 0.20:
            alerts.append({
                "dimension": "delta",
                "label": "Source Diversity",
                "value": round(result.delta, 3),
                "severity": "warning",
                "message": f"Source diversity is only {result.delta * 100:.0f}%. "
                           f"All observations come from the same sensor type — "
                           f"evidence may be correlated, not independent.",
            })
        return alerts


# ---------------------------------------------------------------------------
# Helper: resolve node ID to human-readable name
# ---------------------------------------------------------------------------

def _get_node_name(node_id: str) -> str:
    """
    Attempts to resolve a node_id to a human-readable name using
    world_state. Falls back to the raw ID if unavailable.
    """
    try:
        from backend.world_model.world_state import world_state
        return world_state.get_node_human_name(node_id)
    except Exception:
        return str(node_id)
