import copy
import networkx as nx
import pytest
from backend.agents.base_agent import BaseAgent
from backend.execution_governance.dap import DecisionAdequacyProtocol, MissionWeights
from backend.execution_governance.mission_policy import MissionPolicyManager

def run_scenario(dap, param_name, param_val, target_danger, target_confidence):
    # Setup belief graph
    G = nx.Graph()
    G.add_node("node_A", node_type="POPULATION_ZONE", population=50, 
               p_danger=target_danger, p_state_correct=target_confidence, 
               consistency=0.7, observation_age=10)
    G.add_node("node_B", node_type="SHELTER", population=0, 
               p_danger=0.1, p_state_correct=0.9, consistency=0.8, 
               observation_age=5)
    G.add_edge("node_A", "node_B", distance=1000.0, confidence=target_confidence)
    
    agent = BaseAgent(agent_id="RESCUE_1", agent_type="RESCUE", speed=10.0, start_node="node_B")
    agent.fuel = 100.0
    agent.vehicle_type = "STANDARD_CAR"
    
    # Configure baseline weights
    # Set default values from egl_config.json
    c_route_closure = param_val if param_name == "C_route_closure" else 1.5
    c_golden_hour = param_val if param_name == "C_golden_hour" else 2.0
    aem_slope = param_val if param_name == "aem_slope" else 0.3
    base_margin = param_val if param_name == "base_margin" else 0.15
    
    # Setup ethical weights
    ethical_weights = MissionWeights(
        c_crew_lost=3.0,
        c_resource_waste=0.5,
        c_info_wrong=1.0,
        mu_act=1.0,
        mu_wait_boost=1.0,
        aem_slope=aem_slope,
        profile_name="BALANCED"
    )
    
    import backend.execution_governance.dap as egl_dap

    # Inject variables that are evaluated by the DAP pure math core
    # (Since regret calculations internally use the coefficients)
    # We patch the coefficients on DecisionAdequacyProtocol module level if we want to sweep them.
    orig_closure = egl_dap._C_ROUTE_CLOSURE
    orig_golden = egl_dap._C_GOLDEN_HOUR
    orig_aem = egl_dap._AEM_SLOPE
    
    try:
        egl_dap._C_ROUTE_CLOSURE = c_route_closure
        egl_dap._C_GOLDEN_HOUR = c_golden_hour
        egl_dap._AEM_SLOPE = aem_slope
        
        result = dap.evaluate(
            action_class="RESCUE_DISPATCH",
            agent=agent,
            target_node="node_A",
            route=["node_B", "node_A"],
            belief_graph=G,
            fleet_state={"active_agents": 0, "total_fleet": 3},
            blackout_zones=[],
            forecasts={},
            disaster_type="FLOOD",
            sim_time=10.0,
            ethical_weights=ethical_weights,
            effective_margin=base_margin
        )
        return result.outcome
    finally:
        egl_dap._C_ROUTE_CLOSURE = orig_closure
        egl_dap._C_GOLDEN_HOUR = orig_golden
        egl_dap._AEM_SLOPE = orig_aem

def test_egl_sensitivity_sweeps():
    dap = DecisionAdequacyProtocol()
    
    # We define 10 diverse scenarios (danger, confidence) to create a decision suite
    scenarios = [
        (0.1, 0.9), (0.2, 0.8), (0.3, 0.7), (0.4, 0.6), (0.5, 0.5),
        (0.6, 0.4), (0.7, 0.3), (0.8, 0.2), (0.9, 0.1), (0.5, 0.8)
    ]
    
    # Parameters to sweep: name, default, sensitivity range [low, high]
    parameters = [
        ("C_route_closure", 1.5, [1.0, 2.0]),
        ("C_golden_hour", 2.0, [1.4, 2.6]),
        ("aem_slope", 0.3, [0.2, 0.4]),
        ("base_margin", 0.15, [0.10, 0.20])
    ]
    
    for param_name, default_val, limits in parameters:
        # Run scenarios with default value
        default_outcomes = []
        for danger, conf in scenarios:
            outcome = run_scenario(dap, param_name, default_val, danger, conf)
            default_outcomes.append(outcome)
            
        # Run scenarios with low value (-30% range or specified lower limit)
        low_outcomes = []
        for danger, conf in scenarios:
            outcome = run_scenario(dap, param_name, limits[0], danger, conf)
            low_outcomes.append(outcome)
            
        # Run scenarios with high value (+30% range or specified upper limit)
        high_outcomes = []
        for danger, conf in scenarios:
            outcome = run_scenario(dap, param_name, limits[1], danger, conf)
            high_outcomes.append(outcome)
            
        # Count flips
        flips_low = sum(1 for d, l in zip(default_outcomes, low_outcomes) if d != l)
        flips_high = sum(1 for d, h in zip(default_outcomes, high_outcomes) if d != h)
        
        pct_flipped_low = flips_low / len(scenarios)
        pct_flipped_high = flips_high / len(scenarios)
        
        # Acceptance: No single parameter sweep should flip > 15% of decisions (robustness criterion)
        # Note: With 10 test scenarios, 15% means at most 1 decision flip is allowed (1.5 flips).
        # We check that flips <= 1.
        assert flips_low <= 1, f"Parameter {param_name} low sweep flipped {pct_flipped_low * 100:.1f}% of decisions (> 15% limit)."
        assert flips_high <= 1, f"Parameter {param_name} high sweep flipped {pct_flipped_high * 100:.1f}% of decisions (> 15% limit)."
