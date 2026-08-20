"""
Execution Governance Layer — Mission Policy Manager (MPM)
==========================================================
Single responsibility: hold, validate, and serve policy weight
configurations. No computation. No logging.

All profiles require an authorizing_officer_id before they can be
activated on a non-default run — this enforces human accountability
for every value judgment encoded in the system.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.execution_governance.dap import MissionWeights

# ---------------------------------------------------------------------------
# Load profile defaults from egl_config.json
# ---------------------------------------------------------------------------

_CFG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config_params", "egl_config.json"
)

def _load_profiles() -> Dict[str, Dict[str, Any]]:
    try:
        with open(_CFG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("ethical_profiles", {})
    except Exception as exc:
        print(f"[EGL/MPM] Warning: could not load egl_config.json: {exc}")
        return {}

_PROFILE_DEFS = _load_profiles()

# Phase modulation lookup (golden hour boost, recovery conservatism)
_PHASE_WAIT_BOOSTS: Dict[str, float] = {
    "GOLDEN_HOUR":   1.5,
    "SUSTAINED_OPS": 1.0,
    "RECOVERY":      0.7,
}

# AEM slope cached from egl_config.json (loaded once at module level)
def _load_aem_slope() -> float:
    try:
        with open(_CFG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return float(cfg.get("access_equity", {}).get("aem_slope", {}).get("value", 0.4))
    except Exception:
        return 0.4

_AEM_SLOPE: float = _load_aem_slope()


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------

def _validate_weights(weights: Dict[str, float]) -> List[str]:
    """
    Sanity-check a custom weight profile before activation.
    Returns a list of error strings (empty = valid).
    """
    errors: List[str] = []

    c_crew   = weights.get("c_crew_lost", 0)
    c_res    = weights.get("c_resource_waste", 0)
    mu_boost = weights.get("mu_wait_boost", 1.0)

    if c_crew <= c_res:
        errors.append(
            f"c_crew_lost ({c_crew}) must be > c_resource_waste ({c_res}). "
            "Crew lives must always be valued above equipment."
        )
    if not (0.5 <= mu_boost <= 3.0):
        errors.append(
            f"mu_wait_boost ({mu_boost}) must be in [0.5, 3.0]. "
            "Values outside this range produce degenerate decision behaviour."
        )
    if c_crew <= 0:
        errors.append("c_crew_lost must be > 0.")
    if c_res <= 0:
        errors.append("c_resource_waste must be > 0.")

    return errors


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class MissionPolicyManager:
    """
    Manages policy weight profiles for the EGL.
    """

    def __init__(self, audit_manager: Any = None) -> None:
        self._active_profile_name: str = "BALANCED"
        self._pending_profile_name: Optional[str] = None  # Takes effect next cycle
        self._custom_weights: Optional[Dict[str, float]] = None
        self._audit_manager = audit_manager
        self._last_changed_at: Optional[str] = None
        self._last_changed_by: Optional[str] = None

    # ------------------------------------------------------------------
    # Public: get weights for current phase
    # ------------------------------------------------------------------

    def get_weights(self, phase: str) -> MissionWeights:
        """
        Returns the MissionWeights for the active profile, adjusted for phase.
        """
        raw = self._get_raw_weights(self._active_profile_name)

        phase_boost = _PHASE_WAIT_BOOSTS.get(phase, 1.0)

        return MissionWeights(
            c_crew_lost=raw["c_crew_lost"],
            c_resource_waste=raw["c_resource_waste"],
            c_info_wrong=1.0,       # Fixed reference (by definition)
            mu_act=1.0,             # Fixed baseline (by definition)
            mu_wait_boost=raw["mu_wait_boost"] * phase_boost,
            aem_slope=_AEM_SLOPE,
            profile_name=self._active_profile_name,
        )

    # ------------------------------------------------------------------
    # Public: switch profiles
    # ------------------------------------------------------------------

    def set_profile(
        self,
        profile_name: str,
        officer_id:   str,
        custom_weights: Optional[Dict[str, float]] = None,
    ) -> List[str]:
        """
        Queue a profile change. Change takes effect on the next planning cycle.
        """
        if not officer_id:
            return ["officer_id must not be empty — all profile changes require human authorisation."]

        if profile_name == "CUSTOM":
            if not custom_weights:
                return ["custom_weights must be provided when profile_name == 'CUSTOM'."]
            errors = _validate_weights(custom_weights)
            if errors:
                return errors
            self._custom_weights = dict(custom_weights)
        elif profile_name not in _PROFILE_DEFS and profile_name not in (
            "CREW_CONSERVATIVE", "BALANCED", "CIVILIAN_PRIORITY"
        ):
            return [f"Unknown profile: '{profile_name}'. Valid: CREW_CONSERVATIVE, BALANCED, CIVILIAN_PRIORITY, CUSTOM."]

        self._pending_profile_name = profile_name
        self._last_changed_at = datetime.now(tz=timezone.utc).isoformat()
        self._last_changed_by = officer_id

        # Write to audit log if available
        if self._audit_manager is not None:
            try:
                self._audit_manager.write_profile_change(
                    old_profile=self._active_profile_name,
                    new_profile=profile_name,
                    officer_id=officer_id,
                    timestamp_utc=self._last_changed_at,
                )
            except Exception as exc:
                print(f"[EGL/MPM] Audit write failed on profile change: {exc}")

        return []

    def commit_pending_profile(self) -> None:
        """
        Applies the pending profile at the start of a new planning cycle.
        Called by EGL orchestrator at cycle boundary.
        """
        if self._pending_profile_name is not None:
            self._active_profile_name = self._pending_profile_name
            self._pending_profile_name = None

    @property
    def active_profile_name(self) -> str:
        return self._active_profile_name

    @property
    def pending_profile_name(self) -> Optional[str]:
        return self._pending_profile_name

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_raw_weights(self, profile_name: str) -> Dict[str, float]:
        """Fetch raw weight values for a named profile."""
        cfg_profile = _PROFILE_DEFS.get(profile_name, {})
        if cfg_profile:
            return {
                "c_crew_lost":      float(cfg_profile.get("c_crew_lost",      3.0)),
                "c_resource_waste": float(cfg_profile.get("c_resource_waste", 0.5)),
                "mu_wait_boost":    float(cfg_profile.get("mu_wait_boost",    1.0)),
            }

        # Fallbacks
        fallbacks: Dict[str, Dict[str, float]] = {
            "CREW_CONSERVATIVE": {"c_crew_lost": 5.0, "c_resource_waste": 0.5, "mu_wait_boost": 0.8},
            "BALANCED":          {"c_crew_lost": 3.0, "c_resource_waste": 0.5, "mu_wait_boost": 1.0},
            "CIVILIAN_PRIORITY": {"c_crew_lost": 1.5, "c_resource_waste": 0.5, "mu_wait_boost": 1.8},
        }
        if profile_name == "CUSTOM" and self._custom_weights:
            return dict(self._custom_weights)

        return fallbacks.get(profile_name, fallbacks["BALANCED"])

    def status_dict(self) -> Dict[str, Any]:
        """Returns current MPM status for the dashboard / API."""
        return {
            "active_profile":  self._active_profile_name,
            "pending_profile": self._pending_profile_name,
            "last_changed_by": self._last_changed_by,
            "last_changed_at": self._last_changed_at,
        }
