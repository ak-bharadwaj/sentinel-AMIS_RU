"""
Sentinel DSS — Central Parameter Registry
==========================================
All tunable simulation parameters in one place.

IMPORTANT: Values marked as ASSUMPTIONS are NOT empirically calibrated.
They are reasonable engineering defaults. Before operational deployment,
validate against historical event data relevant to your region and disaster type.

Load order:
  1. Defaults defined here
  2. Override from parameters.json if present in working directory
  3. Runtime override via /api/parameters endpoint (not yet implemented)
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field, asdict


@dataclass
class SentinelParameters:
    # -----------------------------------------------------------------------
    # Simulation timing
    # -----------------------------------------------------------------------
    timestep_duration_s: int = 60          # Seconds per simulation step
    max_simulation_steps: int = 1440        # Total steps per run (24 hours)

    # -----------------------------------------------------------------------
    # Knowledge decay
    # ASSUMPTION: exponential decay. Rate not empirically calibrated.
    # -----------------------------------------------------------------------
    knowledge_decay_rate: float = 0.05     # lambda — per-step decay on p_state_correct

    # -----------------------------------------------------------------------
    # Survival decay [gamma, 1/minute]
    # ASSUMPTION: exponential survival decay. Values are engineering estimates.
    # Flood: slow onset. Earthquake: rubble entrapment rapid deterioration.
    # Cyclone: storm surge drowning. Wildfire: proximity to flame front.
    # These should be calibrated to regional historical casualty data.
    # -----------------------------------------------------------------------
    gamma_flood:      float = 0.0005       # 1/min — slow onset, mostly mobile victims
    gamma_earthquake: float = 0.008        # 1/min — rubble entrapment
    gamma_cyclone:    float = 0.005        # 1/min — storm surge / debris
    gamma_wildfire:   float = 0.020        # 1/min — active fire front proximity

    # -----------------------------------------------------------------------
    # Agent speeds
    # -----------------------------------------------------------------------
    scout_speed_ms:   float = 15.0         # m/s (~54 km/h)
    rescue_speed_ms:  float = 10.0         # m/s (~36 km/h)
    helicopter_speed_ms: float = 62.0      # m/s (~223 km/h HAL Dhruv cruise speed)

    # -----------------------------------------------------------------------
    # Flood thresholds [metres]
    # Based on standard hydraulic engineering depth-damage thresholds.
    # Passenger cars: hazardous at 0.15m, impassable at 0.30m.
    # Trucks: 0.60m. Bridges: clearance-dependent; 0.80m is conservative default.
    # -----------------------------------------------------------------------
    flood_car_caution_m:    float = 0.15   # Warning threshold (speed reduced)
    flood_car_blocked_m:    float = 0.30   # Car impassable
    flood_truck_blocked_m:  float = 0.60   # High-water truck impassable
    flood_bridge_blocked_m: float = 0.80   # Bridge closure (conservative)

    # -----------------------------------------------------------------------
    # Bayesian / observation reliability
    # Note: OBSERVATION_RELIABILITY is kept for backward compatibility.
    # The sensor_model.py module loads per-sensor values from sensor_config.json.
    # -----------------------------------------------------------------------
    observation_reliability: float = 0.90  # Legacy fallback — use sensor_model instead

    # -----------------------------------------------------------------------
    # GEVA allocation
    # ASSUMPTION: these EV weightings are heuristic.
    # -----------------------------------------------------------------------
    geva_exploration_weight:   float = 0.05   # Information-gain exploration bonus
    geva_overlap_ev_penalty:   float = 12.0   # EV penalty per shared route edge

    # -----------------------------------------------------------------------
    # Grid / procedural generation
    # -----------------------------------------------------------------------
    grid_size_lat: float = 0.02
    grid_size_lon: float = 0.02

    # -----------------------------------------------------------------------
    # Terrain Intelligence Layer
    # Added by: Sentinel Terrain Intelligence Framework V1
    # -----------------------------------------------------------------------
    # Flood: minimum effective_elevation (m) to classify a road as elevated
    flood_elevated_road_min_m: float = 2.0
    # Flood: tunnel fill rate multiplier (tunnels are below grade — fill faster)
    flood_tunnel_fill_rate: float = 2.5

    # Terrain accessibility score weights (used to compute node.accessibility_score)
    terrain_acc_weight_slope:      float = 0.40   # slope contribution
    terrain_acc_weight_elevation:  float = 0.25   # low-elevation flood risk contribution
    terrain_acc_weight_drainage:   float = 0.25   # high-TWI waterlogging contribution
    terrain_acc_weight_coastal:    float = 0.10   # coastal surge risk contribution

    # Routing terrain cost weight (w_terrain in WEIGHTS dict)
    routing_terrain_weight: float = 0.8

    def load(self, path: str = "parameters.json") -> "SentinelParameters":
        """Load overrides from a JSON file. Silently skips if file not found."""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    overrides: dict = json.load(f)
                for key, value in overrides.items():
                    if hasattr(self, key):
                        setattr(self, key, type(getattr(self, key))(value))
            except Exception as exc:
                print(f"[SentinelParameters] Warning: failed to load {path}: {exc}")
        return self

    def to_dict(self) -> dict:
        return asdict(self)


# Module-level singleton — import this everywhere instead of duplicating values
params = SentinelParameters().load()
