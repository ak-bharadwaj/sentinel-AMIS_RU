import json
import os
import math
from typing import Dict, Any, List

# Load configuration parameters
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config_params", "routing_weights.json")
try:
    with open(CONFIG_PATH, "r") as f:
        _weights_cfg = json.load(f)
except Exception:
    _weights_cfg = {}

WEIGHTS: Dict[str, float] = _weights_cfg.get("weights", {
    "w_time":        1.0,
    "w_risk":        2.0,
    "w_uncertainty": 0.5,
    "w_terrain":     0.8,   # Terrain cost weight (slope + surface quality)
})

SAFE_ROUTE_MULTIPLIER: float = _weights_cfg.get("safe_route", {}).get("risk_multiplier", 3.0)
REFERENCE_TIME_S: float = _weights_cfg.get("normalisation", {}).get("reference_time_s", 360.0)

BPR_CFG = _weights_cfg.get("bpr_congestion", {})
BPR_ALPHA: float = BPR_CFG.get("alpha", 0.15)
BPR_BETA: float = BPR_CFG.get("beta", 4.0)

ROAD_CAPACITIES: Dict[str, int] = _weights_cfg.get("road_capacity_vehicles_per_hour", {
    "motorway":    2000,
    "primary":     1200,
    "secondary":    800,
    "tertiary":     600,
    "residential":  400,
    "service":      200,
    "track":        100
})

HELI_CFG = _weights_cfg.get("helicopter", {})
HELI_SPEED_KMH: float = HELI_CFG.get("cruise_speed_kmh", 223.2)
HELI_WIND_LIMIT_KMH: float = HELI_CFG.get("wind_limit_kmh", 55.0)
HELI_SMOKE_NO_FLY: float = HELI_CFG.get("smoke_density_no_fly", 0.8)
HELI_NO_PAD_COST: float = HELI_CFG.get("no_helipad_approach_cost", 0.5)
