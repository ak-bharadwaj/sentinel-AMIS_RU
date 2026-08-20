import math
from typing import Dict, Any
from backend.config import settings
from backend.config_params.parameters import params

# Vulnerability class multipliers — determines how much rescue urgency increases based on
# population demographics at the node. Elderly, trapped, and injured populations decay
# faster and must be reached sooner.
VULNERABILITY_MULTIPLIERS: Dict[str, float] = {
    "CRITICAL":  3.0,   # Hospitals: trapped patients, ICU, non-ambulatory
    "HIGH":      2.0,   # Residential dense areas: elderly, families with children
    "MEDIUM":    1.2,   # General residential: mixed ambulatory population
    "LOW":       0.6,   # Bridge/junction: mostly mobile adults who can self-evacuate
    "STANDARD":  1.0,   # Default
}

def get_vulnerability_multiplier(node_data: Dict[str, Any]) -> float:
    """Returns a vulnerability multiplier based on node type and demographic indicators."""
    t_imm = node_data.get('triage_immediate') or 0
    t_del = node_data.get('triage_delayed') or 0
    t_min = node_data.get('triage_minor') or 0
    total_triage = t_imm + t_del + t_min
    
    if total_triage > 0:
        # Weighted blend based on actual triage proportions, not binary trigger
        pop = node_data.get('population', 0) or 1
        general_pop = max(0, pop - total_triage)
        weighted = (
            t_imm * VULNERABILITY_MULTIPLIERS["CRITICAL"]
            + t_del * VULNERABILITY_MULTIPLIERS["HIGH"]
            + t_min * VULNERABILITY_MULTIPLIERS["MEDIUM"]
            + general_pop * VULNERABILITY_MULTIPLIERS["STANDARD"]
        )
        return weighted / pop


    node_type = node_data.get('node_type', 'ROAD')
    if node_type == 'HOSPITAL':
        population = node_data.get('population', 0)
        # Only assign CRITICAL if hospital itself is in danger or has trapped population
        if node_data.get('p_danger', 0.0) > 0.5 or population > 0:
            # Hospital: scale by actual patients (2.0 base + up to 1.0 bonus for high patient count)
            return 2.0 + min(1.0, population / 200.0)
        return VULNERABILITY_MULTIPLIERS['LOW']
    elif node_type == 'POPULATION_ZONE':
        pop_density = node_data.get('population', 0)
        dense_threshold = getattr(params, 'dense_population_threshold', 400)
        if pop_density > dense_threshold:
            return 2.5    # Dense residential, likely elderly
        else:
            return VULNERABILITY_MULTIPLIERS['MEDIUM']
    elif node_type in ('BRIDGE', 'JUNCTION'):
        return VULNERABILITY_MULTIPLIERS['LOW']         # People on bridges can move
    return VULNERABILITY_MULTIPLIERS['STANDARD']

def calculate_ev(
    p_danger: float,
    population: int,
    reachability: float,
    t_arrival_minutes: float,
    vulnerability_multiplier: float = 1.0,
    p_state_correct: float = 0.5,
    disaster_type: str = "FLOOD"
) -> float:
    """Computes Uncertainty-Weighted Expected Value Assignment.
    Formula:
      S_expected = Population * exp(-gamma * p_danger * t_arrival)
      EV = p_state_correct * p_danger * S_expected * Reachability * VulnerabilityMultiplier
    """
    # Resolve decay constant based on disaster type
    disaster_upper = disaster_type.upper()
    if disaster_upper == "EARTHQUAKE":
        gamma = params.gamma_earthquake
    elif disaster_upper == "CYCLONE":
        gamma = params.gamma_cyclone
    elif disaster_upper == "WILDFIRE":
        gamma = params.gamma_wildfire
    else:
        gamma = params.gamma_flood

    if disaster_upper == "FLOOD":
        eff_p_danger = max(0.10, p_danger)   # minimal floor for flood
        eff_p_state  = max(0.60, p_state_correct)
    else:
        eff_p_danger = max(1e-4, p_danger)   # raw for earthquake/cyclone/wildfire
        eff_p_state  = max(0.50, p_state_correct)
    
    # Survival decay: expected survivors remaining at time of arrival
    s_expected = population * math.exp(-gamma * eff_p_danger * t_arrival_minutes)
    
    # Expected value of rescue: expected lives saved, scaled by danger, vulnerability and reachability
    ev = eff_p_state * eff_p_danger * s_expected * reachability * vulnerability_multiplier
    return ev


