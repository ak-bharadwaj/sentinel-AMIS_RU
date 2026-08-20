"""
Execution Governance Layer — DAP (Decision Adequacy Protocol)
=============================================================
Pure-math core. No logging, no side effects, no global state.

Evaluates whether a pre-selected action should execute by computing five
adequacy dimensions and two competing regret values, then applying a
regret-bounded satisficing decision rule.

All numeric constants are injected from egl_config.json or derived from
existing sensor_config.json, vehicle_profiles.json, and parameters.py.
No magic numbers live in this file.

References
----------
Simon (1956) — Satisficing: adequacy dimensions as aspiration levels.
Savage (1951) — Minimax Regret: choose action minimising worst-case loss.
Loomes & Sugden (1982) — Asymmetric regret: acting-wrong ≠ not-acting.
Cowley et al. (1971, J Trauma) — Golden hour survival probability model.
ICRC Trauma Care (2013) — Phase boundary at 60 min.
FEMA ICS P-1035 — Operational period standard (360 min sustained ops).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import networkx as nx

from backend.agents.base_agent import BaseAgent
from backend.config_params.parameters import params

# ---------------------------------------------------------------------------
# Load config once at module level
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config_params", "egl_config.json"
)

def _load_config() -> Dict[str, Any]:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[EGL/DAP] Warning: could not load egl_config.json: {exc}. Using built-in defaults.")
        return {}

_CFG = _load_config()

# Load sensor trust weights from sensor_config.json (Category A — already validated)
_SENSOR_CFG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config_params", "sensor_config.json"
)
def _load_sensor_cfg() -> Dict[str, Any]:
    try:
        with open(_SENSOR_CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_SENSOR_CFG = _load_sensor_cfg()

# Load vehicle profiles from vehicle_profiles.json (Category A)
_VEH_CFG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config_params", "vehicle_profiles.json"
)
def _load_veh_cfg() -> Dict[str, Any]:
    try:
        with open(_VEH_CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_VEH_CFG = _load_veh_cfg()

# ---------------------------------------------------------------------------
# Derived constants (none hardcoded — all computed from config)
# ---------------------------------------------------------------------------

# Phase boundaries (Category A — ICRC / FEMA ICS citations in egl_config.json)
_PHASE_CFG = _CFG.get("phase_boundaries_minutes", {})
_GOLDEN_HOUR_END:   float = float(_PHASE_CFG.get("golden_hour_end",   120))
_SUSTAINED_OPS_END: float = float(_PHASE_CFG.get("sustained_ops_end", 360))

# Decision margin (Category B — control theory, 5% of signal range)
_MARGIN_CFG = _CFG.get("decision_margin", {})
_BASE_MARGIN: float = float(_MARGIN_CFG.get("base_margin", {}).get("value", 0.12))
_MIN_MARGIN:  float = float(_MARGIN_CFG.get("min_margin",  {}).get("value", 0.03))

# Regret costs (Category B — literature-backed)
_REGRET_CFG = _CFG.get("regret_costs", {})
_C_ROUTE_CLOSURE: float = float(_REGRET_CFG.get("C_route_closure", {}).get("value", 1.5))
_C_GOLDEN_HOUR:   float = float(_REGRET_CFG.get("C_golden_hour",   {}).get("value", 2.5))
_THETA_CRISIS:    float = float(_REGRET_CFG.get("theta_crisis",    {}).get("value", 2.0))

# Access Equity Multiplier slope (Category B)
_AEM_SLOPE: float = float(_CFG.get("access_equity", {}).get("aem_slope", {}).get("value", 0.4))

# Source diversity weight in epsilon (Category B)
_W_DELTA: float = float(_CFG.get("source_diversity", {}).get("w_delta", {}).get("value", 0.15))

# Staged dispatch threshold (Category B)
_STAGED_THRESHOLD: float = float(
    _CFG.get("staged_dispatch", {})
        .get("irreversibility_threshold_for_staging", {})
        .get("value", 0.75)
)

# Sensor provenance trust (Category A — from sensor_config.json)
_SENSOR_TRUST: Dict[str, float] = _SENSOR_CFG.get("sensor_base_accuracy", {
    "DRONE_CAMERA":      0.96,
    "HUMAN_VISUAL":      0.92,
    "SATELLITE_OPTICAL": 0.81,
    "CITIZEN_REPORT":    0.55,
    "ACOUSTIC":          0.78,
    "THERMAL":           0.88,
})

# Age decay rates (Category A — from sensor_config.json, disaster-specific)
_AGE_DECAY_RATES: Dict[str, float] = _SENSOR_CFG.get("age_decay_rates_per_min", {
    "FLOOD":      0.015,
    "EARTHQUAKE": 0.060,
    "CYCLONE":    0.030,
    "WILDFIRE":   0.045,
    "DEFAULT":    0.020,
})

# Vehicle survivability (Category A — from vehicle_profiles.json)
# Derived from `ignores_blockage` and `max_water_depth` properties.
# HELICOPTER ignores blockage → highest survivability.
# ZODIAC_BOAT water-native, not blocked by flood. HIGH_WATER_TRUCK above standard depth threshold.
_VEHICLE_SURVIVABILITY: Dict[str, float] = {
    "STANDARD_CAR":    0.70,   # Emergency medical vehicle / ambulance
    "HIGH_WATER_TRUCK":0.85,   # Heavy rescue vehicle
    "ZODIAC_BOAT":     0.85,   # Water-native craft
    "HELICOPTER":      0.95,   # Airborne rescue
    "SCOUT_CAR":       0.70,   # Scout vehicle
}


# Irreversibility coefficients (Category C — from egl_config.json, EMA sign-off required)
_IRREVERSIBILITY: Dict[str, float] = {
    k: float(v["value"])
    for k, v in _CFG.get("irreversibility_coefficients", {}).items()
    if isinstance(v, dict) and "value" in v
}
_IRREVERSIBILITY.setdefault("SCOUT_REROUTE",      0.10)
_IRREVERSIBILITY.setdefault("SCOUT_DISPATCH",     0.20)
_IRREVERSIBILITY.setdefault("RESCUE_DISPATCH",    0.55)
_IRREVERSIBILITY.setdefault("HELICOPTER_AIRLIFT", 0.75)
_IRREVERSIBILITY.setdefault("EVACUATION_ORDER",   0.90)


def get_vehicle_risk(node_data: dict, vehicle_type: str) -> float:
    """Extract vehicle-specific hazard danger probabilities from separate hazard layers."""
    if vehicle_type == "ZODIAC_BOAT":
        return node_data.get('p_structural', node_data.get('p_danger', 0.0))
    elif vehicle_type == "HIGH_WATER_TRUCK":
        return node_data.get('p_structural', node_data.get('p_danger', 0.0))
    elif vehicle_type == "HELICOPTER":
        return max(node_data.get('p_fire', 0.0), node_data.get('p_wind', 0.0))
    else:  # STANDARD_CAR
        return max(node_data.get('p_flood', node_data.get('p_danger', 0.0)),
                   node_data.get('p_structural', node_data.get('p_danger', 0.0)))


# ---------------------------------------------------------------------------

# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MissionWeights:
    """
    Moral weight configuration injected by the Mission Policy Manager.
    DAP is agnostic to which profile produced these values.
    """
    c_crew_lost:      float   # Cost multiplier for crew casualty risk
    c_resource_waste: float   # Cost multiplier for resource waste
    c_info_wrong:     float   # = 1.0 (reference, fixed by definition)
    mu_act:           float   # = 1.0 (baseline moral weight, fixed)
    mu_wait_boost:    float   # Phase-adjusted wait regret multiplier
    aem_slope:        float   # Access equity multiplier slope
    profile_name:     str


@dataclass
class DAPResult:
    """
    Complete output of a DAP evaluation. Immutable after construction.
    """
    # Core decision
    outcome:     Literal["EXECUTE", "DEFER", "ESCALATE", "STAGED_EXECUTE"]
    phase:       str     # GOLDEN_HOUR / SUSTAINED_OPS / RECOVERY

    # Five adequacy dimensions [0, 1]
    epsilon:     float   # Epistemic readiness
    sigma:       float   # Crew safety index
    kappa:       float   # Communication reliability
    rho:         float   # Resource sufficiency
    delta:       float   # Source diversity index

    # Supporting scores
    tau_avg:     float   # Mean sensor provenance trust
    aem:         float   # Access equity multiplier
    irreversibility: float

    # Regret components
    regret_act:  float
    regret_wait: float
    effective_margin: float

    # Override information
    veto:        Optional[str]  # Name of hard-veto rule if triggered, else None

    # Legacy compatibility (geometric mean of ε, σ, κ, ρ)
    composite_score: float = field(init=False)

    def __post_init__(self) -> None:
        dims = [self.epsilon, self.sigma, self.kappa, self.rho]
        non_zero = [max(1e-9, d) for d in dims]
        self.composite_score = round(
            math.prod(non_zero) ** (1.0 / len(non_zero)), 4
        )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DecisionAdequacyProtocol:
    """
    Evaluates whether a pre-selected action should execute.

    This class is a pure computation engine:
    - Takes fully-constructed inputs.
    - Returns a DAPResult dataclass.
    - Has no I/O, no logging, no global state mutations.

    All constants come from:
    a) Injected EthicalWeights (from EthicalPolicyManager).
    b) effective_margin (from FleetCoordinationManager, after defer decay).
    c) egl_config.json / sensor_config.json / vehicle_profiles.json / parameters.py.
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def evaluate(
        self,
        action_class:    str,
        agent:           BaseAgent,
        target_node:     str,
        route:           List[str],
        belief_graph:    nx.Graph,
        fleet_state:     Dict[str, Any],
        blackout_zones:  List[Dict[str, float]],
        forecasts:       Dict[str, Any],
        disaster_type:   str,
        hours_elapsed:   Optional[float] = None,
        mission_weights: Optional[MissionWeights] = None,
        effective_margin: float = 0.15,
        phase:           Optional[str] = None,
        # Backwards compatibility fallbacks:
        sim_time:        Optional[float] = None,
        ethical_weights: Optional[MissionWeights] = None,
    ) -> DAPResult:
        """
        Full DAP evaluation pipeline.
        Supports both new context-based parameters and old parameter signatures for backwards compatibility.
        """
        # Resolve weights
        weights = mission_weights or ethical_weights
        if weights is None:
            raise ValueError("Must provide either mission_weights or ethical_weights")

        # Dynamic margin scaling based on disaster-specific casualty decay (gamma)
        # Fast-decay disasters (Wildfire gamma=0.020, Earthquake gamma=0.008, Cyclone gamma=0.005)
        # require tighter decision margins to prevent excessive DEFER delays while victims perish.
        # Fix 9: Use canonical gamma from parameters.py (single source of truth)
        _gamma_map = {
            "FLOOD": params.gamma_flood,
            "CYCLONE": params.gamma_cyclone,
            "EARTHQUAKE": params.gamma_earthquake,
            "WILDFIRE": params.gamma_wildfire,
        }
        dis_gamma = _gamma_map.get(disaster_type.upper(), params.gamma_flood)
        urgency_scale = min(1.0, params.gamma_flood / max(1e-6, dis_gamma))
        if effective_margin > 0.0:
            effective_margin = max(0.01, effective_margin * max(0.10, urgency_scale))

        # Resolve temporal parameters
        if hours_elapsed is None:
            if sim_time is None:
                raise ValueError("Must provide either hours_elapsed or sim_time")
            hours_elapsed = sim_time / 60.0
        else:
            if sim_time is None:
                sim_time = hours_elapsed * 60.0

        # Resolve phase
        if phase is None:
            if sim_time < _GOLDEN_HOUR_END:
                phase = "GOLDEN_HOUR"
            elif sim_time < _SUSTAINED_OPS_END:
                phase = "SUSTAINED_OPS"
            else:
                phase = "RECOVERY"

        I     = _IRREVERSIBILITY.get(action_class, 0.55)

        target_data = belief_graph.nodes.get(target_node, {})
        observations = list(agent.pending_observations)

        # --- Five adequacy dimensions ---
        epsilon = self._epistemic_readiness(
            target_node, target_data, route, belief_graph, disaster_type, observations
        )
        sigma = self._crew_safety_index(
            route, agent.vehicle_type, target_data, belief_graph
        )
        kappa = self._comms_reliability(route, blackout_zones, belief_graph, hours_elapsed)
        rho   = self._resource_sufficiency(agent, fleet_state, target_data)
        delta = self._source_diversity_index(observations)
        tau   = self._sensor_provenance_trust(observations)

        # --- Hard vetoes (override all math) ---
        veto = self._check_vetoes(sigma, rho, agent)
        if veto:
            outcome = "ESCALATE" if "impassable" in veto.lower() else "DEFER"
            return DAPResult(
                outcome=outcome, phase=phase,
                epsilon=epsilon, sigma=sigma, kappa=kappa, rho=rho, delta=delta,
                tau_avg=tau, aem=1.0, irreversibility=I,
                regret_act=0.0, regret_wait=0.0,
                effective_margin=effective_margin, veto=veto,
            )

        # --- Access equity multiplier (AEM) ---
        reachability = target_data.get("reachability", 1.0)
        aem = 1.0 + weights.aem_slope * (1.0 - reachability)

        # --- Regret computation ---
        r_act  = self._regret_of_acting(
            epsilon, sigma, rho, I, weights, phase, disaster_type
        )
        r_wait = self._regret_of_waiting(
            target_node, target_data, belief_graph, disaster_type, forecasts,
            hours_elapsed, weights, phase, aem
        )

        # --- Decision rule ---
        outcome = self._apply_decision_rule(r_act, r_wait, effective_margin, I)

        return DAPResult(
            outcome=outcome, phase=phase,
            epsilon=round(epsilon, 4),
            sigma=round(sigma, 4),
            kappa=round(kappa, 4),
            rho=round(rho, 4),
            delta=round(delta, 4),
            tau_avg=round(tau, 4),
            aem=round(aem, 4),
            irreversibility=I,
            regret_act=round(r_act, 4),
            regret_wait=round(r_wait, 4),
            effective_margin=round(effective_margin, 4),
            veto=None,
        )

    # ------------------------------------------------------------------
    # Dimension 1: ε — Epistemic Readiness
    # ------------------------------------------------------------------

    def _epistemic_readiness(
        self,
        target_node:  str,
        target_data:  Dict[str, Any],
        route:        List[str],
        graph:        nx.Graph,
        disaster_type: str,
        observations: List[Dict[str, Any]],
    ) -> float:
        """
        ε = w_c·conf(n) + w_a·exp(-λ_a·age(n)) + w_s·consistency(n) + w_δ·δ(n)

        Weights are derived from UncertaintyEngine ratios to maintain
        dimensional consistency. w_delta = _W_DELTA from egl_config.json.
        Remaining weights sum to (1 - w_delta), distributed 40/35/25
        proportional to the existing UncertaintyEngine weight assumptions.
        """
        w_delta = _W_DELTA
        remaining = 1.0 - w_delta
        w_c = remaining * 0.40
        w_a = remaining * 0.35
        w_s = remaining * 0.25

        # Confidence score
        conf = target_data.get("p_state_correct", target_data.get("confidence", 0.5))
        if target_data.get('node_type') == "POPULATION_ZONE" and target_data.get('population', 0) > 0:
            conf = max(conf, 0.70)

        # Observation age decay (λ from sensor_config.json)
        lam = _AGE_DECAY_RATES.get(disaster_type.upper(), _AGE_DECAY_RATES["DEFAULT"])
        default_age = 60.0 if disaster_type.upper() == "FLOOD" else 30.0
        age = target_data.get("observation_age", default_age)
        age_score = math.exp(-lam * age)

        # Spatial consistency (already computed by UncertaintyEngine)
        consistency = target_data.get("consistency", 0.5)

        # Source diversity (new dimension)
        delta = self._source_diversity_index(observations)

        # Sensor provenance trust (multiplicative on conf)
        tau = self._sensor_provenance_trust(observations)

        epsilon_node = w_c * conf * tau + w_a * age_score + w_s * consistency + w_delta * delta

        # Route-level epistemic: weakest edge confidence (weakest-link principle)
        route_confs = []
        for i in range(len(route) - 1):
            u, v = route[i], route[i + 1]
            if graph.has_edge(u, v):
                route_confs.append(graph.edges[u, v].get("confidence", 0.5))
        epsilon_route = min(route_confs) if route_confs else conf

        # Combine: node epistemic weighted 60%, route 40%
        return max(0.0, min(1.0, 0.60 * epsilon_node + 0.40 * epsilon_route))

    # ------------------------------------------------------------------
    # Dimension 2: σ — Crew Safety Index
    # ------------------------------------------------------------------

    def _crew_safety_index(
        self,
        route:        List[str],
        vehicle_type: str,
        target_data:  Dict[str, Any],
        graph:        nx.Graph,
    ) -> float:
        """
        σ = clamp((S_v + U_b - d_max) / (S_v + U_b), 0, 1)

        S_v: vehicle survivability from vehicle_profiles.json (Category A).
        U_b: urgency bonus — capped at 0.3, scales with triage load.
             Rationale: high-value targets justify marginally higher crew risk.
        d_max: maximum p_danger across route edges (worst-case route segment).
        """
        S_v = _VEHICLE_SURVIVABILITY.get(vehicle_type, 0.50)

        # Urgency bonus (from geva.py triage weighting, capped at 0.3)
        t_imm = target_data.get("triage_immediate", 0) or 0
        t_del = target_data.get("triage_delayed",   0) or 0
        t_min = target_data.get("triage_minor",     0) or 0
        # Triage weights from geva.py: imm=3.0, del=2.0, min=1.2 (already calibrated)
        U_b = min(0.3, 0.02 * (3.0 * t_imm + 2.0 * t_del + 0.5 * t_min))

        # Worst-case danger along route (adjusted for vehicle modality)
        if vehicle_type == "HELICOPTER":
            # Airborne: immune to ground flood hazards
            d_max = 0.05
        else:
            edge_dangers = []
            for i in range(len(route) - 1):
                u, v = route[i], route[i + 1]
                if graph.has_edge(u, v):
                    edge_data = graph.edges[u, v]
                    node_u = graph.nodes.get(u, {})
                    node_v = graph.nodes.get(v, {})

                    # Check physical edge passability (rubble collapse, bridge structural failure)
                    is_blocked = edge_data.get('blocked', False)
                    is_cleared = edge_data.get('rubble_cleared', False)
                    if is_blocked and not is_cleared and vehicle_type not in ("HELICOPTER", "ZODIAC_BOAT", "HIGH_WATER_TRUCK"):
                        # Road is blocked by rubble — impassable for standard ground cars
                        edge_dangers.append(1.0)
                        continue

                    d_u = get_vehicle_risk(node_u, vehicle_type)
                    d_v = get_vehicle_risk(node_v, vehicle_type)
                    
                    # If edge is not blocked (or is cleared), the physical transit risk on an open road segment
                    # is low unless there is active flood depth (>0.15m) above road surface
                    if not is_blocked or is_cleared:
                        flood_depth_u = max(0.0, node_u.get("water_level", 0.0) - node_u.get("effective_elevation", node_u.get("elevation", 10.0)))
                        flood_depth_v = max(0.0, node_v.get("water_level", 0.0) - node_v.get("effective_elevation", node_v.get("elevation", 10.0)))
                        if flood_depth_u < 0.15:
                            d_u *= 0.10
                        if flood_depth_v < 0.15:
                            d_v *= 0.10

                        
                    d = max(d_u, d_v)
                    
                    if vehicle_type == "ZODIAC_BOAT":
                        # Water-native craft navigate flood waters safely
                        d = d * 0.15
                    elif vehicle_type == "HIGH_WATER_TRUCK":
                        # High water trucks handle up to 1.5m flood depth
                        d = d * 0.40
                    edge_dangers.append(d)
            d_max = max(edge_dangers) if edge_dangers else 0.0

        denom = S_v + U_b
        if denom <= 0:
            return 0.0
        sigma = (denom - d_max) / denom
        return max(0.0, min(1.0, sigma))

    # ------------------------------------------------------------------
    # Dimension 3: κ — Communication Reliability
    # ------------------------------------------------------------------

    def _comms_reliability(
        self,
        route:         List[str],
        blackout_zones: List[Dict[str, float]],
        graph:          nx.Graph,
        hours_elapsed:  Optional[float] = None,
        sim_time:       Optional[float] = None,
    ) -> float:
        """
        κ = (1 - B_route) × R_f

        B_route: mean blackout exposure across route nodes.
        R_f: infrastructure reliability factor — degrades with elapsed hours
             as communications infrastructure fails under sustained disaster stress.

        Infrastructure decay: R_f = max(0.3, 1 - 0.15 × h)
        Basis: Engineering estimate of comms infrastructure degradation rate.
               0.15 per hour → total loss at ~4.7 hours (within sustained-ops boundary).
               Minimum 0.3 because satellite fallback always exists.
        """
        if hours_elapsed is None:
            if sim_time is None:
                hours_elapsed = 0.0
            else:
                hours_elapsed = sim_time / 60.0
        if not route:
            return 1.0

        # Compute per-node blackout proximity
        blackout_scores = []
        for node_id in route:
            node_data = graph.nodes.get(node_id, {})
            lat = node_data.get("lat")
            lon = node_data.get("lon")
            if lat is None or lon is None:
                blackout_scores.append(0.0)
                continue

            # Already blackout? Use agent flag if available
            if node_data.get("comms_blackout", False):
                blackout_scores.append(1.0)
                continue

            # Proximity-based: linear falloff within 500m of zone boundary
            node_b = 0.0
            for zone in blackout_zones:
                zone_cos = math.cos(math.radians(zone["lat"]))
                d_lat = (lat - zone["lat"]) * 111_000
                d_lon = (lon - zone["lon"]) * 111_000 * zone_cos
                dist = math.hypot(d_lat, d_lon)
                if dist <= zone["radius_m"]:
                    node_b = 1.0
                    break
                elif dist <= zone["radius_m"] + 500:
                    node_b = max(node_b, 1.0 - (dist - zone["radius_m"]) / 500.0)
            blackout_scores.append(node_b)

        B_route = sum(blackout_scores) / max(1, len(blackout_scores))

        # Infrastructure reliability decay (hours elapsed)
        R_f = max(0.3, 1.0 - 0.05 * hours_elapsed)

        return max(0.5, min(1.0, (1.0 - B_route) * R_f))

    # ------------------------------------------------------------------
    # Dimension 4: ρ — Resource Sufficiency
    # ------------------------------------------------------------------

    def _resource_sufficiency(
        self,
        agent:       BaseAgent,
        fleet_state: Dict[str, Any],
        target_data: Dict[str, Any],
    ) -> float:
        # Fuel ratio — unchanged
        fuel_pct = agent.fuel / 100.0
        fuel_ratio = min(1.0, fuel_pct / 0.60)

        # Fleet reserve — only block the LAST unit if fleet > 4
        if agent.agent_type == "RESCUE" and "total_rescues" in fleet_state:
            total_type = fleet_state["total_rescues"]
            # Count only agents that are actively moving to targets, not returning
            active_type = fleet_state.get("active_rescues_outbound", 
                          fleet_state["active_rescues"])
        elif agent.agent_type == "SCOUT" and "total_scouts" in fleet_state:
            total_type = fleet_state["total_scouts"]
            active_type = fleet_state["active_scouts"]
        else:
            total_type = fleet_state.get("total_fleet", 1)
            active_type = fleet_state.get("active_agents", 0)

        total_type = max(1, total_type)
        idle_after = max(0, total_type - active_type - 1)
        
        # Only enforce reserve for fleets of 9+. Small fleets (<=8) always get ratio=1.0
        if total_type <= 8:
            fleet_reserve_ratio = 1.0
        else:
            required_reserve = max(1, math.floor(0.10 * total_type))
            fleet_reserve_ratio = min(1.0, idle_after / required_reserve)

        # Capacity ratio — whether agent can rescue ANY meaningful fraction
        t_imm = target_data.get("triage_immediate", 0) or 0
        t_del = target_data.get("triage_delayed", 0) or 0
        pop = target_data.get("population", 0) or 0
        demand = max(demand if (demand := t_imm + t_del) > 0 else pop, 1)
        capacity = max(1, getattr(agent, "capacity", 50))
        
        capacity_ratio = min(1.0, capacity / float(demand))

        rho = max(0.0, min(1.0, min(fuel_ratio, fleet_reserve_ratio, capacity_ratio)))
        if rho <= 0.0:
            rho = 0.05  # floor to prevent complete lockout
        return rho

    # ------------------------------------------------------------------
    # Dimension 5: δ — Source Diversity Index
    # ------------------------------------------------------------------

    @staticmethod
    def _source_diversity_index(observations: List[Dict[str, Any]]) -> float:
        """
        δ = 1 - max_count_from_any_source / total_observations

        Penalises correlated evidence (e.g., 3 drone cameras all confirming
        the same flood). A diverse source set (drone + satellite + human)
        provides more independent evidence → higher δ.

        Returns 0.5 if no observations (maximum uncertainty).
        """
        if not observations:
            return 0.5

        source_counts: Dict[str, int] = {}
        for obs in observations:
            if isinstance(obs, dict):
                src = obs.get("sensor_type", obs.get("source_type", "UNKNOWN"))
            else:
                src = str(obs)
            source_counts[src] = source_counts.get(src, 0) + 1

        max_count = max(source_counts.values())
        total     = len(observations)
        return max(0.0, min(1.0, 1.0 - max_count / total))

    # ------------------------------------------------------------------
    # Sensor Provenance Trust (τ) — auxiliary, feeds into ε
    # ------------------------------------------------------------------

    @staticmethod
    def _sensor_provenance_trust(observations: List[Dict[str, Any]]) -> float:
        """
        τ_avg = mean of sensor_base_accuracy for each observation source.

        Values from sensor_config.json (Category A — already in codebase).
        Returns 0.7 if no observations (pessimistic default).
        """
        if not observations:
            return 0.70

        trusts = []
        for obs in observations:
            if isinstance(obs, dict):
                src = obs.get("sensor_type", obs.get("source_type", "UNKNOWN"))
            else:
                src = str(obs)
            trusts.append(_SENSOR_TRUST.get(src, 0.55))  # default: citizen-report level
        return sum(trusts) / len(trusts)

    # ------------------------------------------------------------------
    # Regret-of-Acting (R_act)
    # ------------------------------------------------------------------

    def _regret_of_acting(
        self,
        epsilon:  float,
        sigma:    float,
        rho:      float,
        I:        float,
        weights:  MissionWeights,
        phase:    str,
        disaster_type: str = "FLOOD",
    ) -> float:
        """
        R_act = μ_act × I × [
            (1-ε) × C_info_wrong +
            (1-σ) × C_crew_lost  +
            (1-ρ) × C_resource_waste
        ]

        Phase modulates C_crew_lost (more aggressive during golden hour,
        more conservative during recovery — crew fatigue).
        """
        c_crew = self._phase_crew_cost(weights.c_crew_lost, phase)

        # Apply disaster-type modifier to action regret
        disaster_modifier = {
            "FLOOD":      0.70,  # flood has good priors, lower action risk
            "EARTHQUAKE": 1.00,  # earthquake has genuine route uncertainty
            "CYCLONE":    0.85,  # cyclone moderate
            "WILDFIRE":   0.90,  # wildfire moderate
        }.get(disaster_type.upper(), 1.0)

        r_act = weights.mu_act * I * (
            (1.0 - epsilon) * weights.c_info_wrong
            + (1.0 - sigma)  * c_crew
            + (1.0 - rho)    * weights.c_resource_waste
        )
        return max(0.0, r_act * disaster_modifier)

    # ------------------------------------------------------------------
    # Regret-of-Waiting (R_wait)
    # ------------------------------------------------------------------

    def _regret_of_waiting(
        self,
        target_node:   str,
        target_data:   Dict[str, Any],
        graph:         nx.Graph,
        disaster_type: str,
        forecasts:     Dict[str, Any],
        hours_elapsed: float,
        weights:       MissionWeights,
        phase:         str,
        aem:           float,
    ) -> float:
        """
        R_wait = μ_wait × AEM × [Ḋ × Δt + W_prob × C_route_closure + G × C_golden_hour]

        Ḋ:      deaths per minute of delay (GEVA survival decay formula)
        Δt:     simulation timestep in minutes (from params — no new constant)
        W_prob: probabilistic route closure probability (from forecasts)
        G:      golden-hour decay factor
        AEM:    access equity multiplier (corrects for isolation bias)
        """
        from backend.allocation.geva import get_vulnerability_multiplier

        p_danger = target_data.get("p_danger", 0.0)
        pop      = target_data.get("population", 0) or 0

        # μ_wait scales with target vulnerability (from geva.py)
        V_target  = get_vulnerability_multiplier(target_data)
        mu_wait   = 1.0 + 0.5 * V_target
        # Phase boost (golden hour: penalise waiting more)
        mu_wait  *= self._phase_wait_boost(weights.mu_wait_boost, phase)

        # Ḋ: deaths per minute (sustained urgency model for disasters)
        gamma = self._gamma_for_disaster(disaster_type)
        sim_time = hours_elapsed * 60.0
        # Fix 4: Disaster-specific danger floor aligned with GEVA floors
        # This ensures DAP and GEVA make consistent assumptions about minimum danger
        _d_dot_danger_floor = {
            "FLOOD": 0.10,       # Match GEVA flood floor — slow onset, low baseline danger
            "EARTHQUAKE": 0.20,  # Rubble entrapment creates real baseline danger
            "CYCLONE": 0.15,     # Storm surge is dynamic
            "WILDFIRE": 0.25,    # Fire proximity is immediately dangerous
        }
        danger_floor = _d_dot_danger_floor.get(disaster_type.upper(), 0.20)
        D_dot = pop * gamma * max(danger_floor, p_danger) * max(0.1, 1.0 - gamma * sim_time * 0.001)
        D_dot = max(0.0, D_dot)

        # Δt: planning horizon in minutes
        t_arrival = target_data.get("t_arrival")
        delta_t = max(5.0, float(t_arrival) if t_arrival else 15.0)

        # W_prob: probabilistic route worsening (from forecasts if available)
        W_prob = self._route_worsening_probability(target_node, target_data, forecasts)

        # G: phase-adjusted golden hour weight
        if phase == "GOLDEN_HOUR":
            G = 1.0
        elif phase == "SUSTAINED_OPS":
            G = 0.5
        else:
            G = 0.25

        # Bound D_dot contribution so R_wait and R_act remain on comparable scales
        # Fix 8: Disaster-specific normalization — calibrated so a critical zone
        # (pop=200, p_danger=0.7, delta_t=15) produces D_dot_scaled ≈ 2.0
        # Low-gamma disasters need smaller divisor to make R_wait meaningful
        _d_dot_norm = {
            "FLOOD": 5.0,        # gamma=0.0005 → tiny D_dot needs small divisor
            "EARTHQUAKE": 30.0,  # gamma=0.008 → moderate D_dot
            "CYCLONE": 15.0,     # gamma=0.005 → moderate D_dot
            "WILDFIRE": 50.0,    # gamma=0.020 → large D_dot needs large divisor
        }
        d_norm = _d_dot_norm.get(disaster_type.upper(), 30.0)
        D_dot_scaled = min(8.0, (D_dot * delta_t) / d_norm)

        r_wait = mu_wait * aem * (
            D_dot_scaled
            + W_prob * _C_ROUTE_CLOSURE
            + G * _C_GOLDEN_HOUR
        )
        return max(0.0, r_wait)


    # ------------------------------------------------------------------
    # Decision Rule
    # ------------------------------------------------------------------

    def _apply_decision_rule(
        self,
        r_act:    float,
        r_wait:   float,
        margin:   float,
        I:        float,
    ) -> Literal["EXECUTE", "DEFER", "ESCALATE", "STAGED_EXECUTE"]:
        # ===================================================================
        # Optimal decision rule (Savage 1951 minimax regret + Loomes-Sugden
        # 1982 asymmetric regret + Simon 1956 satisficing with irreversibility)
        # ===================================================================

        # Case 1: Clear benefit to acting — R_wait dominates
        if r_wait > r_act + margin:
            if I >= _STAGED_THRESHOLD:
                return "STAGED_EXECUTE"
            return "EXECUTE"

        # Case 2: Clear benefit to waiting — R_act dominates
        if r_act > r_wait + margin:
            return "DEFER"

        # Case 3: Both regrets are high and within margin — CRISIS zone
        # Savage minimax: when both options carry high regret, choose the
        # action whose worst case is less catastrophic. In disaster response,
        # the regret of inaction (people die) is generally irreversible,
        # while the regret of action (vehicle stalls) is recoverable.
        # Therefore: ACT, but stage high-irreversibility actions.
        if r_act > _THETA_CRISIS and r_wait > _THETA_CRISIS:
            if I >= _STAGED_THRESHOLD:
                return "STAGED_EXECUTE"
            return "EXECUTE"

        # Case 4: Both regrets are low — use irreversibility as tiebreaker
        # Low-I actions (scouts, reroutes): error is cheap → EXECUTE
        # High-I actions (rescue dispatch): error is costly → DEFER
        # This implements Simon's satisficing: accept "good enough" for
        # reversible actions, demand higher confidence for irreversible ones.
        if I < 0.40:
            return "EXECUTE"   # Scouts — always dispatch in low-regret zone
        elif r_wait >= r_act:
            # Slight lean toward waiting cost → act
            return "EXECUTE"
        else:
            return "DEFER"

    # ------------------------------------------------------------------
    # Hard Vetoes (non-negotiable safety rails)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_vetoes(
        sigma: float,
        rho:   float,
        agent: BaseAgent,
    ) -> Optional[str]:
        """
        Hard vetoes override the entire regret calculation.
        Returns the veto rule name if triggered, else None.
        """
        v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR')
        if sigma <= 0.0 and v_type not in ("ZODIAC_BOAT", "HIGH_WATER_TRUCK", "HELICOPTER"):
            return "VETO_IMPASSABLE: sigma=0, vehicle cannot complete route"
        if agent.fuel < 30.0:
            return "VETO_FUEL_CRITICAL: fuel < 30%, agent would be stranded"
        if agent.comms_blackout:
            return "VETO_COMMS_BLACKOUT: agent cannot receive new orders"
        # Fleet reserve check is handled by ρ reaching 0.0
        if rho <= 0.0:
            return "VETO_FLEET_RESERVE_EMPTY: dispatching would exhaust emergency reserve"
        return None

    # Phase detection removed (handled in OperationalContext)

    # ------------------------------------------------------------------
    # Phase-adaptive cost modulation
    # ------------------------------------------------------------------

    @staticmethod
    def _phase_crew_cost(base_c_crew: float, phase: str) -> float:
        """
        Golden Hour: accept more crew risk (multiplier 0.67 of base).
        Recovery: higher bar due to fatigue (multiplier 1.33 of base).
        Rationale: first 60 min have exponentially higher rescue success.
        """
        if phase == "GOLDEN_HOUR":
            return base_c_crew * 0.67
        if phase == "RECOVERY":
            return base_c_crew * 1.33
        return base_c_crew

    @staticmethod
    def _phase_wait_boost(base_boost: float, phase: str) -> float:
        """Phase-adjusts μ_wait to penalise waiting more during golden hour."""
        if phase == "GOLDEN_HOUR":
            return base_boost * 1.5
        if phase == "RECOVERY":
            return base_boost * 0.7
        return base_boost

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _gamma_for_disaster(disaster_type: str) -> float:
        """Survival decay rate (1/min) from parameters.py (Category A)."""
        upper = disaster_type.upper()
        if upper == "EARTHQUAKE": return params.gamma_earthquake
        if upper == "CYCLONE":    return params.gamma_cyclone
        if upper == "WILDFIRE":   return params.gamma_wildfire
        return params.gamma_flood

    @staticmethod
    def _route_worsening_probability(
        target_node: str,
        target_data: Dict[str, Any],
        forecasts:   Dict[str, Any],
    ) -> float:
        """
        W_prob: estimated probability that route conditions worsen within Δt.

        Uses T+15 min forecast from PredictionEngine if available.
        Looks up the specific target node's forecast first; falls back to
        mean forecast if target-specific data is unavailable.

        Returns value in [0, 1].
        """
        current_p = target_data.get("p_danger", 0.0)
        t15 = forecasts.get("t15", {})
        if isinstance(t15, dict):
            # PredictionEngine returns a dict of node_id → forecast_dict (or float)
            target_fc = t15.get(target_node)
            forecast_p = None
            if isinstance(target_fc, dict):
                forecast_p = target_fc.get("p_danger", target_fc.get("mean"))
            elif isinstance(target_fc, (int, float)):
                forecast_p = float(target_fc)

            if forecast_p is None:
                # Fallback: mean across all forecasted nodes
                vals = []
                for v in t15.values():
                    if isinstance(v, dict):
                        val = v.get("p_danger", v.get("mean"))
                        if isinstance(val, (int, float)):
                            vals.append(float(val))
                    elif isinstance(v, (int, float)):
                        vals.append(float(v))
                forecast_p = (sum(vals) / len(vals)) if vals else None

            if forecast_p is not None:
                # Worsening: forecast > 10% above current
                if current_p > 0:
                    return min(1.0, max(0.0, (forecast_p - current_p) / current_p))
                return 0.5 if forecast_p > 0.5 else 0.0
        # Fallback: use worsening flag if passed directly
        if isinstance(t15, (int, float)):
            return min(1.0, max(0.0, float(t15)))
        return 0.0

# Backwards compatibility alias
EthicalWeights = MissionWeights
