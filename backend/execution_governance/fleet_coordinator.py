"""
Execution Governance Layer — Fleet Coordination Manager (FCM)
==============================================================
Single responsibility: track active dispatch targets, manage DEFER
state counters, and coordinate staged dispatch lifecycle.

No computation of adequacy dimensions. No regret math. No logging.

The FCM owns three pieces of mutable state:
1. active_targets    — which target nodes currently have an agent dispatched.
2. defer_counts      — how many consecutive times each node has been DEFER'd.
3. staged_agents     — agents currently in STAGED_EXECUTE awaiting re-evaluation.

All constants are derived from two primary values in egl_config.json:
    base_margin         = 0.15  (from decision_margin section)
    golden_hour_end     = 60    (from phase_boundaries_minutes)
    timestep_duration_s = 60    (from parameters.py)

Derivation chain:
    avg_reeval_interval = 10 min  (≈ typical coordinator re-planning interval)
    defer_escalate_count = floor(golden_hour_end / avg_reeval_interval) = 6
    defer_margin_decay   = (base_margin - min_margin) / defer_escalate_count
                         = (0.15 - 0.03) / 6 = 0.02
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Set

import networkx as nx

from backend.agents.base_agent import BaseAgent

# ---------------------------------------------------------------------------
# Load derived constants from egl_config.json
# ---------------------------------------------------------------------------

_CFG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config_params", "egl_config.json"
)

def _load_fcm_config() -> Dict[str, Any]:
    try:
        with open(_CFG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}

    margin_cfg = cfg.get("decision_margin", {})
    defer_cfg  = cfg.get("defer_escalation", {})
    staged_cfg = cfg.get("staged_dispatch", {})

    return {
        "base_margin": float(
            margin_cfg.get("base_margin", {}).get("value", 0.15)
        ),
        "min_margin": float(
            margin_cfg.get("min_margin", {}).get("value", 0.03)
        ),
        "defer_escalate_count": int(
            defer_cfg.get("defer_escalate_count", {}).get("value", 6)
        ),
        "defer_margin_decay_per_tick": float(
            defer_cfg.get("defer_margin_decay_per_tick", {}).get("value", 0.02)
        ),
        "staging_fraction": float(
            staged_cfg.get("staging_fraction", {}).get("value", 0.67)
        ),
        "staging_irreversibility_threshold": float(
            staged_cfg.get("irreversibility_threshold_for_staging", {})
                      .get("value", 0.70)
        ),
    }

_FCM_CFG = _load_fcm_config()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class FleetCoordinationManager:
    """
    Coordinates fleet-level dispatch state to prevent redundancy and
    starvation.

    Anti-redundancy
    ---------------
    Maintains a set of target nodes that already have an active dispatch.
    If a second agent attempts to dispatch to the same node, the FCM
    signals a DEFER (fleet mutex).

    Anti-starvation (DEFER decay)
    -----------------------------
    Each consecutive DEFER on the same target node reduces the effective
    decision margin. After `defer_escalate_count` consecutive DEFERs,
    the FCM forces an ESCALATE — ensuring human review before a target
    is permanently abandoned.

    Staged dispatch
    ---------------
    For high-irreversibility actions (I ≥ threshold), agents move to a
    staging node (≈33% of route) and pause. After DAP re-evaluates with
    fresher data, the agent either continues or aborts. The FCM tracks
    which agents are in this staging state.
    """

    def __init__(self) -> None:
        self._active_targets: Set[str]    = set()
        self._committed_capacity: Dict[str, int] = {}
        self._defer_counts:   Dict[str, int] = {}
        self._staged_agents:  Dict[str, _StagedState] = {}

    # ------------------------------------------------------------------
    # Fleet Mutex
    # ------------------------------------------------------------------

    def check_mutex(self, target_node: str, target_pop: int = 0, agent_cap: int = 50) -> bool:
        """
        Returns True if `target_node` already has active dispatches satisfying all demand.
        Allows multi-agent dispatch if remaining unserved demand exceeds 0.
        Caller should DEFER if True.
        """
        if target_node not in self._active_targets:
            return False
        committed = self._committed_capacity.get(target_node, 0)
        if target_pop > committed:
            return False  # Still need more vehicles
        return True

    def register_dispatch(self, agent_id: str, target_node: str, agent_cap: int = 50) -> None:
        """Mark a target as actively dispatched. Called on EXECUTE/STAGED_EXECUTE."""
        self._active_targets.add(target_node)
        self._committed_capacity[target_node] = self._committed_capacity.get(target_node, 0) + agent_cap
        # Clear any DEFER count — the node is now being serviced
        self._defer_counts.pop(target_node, None)

    def release_target(self, target_node: str, agent_cap: int = 50) -> None:
        """
        Release or decrement committed capacity when an agent completes, aborts, or returns.
        Called by the simulation engine when an agent finishes its mission.
        """
        if target_node in self._committed_capacity:
            current = self._committed_capacity[target_node] - agent_cap
            if current <= 0:
                self._committed_capacity.pop(target_node, None)
                self._active_targets.discard(target_node)
            else:
                self._committed_capacity[target_node] = current
        else:
            self._active_targets.discard(target_node)

    @property
    def active_targets(self) -> Set[str]:
        return frozenset(self._active_targets)

    # ------------------------------------------------------------------
    # DEFER Decay (anti-starvation)
    # ------------------------------------------------------------------

    def get_effective_margin(self, target_node: str) -> float:
        """
        Returns the current decision margin for a target node.

        margin = max(min_margin, base_margin - decay × defer_count)

        If defer_count >= defer_escalate_count, returns -1.0 as a signal
        to the orchestrator that forced ESCALATE is required.

        Derivation (no independent constants)
        --------------------------------------
        base_margin              = 0.15  (control theory: 5% of [0, 3.0] range)
        min_margin               = 0.03  (1% of range; below this → ESCALATE anyway)
        defer_escalate_count     = 6     (golden_hour / avg_reeval = 60/10)
        defer_margin_decay/tick  = 0.02  ((0.15 - 0.03) / 6)
        """
        count = self._defer_counts.get(target_node, 0)

        if count >= _FCM_CFG["defer_escalate_count"]:
            return -1.0  # Sentinel: force ESCALATE

        decayed = (
            _FCM_CFG["base_margin"]
            - _FCM_CFG["defer_margin_decay_per_tick"] * count
        )
        return max(_FCM_CFG["min_margin"], decayed)

    def increment_defer(self, target_node: str) -> bool:
        """
        Increment the DEFER count for a target node.

        Returns True if defer_count has reached the escalation threshold
        (caller should force ESCALATE).
        """
        current = self._defer_counts.get(target_node, 0) + 1
        self._defer_counts[target_node] = current
        return current >= _FCM_CFG["defer_escalate_count"]

    def reset_defer_count(self, target_node: str) -> None:
        """Reset DEFER counter — called when node is successfully dispatched or observed."""
        self._defer_counts.pop(target_node, None)

    @property
    def defer_counts(self) -> Dict[str, int]:
        return dict(self._defer_counts)

    # ------------------------------------------------------------------
    # Staged Dispatch
    # ------------------------------------------------------------------

    def compute_staging_node(
        self,
        route: List[str],
        belief_graph: nx.Graph,
    ) -> Optional[str]:
        """
        Determine the staging node — the node at approximately
        `staging_fraction` (33%) of cumulative route distance.

        Returns None if the route is too short for staging (< 3 nodes).
        """
        if len(route) < 3:
            return None

        # Calculate cumulative distances along the route
        cumulative = [0.0]
        for i in range(len(route) - 1):
            u, v = route[i], route[i + 1]
            if belief_graph.has_edge(u, v):
                d = belief_graph.edges[u, v].get("distance", 500.0)
            else:
                d = 500.0
            cumulative.append(cumulative[-1] + d)

        total_dist = cumulative[-1]
        if total_dist <= 0:
            return None

        target_dist = total_dist * _FCM_CFG["staging_fraction"]

        # Find the node closest to the staging distance
        best_idx = 0
        best_diff = float("inf")
        for idx, cum_d in enumerate(cumulative):
            diff = abs(cum_d - target_dist)
            if diff < best_diff:
                best_diff = diff
                best_idx = idx

        # Don't stage at the very first or very last node
        best_idx = max(1, min(best_idx, len(route) - 2))
        return route[best_idx]

    def register_staged(
        self,
        agent_id:     str,
        target_node:  str,
        staging_node: str,
        full_route:   List[str],
        action_class: str = "RESCUE_DISPATCH",
    ) -> None:
        """
        Register an agent as being in STAGED_EXECUTE state.

        The agent will move to `staging_node` and pause. After
        DAP re-evaluates, the orchestrator calls either
        `complete_staged()` or `abort_staged()`.
        """
        self._staged_agents[agent_id] = _StagedState(
            agent_id=agent_id,
            target_node=target_node,
            staging_node=staging_node,
            full_route=list(full_route),
            action_class=action_class,
        )
        # The target is "soft locked" — registered as active
        self._active_targets.add(target_node)

    def get_staged_state(self, agent_id: str) -> Optional["_StagedState"]:
        """Returns the staged state for an agent, or None."""
        return self._staged_agents.get(agent_id)

    def is_agent_staged(self, agent_id: str) -> bool:
        return agent_id in self._staged_agents

    def complete_staged(self, agent_id: str) -> Optional[List[str]]:
        """
        Agent has been re-evaluated and cleared for full execution.
        Returns the remaining route from staging node to target,
        or None if agent is not staged.
        """
        state = self._staged_agents.pop(agent_id, None)
        if state is None:
            return None

        # Find index of staging node in the full route
        try:
            idx = state.full_route.index(state.staging_node)
            return state.full_route[idx + 1:]
        except ValueError:
            return state.full_route[1:]  # fallback: skip first node

    def abort_staged(self, agent_id: str) -> None:
        """
        Agent's staged dispatch has been aborted (DAP re-eval said DEFER).
        Release the target lock and clean up.
        """
        state = self._staged_agents.pop(agent_id, None)
        if state:
            self._active_targets.discard(state.target_node)

    @property
    def staged_agents(self) -> Dict[str, "_StagedState"]:
        return dict(self._staged_agents)

    # ------------------------------------------------------------------
    # Reset (called at simulation setup)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Full state reset — called when simulation is re-initialised."""
        self._active_targets.clear()
        self._committed_capacity.clear()
        self._defer_counts.clear()
        self._staged_agents.clear()

    # ------------------------------------------------------------------
    # Status (for dashboard)
    # ------------------------------------------------------------------

    def status_dict(self) -> Dict[str, Any]:
        return {
            "active_targets":     list(self._active_targets),
            "defer_counts":       dict(self._defer_counts),
            "staged_agent_count": len(self._staged_agents),
            "staged_agents":      {
                k: {
                    "target": v.target_node,
                    "staging_node": v.staging_node,
                }
                for k, v in self._staged_agents.items()
            },
        }


# ---------------------------------------------------------------------------
# Internal data class
# ---------------------------------------------------------------------------

class _StagedState:
    """Tracks an agent in STAGED_EXECUTE limbo."""
    __slots__ = ("agent_id", "target_node", "staging_node", "full_route", "action_class")

    def __init__(
        self,
        agent_id:     str,
        target_node:  str,
        staging_node: str,
        full_route:   List[str],
        action_class: str = "RESCUE_DISPATCH",
    ) -> None:
        self.agent_id     = agent_id
        self.target_node  = target_node
        self.staging_node = staging_node
        self.full_route   = full_route
        self.action_class = action_class
