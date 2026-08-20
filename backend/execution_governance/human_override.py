"""
Execution Governance Layer — Human Override Manager (HOM)
==========================================================
Single responsibility: manage the Time-Boxed Human Override (TBHO)
protocol for ESCALATE decisions.

When DAP returns ESCALATE, the HOM:
1. Creates an OverrideRequest with a phase-appropriate countdown timer.
2. Emits the request payload (consumed by the frontend via SSE).
3. Awaits a human response: APPROVE_EXECUTE or CONFIRM_DEFER.
4. If no response arrives before timeout, applies a safe default
   based on the action's irreversibility.

The HOM does NOT compute adequacy dimensions, regret, or anything
related to DAP math. It is a pure state machine for the human-in-the-loop
protocol.

Timeout defaults (from egl_config.json, Category C — domain expert required):
    I < 0.50 → EXECUTE  (low-I actions are recoverable)
    I ≥ 0.50 → DEFER    (high-I actions risk irreversible harm)

Timeout durations (from egl_config.json, Category C):
    GOLDEN_HOUR:    30s  (every second matters — Cowley 1971)
    SUSTAINED_OPS:  60s  (standard deliberate window)
    RECOVERY:       90s  (fatigue → slower cognition → more time)
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from backend.execution_governance.dap import DAPResult

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CFG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config_params", "egl_config.json"
)

def _load_hom_config() -> Dict[str, Any]:
    try:
        with open(_CFG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("human_override", {})
    except Exception:
        return {}

_HOM_CFG = _load_hom_config()

# Phase → timeout in seconds
_TIMEOUT_BY_PHASE: Dict[str, int] = {
    "GOLDEN_HOUR":   int(_HOM_CFG.get("tbho_timeout_s", {}).get("GOLDEN_HOUR",   {}).get("value", 30)),
    "SUSTAINED_OPS": int(_HOM_CFG.get("tbho_timeout_s", {}).get("SUSTAINED_OPS", {}).get("value", 60)),
    "RECOVERY":      int(_HOM_CFG.get("tbho_timeout_s", {}).get("RECOVERY",      {}).get("value", 90)),
}

_HIGH_I_THRESHOLD: float = float(_HOM_CFG.get("high_irreversibility_threshold", 0.50))
_TIMEOUT_DEFAULT_LOW_I:  str = _HOM_CFG.get("timeout_default_low_irreversibility",  "EXECUTE")
_TIMEOUT_DEFAULT_HIGH_I: str = _HOM_CFG.get("timeout_default_high_irreversibility", "DEFER")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OverrideRequest:
    """
    Represents an active TBHO request sent to the EOC dashboard.
    The frontend renders this as a countdown card with APPROVE / DEFER buttons.
    """
    request_id:       str
    agent_id:         str
    target_node:      str
    phase:            str
    timeout_s:        int
    irreversibility:  float
    timeout_default:  str      # What happens if no response: "EXECUTE" or "DEFER"
    created_at:       str      # UTC ISO timestamp
    regret_act:       float
    regret_wait:      float
    epsilon:          float
    sigma:            float
    kappa:            float
    rho:              float
    rationale:        str      # Plain-English from XE

    # State
    resolved:         bool = False
    resolution:       Optional[str] = None   # "APPROVE_EXECUTE" | "CONFIRM_DEFER" | "TIMEOUT"
    resolved_by:      Optional[str] = None   # officer_id or "SYSTEM_TIMEOUT"
    resolved_at:      Optional[str] = None
    created_sim_time: float = 0.0

    def to_sse_payload(self) -> Dict[str, Any]:
        """
        JSON payload for Server-Sent Events to the frontend.
        The frontend displays this as an interactive ESCALATE card.
        """
        return {
            "type":            "DAP_ESCALATE",
            "request_id":     self.request_id,
            "agent_id":       self.agent_id,
            "target_node":    self.target_node,
            "phase":          self.phase,
            "timeout_s":      self.timeout_s,
            "timeout_default": self.timeout_default,
            "irreversibility": self.irreversibility,
            "regret_act":     round(self.regret_act, 3),
            "regret_wait":    round(self.regret_wait, 3),
            "epsilon":        round(self.epsilon, 3),
            "sigma":          round(self.sigma, 3),
            "kappa":          round(self.kappa, 3),
            "rho":            round(self.rho, 3),
            "rationale":      self.rationale,
            "created_at":     self.created_at,
        }


@dataclass
class OverrideResult:
    """Result of a resolved TBHO request."""
    request_id:   str
    resolution:   str      # "APPROVE_EXECUTE" | "CONFIRM_DEFER" | "TIMEOUT"
    resolved_by:  str      # officer_id or "SYSTEM_TIMEOUT"
    resolved_at:  str      # UTC ISO
    final_outcome: str     # The dispatch outcome to apply: "EXECUTE" or "DEFER"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class HumanOverrideManager:
    """
    Manages the TBHO protocol lifecycle.

    Lifecycle per ESCALATE event:
    1. `request_override()` → creates OverrideRequest, stores it, returns SSE payload.
    2. Frontend receives SSE payload and shows countdown + buttons.
    3a. Officer clicks APPROVE → `receive_response("APPROVE_EXECUTE", officer_id)`.
    3b. Officer clicks DEFER   → `receive_response("CONFIRM_DEFER", officer_id)`.
    3c. Timeout expires         → `apply_timeout_default(request_id)`.
    4. `get_result(request_id)` → returns OverrideResult with final outcome.
    """

    def __init__(self) -> None:
        self._pending: Dict[str, OverrideRequest] = {}   # request_id → OverrideRequest
        self.tbho_created_count: int = 0
        self.tbho_timeout_count: int = 0

    # ------------------------------------------------------------------
    # Step 1: Create override request
    # ------------------------------------------------------------------

    def request_override(
        self,
        dap_result:  DAPResult,
        agent_id:    str,
        target_node: str,
        rationale:   str = "",
        sim_time:    float = 0.0,
    ) -> OverrideRequest:
        """
        Create a TBHO request from an ESCALATE DAPResult.

        Returns the OverrideRequest (caller should emit `.to_sse_payload()`
        through the SSE event stream).
        """
        timeout_s = _TIMEOUT_BY_PHASE.get(dap_result.phase, 60)

        # Regret-minimizing fallback for high-irreversibility actions:
        # Default to EXECUTE if wait regret exceeds act regret, otherwise follow EGL defaults.
        if dap_result.irreversibility < _HIGH_I_THRESHOLD:
            timeout_default = _TIMEOUT_DEFAULT_LOW_I
        else:
            if dap_result.regret_wait > dap_result.regret_act:
                timeout_default = "EXECUTE"
            else:
                timeout_default = _TIMEOUT_DEFAULT_HIGH_I



        req = OverrideRequest(
            request_id=str(uuid.uuid4()),
            agent_id=agent_id,
            target_node=target_node,
            phase=dap_result.phase,
            timeout_s=timeout_s,
            irreversibility=dap_result.irreversibility,
            timeout_default=timeout_default,
            created_at=datetime.now(tz=timezone.utc).isoformat(),
            created_sim_time=sim_time,
            regret_act=dap_result.regret_act,
            regret_wait=dap_result.regret_wait,
            epsilon=dap_result.epsilon,
            sigma=dap_result.sigma,
            kappa=dap_result.kappa,
            rho=dap_result.rho,
            rationale=rationale,
        )
        self._pending[req.request_id] = req
        self.tbho_created_count += 1
        return req

    # ------------------------------------------------------------------
    # Step 3a/3b: Receive human response
    # ------------------------------------------------------------------

    def receive_response(
        self,
        request_id: str,
        decision:   Literal["APPROVE_EXECUTE", "CONFIRM_DEFER"],
        officer_id: str,
    ) -> Optional[OverrideResult]:
        """
        Process a human response to a pending TBHO request.

        Returns OverrideResult if the request was found and not already resolved.
        Returns None if request_id is unknown or already resolved.
        """
        req = self._pending.get(request_id)
        if req is None or req.resolved:
            return None

        now = datetime.now(tz=timezone.utc).isoformat()
        req.resolved = True
        req.resolution = decision
        req.resolved_by = officer_id
        req.resolved_at = now

        final = "EXECUTE" if decision == "APPROVE_EXECUTE" else "DEFER"

        return OverrideResult(
            request_id=request_id,
            resolution=decision,
            resolved_by=officer_id,
            resolved_at=now,
            final_outcome=final,
        )

    # ------------------------------------------------------------------
    # Step 3c: Timeout
    # ------------------------------------------------------------------

    def apply_timeout_default(self, request_id: str) -> Optional[OverrideResult]:
        """
        Apply the safe default when timeout expires without human input.

        I <  0.50 → EXECUTE  (scout-class actions: error is recoverable)
        I ≥  0.50 → DEFER    (rescue/evacuation: irreversible harm avoided)
        """
        req = self._pending.get(request_id)
        if req is None or req.resolved:
            return None

        now = datetime.now(tz=timezone.utc).isoformat()
        req.resolved = True
        req.resolution = "TIMEOUT"
        req.resolved_by = "SYSTEM_TIMEOUT"
        req.resolved_at = now
        self.tbho_timeout_count += 1

        return OverrideResult(
            request_id=request_id,
            resolution="TIMEOUT",
            resolved_by="SYSTEM_TIMEOUT",
            resolved_at=now,
            final_outcome=req.timeout_default,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_pending_requests(self) -> List[OverrideRequest]:
        """Returns all unresolved TBHO requests (for dashboard polling)."""
        return [r for r in self._pending.values() if not r.resolved]

    def get_result(self, request_id: str) -> Optional[OverrideResult]:
        """
        Check if a TBHO request has been resolved (by human or timeout).
        Returns None if the request is still pending.
        """
        req = self._pending.get(request_id)
        if req is None or not req.resolved:
            return None
        return OverrideResult(
            request_id=req.request_id,
            resolution=req.resolution,
            resolved_by=req.resolved_by,
            resolved_at=req.resolved_at,
            final_outcome="EXECUTE" if req.resolution == "APPROVE_EXECUTE" else "DEFER",
        )

    def has_pending(self) -> bool:
        return any(not r.resolved for r in self._pending.values())

    def get_request(self, request_id: str) -> Optional[OverrideRequest]:
        """Returns the raw OverrideRequest by ID, or None if not found."""
        return self._pending.get(request_id)

    # ------------------------------------------------------------------
    # Override rate monitoring (operator trust calibration)
    # ------------------------------------------------------------------

    def get_override_rate(self) -> Dict[str, Any]:
        """
        Computes the override rate for the current session.

        If > 40% of ESCALATE decisions are overridden (human disagrees with
        DAP), it suggests the ethical profile or config may be miscalibrated.
        """
        resolved = [r for r in self._pending.values() if r.resolved]
        if not resolved:
            return {"total": 0, "overrides": 0, "rate": 0.0, "alert": False}

        overrides = sum(1 for r in resolved if r.resolution == "APPROVE_EXECUTE")
        total = len(resolved)
        rate = overrides / total

        return {
            "total":     total,
            "overrides": overrides,
            "rate":      round(rate, 3),
            "alert":     rate > 0.40,
            "message":   (
                "High override rate detected — consider adjusting Ethical Profile "
                "or reviewing EGL configuration."
            ) if rate > 0.40 else "",
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Full state reset — called when simulation is re-initialised."""
        self._pending.clear()

    def cleanup_resolved(self, keep_last_n: int = 100) -> None:
        """
        Prune old resolved requests to prevent memory growth.
        Keeps the most recent `keep_last_n` resolved entries.
        """
        resolved = sorted(
            [(rid, r) for rid, r in self._pending.items() if r.resolved],
            key=lambda x: x[1].resolved_at or "",
            reverse=True,
        )
        if len(resolved) > keep_last_n:
            for rid, _ in resolved[keep_last_n:]:
                del self._pending[rid]
