"""
Execution Governance Layer — Orchestrator (EGL)
================================================
Thin wiring module. The only class that external code (Coordinator,
Engine) interacts with.

The EGL orchestrator owns no computation. Its sole purpose is to
call sub-modules in the correct order and compose their outputs
into a single EGLDecision.

Call sequence per evaluation:
    1. FCM.check_mutex()           — fleet mutex
    2. EPM.get_weights()           — ethical weights for current phase
    3. FCM.get_effective_margin()  — DEFER-decayed margin
    4. DAP.evaluate()              — pure math core
    5. FCM.increment_defer()       — if DEFER, track starvation counter
    6. FCM.register_dispatch()     — if EXECUTE/STAGED, lock target
    7. HOM.request_override()      — if ESCALATE, create TBHO request
    8. XE.plain_english()          — generate rationale
    9. AM.write()                  — append audit record (always)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import networkx as nx

from backend.agents.base_agent import BaseAgent
from backend.execution_governance.dap import DAPResult, DecisionAdequacyProtocol, MissionWeights
from backend.execution_governance.mission_policy import MissionPolicyManager
from backend.execution_governance.audit import AuditManager, EGLAuditRecord
from backend.execution_governance.human_override import HumanOverrideManager, OverrideRequest
from backend.execution_governance.fleet_coordinator import FleetCoordinationManager
from backend.execution_governance.explainability import ExplainabilityEngine

# ---------------------------------------------------------------------------
# Operational Context
# ---------------------------------------------------------------------------

@dataclass
class OperationalContext:
    """
    Encapsulates the current operational context of the disaster response.
    Divides time into distinct phases based on emergency management doctrine.
    """
    phase: str
    hours_elapsed: float

    @classmethod
    def from_sim_time(cls, sim_time: float) -> OperationalContext:
        hours_elapsed = sim_time / 60.0
        # Phase boundaries (Category A — ICRC / FEMA ICS citations in egl_config.json)
        # Golden Hour: 0–60 min (ICRC Trauma Care 2013).
        # Sustained Ops: 60–360 min (FEMA ICS P-1035 operational period).
        if sim_time < 60.0:
            phase = "GOLDEN_HOUR"
        elif sim_time < 360.0:
            phase = "SUSTAINED_OPS"
        else:
            phase = "RECOVERY"
        return cls(phase=phase, hours_elapsed=hours_elapsed)


# ---------------------------------------------------------------------------
# Output data class
# ---------------------------------------------------------------------------

@dataclass
class EGLDecision:
    """
    Complete output of an EGL evaluation.
    Consumed by the Coordinator to decide dispatch actions.
    """
    dap_result:       DAPResult
    outcome:          str          # Final outcome (may differ from DAP if FCM forces ESCALATE)
    rationale:        str          # Plain-English explanation
    rationale_tech:   str          # Technical breakdown
    xai_event:        Dict[str, Any]  # Structured dict for frontend
    alerts:           List[Dict]   # Per-dimension warnings
    override_request: Optional[OverrideRequest] = None  # Non-None if ESCALATE → TBHO
    shadow:           bool = False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class ExecutionGovernanceLayer:
    """
    The single entry point for all execution governance decisions.

    Usage
    -----
    egl = ExecutionGovernanceLayer()  # creates all sub-modules with defaults
    decision = egl.evaluate(action_class, agent, target, ...)

    if decision.outcome == "EXECUTE":       dispatch normally
    elif decision.outcome == "STAGED_EXECUTE": dispatch to staging node
    elif decision.outcome == "DEFER":       push to OKV scout queue
    elif decision.outcome == "ESCALATE":    TBHO request sent to frontend
    """

    def __init__(
        self,
        dap: Optional[DecisionAdequacyProtocol]    = None,
        epm: Optional[MissionPolicyManager]        = None,
        am:  Optional[AuditManager]                = None,
        hom: Optional[HumanOverrideManager]        = None,
        fcm: Optional[FleetCoordinationManager]    = None,
        xe:  Optional[ExplainabilityEngine]        = None,
        shadow_mode: bool                          = False,
    ) -> None:
        """
        Accepts pre-constructed sub-modules for testing (dependency injection).
        Defaults create production instances.
        """
        self.dap = dap or DecisionAdequacyProtocol()
        self.epm = epm or MissionPolicyManager()
        self.am  = am  or AuditManager()
        self.hom = hom or HumanOverrideManager()
        self.fcm = fcm or FleetCoordinationManager()
        self.xe  = xe  or ExplainabilityEngine()
        self.shadow_mode = shadow_mode

        # Wire audit manager into policy manager for profile change logging
        self.epm._audit_manager = self.am
        self.outcome_counts: Dict[str, int] = {"EXECUTE": 0, "STAGED_EXECUTE": 0, "DEFER": 0, "ESCALATE": 0}

    # ------------------------------------------------------------------
    # Main evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        action_class:   str,
        agent:          BaseAgent,
        target_node:    str,
        route:          List[str],
        belief_graph:   nx.Graph,
        fleet_state:    Dict[str, Any],
        blackout_zones: List[Dict[str, float]],
        forecasts:      Dict[str, Any],
        disaster_type:  str,
        sim_time:       float,
    ) -> EGLDecision:
        """
        Run the full EGL evaluation pipeline.

        Parameters match DAP.evaluate() — the orchestrator adds fleet-level
        and ethical-level context transparently.
        """
        # 1. Fleet mutex check
        context = OperationalContext.from_sim_time(sim_time)
        target_pop = belief_graph.nodes.get(target_node, {}).get("population", 0) if belief_graph else 0
        agent_cap = getattr(agent, "capacity", 50)
        if self.fcm.check_mutex(target_node, target_pop=target_pop, agent_cap=agent_cap):
            # Target already has an active dispatch — DEFER with a fleet mutex veto
            dummy_result = DAPResult(
                outcome="DEFER",
                phase=context.phase,
                epsilon=0.0, sigma=0.0, kappa=0.0, rho=0.0, delta=0.0,
                tau_avg=0.0, aem=1.0, irreversibility=0.0,
                regret_act=0.0, regret_wait=0.0,
                effective_margin=0.0,
                veto="FLEET_MUTEX: another agent already dispatched to this target",
            )
            rationale = self.xe.plain_english(dummy_result, agent.id, target_node)
            xai = self.xe.xai_event(dummy_result, agent.id, target_node, rationale)

            # Log even mutex decisions — auditability matters
            self._write_audit(dummy_result, agent.id, target_node, sim_time)

            return EGLDecision(
                dap_result=dummy_result,
                outcome="DEFER",
                rationale=rationale,
                rationale_tech=self.xe.technical_breakdown(dummy_result),
                xai_event=xai,
                alerts=[],
                shadow=self.shadow_mode,
            )

        # 2. Get mission weights for current phase
        # Fix 7: Auto-select disaster-appropriate mission profile
        # Flood uses CIVILIAN_PRIORITY because water vehicles (boats, HW trucks)
        # are purpose-built for flood ops — crew risk is inherently lower.
        # This reduces R_act, allowing more dispatches to pass the regret threshold.
        _DISASTER_PROFILES = {
            "FLOOD": "CIVILIAN_PRIORITY",
            "EARTHQUAKE": "BALANCED",
            "CYCLONE": "BALANCED",
            "WILDFIRE": "BALANCED",
        }
        desired_profile = _DISASTER_PROFILES.get(disaster_type.upper(), "BALANCED")
        if self.epm.active_profile_name != desired_profile:
            self.epm.set_profile(desired_profile, officer_id="EGL_AUTO_DISASTER_POLICY")
            self.epm.commit_pending_profile()
        mission_weights = self.epm.get_weights(context.phase)

        # 3. Get effective margin (with DEFER decay from FCM)
        effective_m = self.fcm.get_effective_margin(target_node)
        forced_escalate = effective_m < 0  # FCM returns -1.0 → force ESCALATE

        if forced_escalate:
            effective_m = 0.03  # Use minimum margin for the DAP computation
            # DAP still runs to produce dimension scores for the audit log

        # 4. DAP core evaluation (pure math)
        dap_result = self.dap.evaluate(
            action_class=action_class,
            agent=agent,
            target_node=target_node,
            route=route,
            belief_graph=belief_graph,
            fleet_state=fleet_state,
            blackout_zones=blackout_zones,
            forecasts=forecasts,
            disaster_type=disaster_type,
            hours_elapsed=context.hours_elapsed,
            mission_weights=mission_weights,
            effective_margin=effective_m,
            phase=context.phase,
        )

        # 5. Apply post-DAP overrides
        final_outcome = dap_result.outcome

        # DEFER starvation override: FCM says this target has been deferred too many times
        # Only override DEFER → ESCALATE; never block a valid EXECUTE or STAGED_EXECUTE
        if forced_escalate and final_outcome == "DEFER":
            final_outcome = "ESCALATE"


        override_request: Optional[OverrideRequest] = None

        if final_outcome == "ESCALATE":
            # 7. Create TBHO request for human decision
            # Lock target temporarily during TBHO evaluation window to prevent redundant dispatches
            # Skip state mutations in shadow mode to prevent capacity leaks
            if not self.shadow_mode:
                from backend.agents.fleet_config import FLEET_SPECIFICATIONS
                v_type = getattr(agent, "vehicle_type", "STANDARD_CAR")
                agent_cap = FLEET_SPECIFICATIONS.get(v_type, {}).get("capacity", 50)
                self.fcm.register_dispatch(agent.id, target_node, agent_cap)
                rationale_preview = self.xe.plain_english(dap_result, agent.id, target_node)
                override_request = self.hom.request_override(
                    dap_result=dap_result,
                    agent_id=agent.id,
                    target_node=target_node,
                    rationale=rationale_preview,
                    sim_time=sim_time,
                )

        elif final_outcome == "DEFER":
            # 5b. Track DEFER count (anti-starvation)
            if not self.shadow_mode:
                force_esc = self.fcm.increment_defer(target_node)
                if force_esc:
                    # This DEFER pushed the count over the threshold → ESCALATE next time
                    # We still emit DEFER this tick (the forced ESCALATE is handled on the
                    # next evaluation via get_effective_margin returning -1.0)
                    pass

        elif final_outcome in ("EXECUTE", "STAGED_EXECUTE"):
            # 6. Lock the target and clear DEFER counter
            if not self.shadow_mode:
                from backend.agents.fleet_config import FLEET_SPECIFICATIONS
                v_type = getattr(agent, "vehicle_type", "STANDARD_CAR")
                agent_cap = FLEET_SPECIFICATIONS.get(v_type, {}).get("capacity", 50)
                self.fcm.register_dispatch(agent.id, target_node, agent_cap)
                self.fcm.reset_defer_count(target_node)

                # For STAGED_EXECUTE, register the staged state with FCM
                if final_outcome == "STAGED_EXECUTE":
                    staging_node = self.fcm.compute_staging_node(route, belief_graph)
                    if staging_node:
                        self.fcm.register_staged(agent.id, target_node, staging_node, route, action_class)
                    else:
                        # Fallback to EXECUTE (direct dispatch) if no intermediate staging node could be found
                        final_outcome = "EXECUTE"


        # 8. Generate explanations
        rationale = self.xe.plain_english(dap_result, agent.id, target_node)
        rationale_tech = self.xe.technical_breakdown(dap_result)
        xai = self.xe.xai_event(dap_result, agent.id, target_node, rationale)
        alerts = self.xe.dimension_alerts(dap_result)

        # 9. Audit log (always — shadow or not)
        self._write_audit(
            dap_result, agent.id, target_node, sim_time,
            ethical_profile=mission_weights.profile_name,
            human_override=None,  # Will be updated by HOM when resolved
        )

        self.outcome_counts[final_outcome] = self.outcome_counts.get(final_outcome, 0) + 1

        effective_outcome = "EXECUTE" if self.shadow_mode else final_outcome

        return EGLDecision(
            dap_result=dap_result,
            outcome=effective_outcome,
            rationale=rationale,
            rationale_tech=rationale_tech,
            xai_event=xai,
            alerts=alerts,
            override_request=override_request,
            shadow=self.shadow_mode,
        )


    # ------------------------------------------------------------------
    # Staged dispatch re-evaluation
    # ------------------------------------------------------------------

    def re_evaluate_staged(
        self,
        agent:          BaseAgent,
        belief_graph:   nx.Graph,
        fleet_state:    Dict[str, Any],
        blackout_zones: List[Dict[str, float]],
        forecasts:      Dict[str, Any],
        disaster_type:  str = "FLOOD",
        sim_time:       float = 0.0,
    ) -> Optional[EGLDecision]:
        """
        Re-evaluate a staged agent with fresher data.

        If the re-evaluation returns EXECUTE or STAGED_EXECUTE,
        the agent continues to the target (complete_staged).
        If it returns DEFER or ESCALATE, the agent aborts.

        Returns None if the agent is not in staged state.
        """
        staged = self.fcm.get_staged_state(agent.id)
        if staged is None:
            return None

        target_node = staged.target_node

        # Temporarily release target lock so evaluate() check_mutex doesn't self-block
        from backend.agents.fleet_config import FLEET_SPECIFICATIONS
        v_type = getattr(agent, "vehicle_type", "STANDARD_CAR")
        agent_cap = FLEET_SPECIFICATIONS.get(v_type, {}).get("capacity", 50)
        self.fcm.release_target(target_node, agent_cap)

        # Re-evaluate with the same action class
        # (staged dispatch is always for high-I actions)
        remaining_route = self.fcm.complete_staged(agent.id)
        if not remaining_route:
            # Already popped and released
            return None

        full_route = [agent.current_node] + remaining_route
        decision = self.evaluate(
            action_class=staged.action_class,
            agent=agent,
            target_node=target_node,
            route=full_route,
            belief_graph=belief_graph,
            fleet_state=fleet_state,
            blackout_zones=blackout_zones,
            forecasts=forecasts,
            disaster_type=disaster_type,
            sim_time=sim_time,
        )

        return decision

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_new_planning_cycle(self, sim_time: float = 0.0) -> None:
        """
        Called at the start of each planning cycle.
        Commits pending ethical profile changes and checks for TBHO timeouts.
        """
        self.epm.commit_pending_profile()
        
        # Check and apply TBHO timeouts based on simulation time
        from datetime import datetime, timezone
        for request_id, req in list(self.hom._pending.items()):
            if not req.resolved:
                if sim_time > 0:
                    sim_elapsed_s = (sim_time - getattr(req, 'created_sim_time', 0.0)) * 60.0
                    if sim_elapsed_s >= req.timeout_s:
                        self.hom.apply_timeout_default(request_id)
                else:
                    created = datetime.fromisoformat(req.created_at)
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    elapsed = (datetime.now(timezone.utc) - created).total_seconds()
                    if elapsed >= req.timeout_s:
                        self.hom.apply_timeout_default(request_id)

        # Prune old resolved TBHO requests to prevent memory leaks
        self.hom.cleanup_resolved(keep_last_n=100)

    def on_agent_mission_complete(self, agent_id: str, target_node: str, agent_capacity: int = 50) -> None:
        """
        Called when an agent completes or aborts a mission.
        Releases the fleet mutex lock on the target.
        """
        self.fcm.release_target(target_node, agent_capacity)
        if self.fcm.is_agent_staged(agent_id):
            self.fcm.abort_staged(agent_id)

    def reset(self) -> None:
        """Full state reset — called when simulation is re-initialised."""
        self.fcm.reset()
        self.hom.reset()

    # ------------------------------------------------------------------
    # Status (for API / dashboard)
    # ------------------------------------------------------------------

    def status_dict(self) -> Dict[str, Any]:
        """Returns combined EGL status for the dashboard."""
        return {
            "ethical_policy":    self.epm.status_dict(),
            "fleet_coordinator": self.fcm.status_dict(),
            "override_rate":    self.hom.get_override_rate(),
            "pending_overrides": len(self.hom.get_pending_requests()),
            "shadow_mode":       self.shadow_mode,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write_audit(
        self,
        result:          DAPResult,
        agent_id:        str,
        target_node:     str,
        sim_time:        float,
        ethical_profile: str = "",
        human_override:  Optional[str] = None,
    ) -> None:
        """Write an audit record. Silently handles errors."""
        try:
            self.am.write(EGLAuditRecord(
                sim_time=sim_time,
                agent_id=agent_id,
                target_node=target_node,
                outcome=result.outcome,
                epsilon=result.epsilon,
                sigma=result.sigma,
                kappa=result.kappa,
                rho=result.rho,
                delta=result.delta,
                regret_act=result.regret_act,
                regret_wait=result.regret_wait,
                irreversibility=result.irreversibility,
                effective_margin=result.effective_margin,
                phase=result.phase,
                ethical_profile=ethical_profile,
                composite_score=result.composite_score,
                veto=result.veto,
                human_override=human_override,
                shadow=self.shadow_mode,
            ))
        except Exception as exc:
            print(f"[EGL] Audit write failed (non-blocking): {exc}")
