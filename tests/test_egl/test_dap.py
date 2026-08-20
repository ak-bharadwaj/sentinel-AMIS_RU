import networkx as nx
import pytest
from backend.agents.base_agent import BaseAgent
from backend.execution_governance.dap import DecisionAdequacyProtocol, MissionWeights, DAPResult

@pytest.fixture
def base_belief_graph():
    G = nx.Graph()
    G.add_node("node_A", node_type="POPULATION_ZONE", population=50, p_danger=0.2, p_state_correct=0.8, consistency=0.7, observation_age=10)
    G.add_node("node_B", node_type="SHELTER", population=0, p_danger=0.1, p_state_correct=0.9, consistency=0.8, observation_age=5)
    G.add_edge("node_A", "node_B", distance=1000.0, confidence=0.9)
    return G

@pytest.fixture
def default_agent():
    agent = BaseAgent(agent_id="RESCUE_1", agent_type="RESCUE", speed=10.0, start_node="node_B")
    agent.fuel = 100.0
    agent.vehicle_type = "STANDARD_CAR"
    return agent

@pytest.fixture
def default_ethical_weights():
    return MissionWeights(
        c_crew_lost=3.0,
        c_resource_waste=0.5,
        c_info_wrong=1.0,
        mu_act=1.0,
        mu_wait_boost=1.0,
        aem_slope=0.3,
        profile_name="BALANCED"
    )

def test_dap_epistemic_readiness(base_belief_graph, default_agent):
    dap = DecisionAdequacyProtocol()
    # Mocking observations
    default_agent.pending_observations = [
        {"sensor_type": "DRONE_CAMERA", "timestamp": 0},
        {"sensor_type": "HUMAN_VISUAL", "timestamp": 5}
    ]
    
    eps = dap._epistemic_readiness(
        target_node="node_A",
        target_data=base_belief_graph.nodes["node_A"],
        route=["node_B", "node_A"],
        graph=base_belief_graph,
        disaster_type="FLOOD",
        observations=default_agent.pending_observations
    )
    
    assert 0.0 <= eps <= 1.0
    # Higher diversity should yield higher epsilon
    assert eps > 0.5

def test_dap_source_diversity_index():
    dap = DecisionAdequacyProtocol()
    # Uncorrelated sources
    obs_diverse = [
        {"sensor_type": "DRONE_CAMERA"},
        {"sensor_type": "HUMAN_VISUAL"},
        {"sensor_type": "SATELLITE_OPTICAL"}
    ]
    # Fully correlated sources
    obs_correlated = [
        {"sensor_type": "DRONE_CAMERA"},
        {"sensor_type": "DRONE_CAMERA"},
        {"sensor_type": "DRONE_CAMERA"}
    ]
    
    div_score = dap._source_diversity_index(obs_diverse)
    corr_score = dap._source_diversity_index(obs_correlated)
    
    assert div_score > corr_score
    assert corr_score == 0.0  # max count / total = 3/3, 1 - 1 = 0

def test_dap_crew_safety_index(base_belief_graph):
    dap = DecisionAdequacyProtocol()
    
    # Low danger route
    sig_safe = dap._crew_safety_index(
        route=["node_B", "node_A"],
        vehicle_type="STANDARD_CAR",
        target_data=base_belief_graph.nodes["node_A"],
        graph=base_belief_graph
    )
    
    # Introduce high danger on route
    base_belief_graph.nodes["node_A"]["p_danger"] = 0.9
    sig_dangerous = dap._crew_safety_index(
        route=["node_B", "node_A"],
        vehicle_type="STANDARD_CAR",
        target_data=base_belief_graph.nodes["node_A"],
        graph=base_belief_graph
    )
    
    assert sig_safe > sig_dangerous
    assert 0.0 <= sig_dangerous <= 1.0

def test_dap_comms_reliability(base_belief_graph):
    dap = DecisionAdequacyProtocol()
    
    # Node coordinates for distance check
    base_belief_graph.nodes["node_A"]["lat"] = 37.7749
    base_belief_graph.nodes["node_A"]["lon"] = -122.4194
    base_belief_graph.nodes["node_B"]["lat"] = 37.7700
    base_belief_graph.nodes["node_B"]["lon"] = -122.4200
    
    blackout_zones = [
        {"lat": 37.7749, "lon": -122.4194, "radius_m": 500.0}
    ]
    
    # Inside blackout zone should yield lower comms reliability
    kappa_blackout = dap._comms_reliability(
        route=["node_B", "node_A"],
        blackout_zones=blackout_zones,
        graph=base_belief_graph,
        sim_time=10.0
    )
    
    kappa_clear = dap._comms_reliability(
        route=["node_B", "node_A"],
        blackout_zones=[],
        graph=base_belief_graph,
        sim_time=10.0
    )
    
    assert kappa_clear > kappa_blackout

def test_dap_resource_sufficiency(default_agent):
    dap = DecisionAdequacyProtocol()
    fleet_state = {"active_agents": 1, "total_fleet": 5}
    target_data = {"triage_immediate": 5, "triage_delayed": 5}
    
    rho_full = dap._resource_sufficiency(default_agent, fleet_state, target_data)
    
    # Depleted fuel
    default_agent.fuel = 10.0
    rho_low_fuel = dap._resource_sufficiency(default_agent, fleet_state, target_data)
    
    assert rho_full > rho_low_fuel
    assert rho_low_fuel < 0.3

def test_dap_vetoes(default_agent):
    dap = DecisionAdequacyProtocol()
    
    # Normal state - no veto
    veto_normal = dap._check_vetoes(sigma=0.8, rho=0.8, agent=default_agent)
    assert veto_normal is None
    
    # Low safety (sigma=0) -> impassable veto
    veto_safety = dap._check_vetoes(sigma=0.0, rho=0.8, agent=default_agent)
    assert veto_safety is not None
    assert "IMPASSABLE" in veto_safety
    
    # Low fuel
    default_agent.fuel = 20.0
    veto_fuel = dap._check_vetoes(sigma=0.8, rho=0.8, agent=default_agent)
    assert veto_fuel is not None
    assert "FUEL" in veto_fuel

def test_dap_decision_rules_execute_vs_defer():
    dap = DecisionAdequacyProtocol()
    
    # R_wait > R_act + margin -> EXECUTE
    outcome_exec = dap._apply_decision_rule(r_act=0.2, r_wait=0.8, margin=0.15, I=0.3)
    assert outcome_exec == "EXECUTE"
    
    # High irreversibility -> STAGED_EXECUTE
    outcome_stage = dap._apply_decision_rule(r_act=0.2, r_wait=0.8, margin=0.15, I=0.85)
    assert outcome_stage == "STAGED_EXECUTE"
    
    # R_act > R_wait + margin -> DEFER
    outcome_defer = dap._apply_decision_rule(r_act=0.8, r_wait=0.2, margin=0.15, I=0.3)
    assert outcome_defer == "DEFER"
    
    # Both regrets high and within margin -> EXECUTE under urgency (with low irreversibility I=0.3)
    outcome_crisis = dap._apply_decision_rule(r_act=2.5, r_wait=2.6, margin=0.15, I=0.3)
    assert outcome_crisis == "EXECUTE"
    
    # Both regrets high with high irreversibility I=0.85 -> STAGED_EXECUTE
    outcome_crisis_staged = dap._apply_decision_rule(r_act=2.5, r_wait=2.6, margin=0.15, I=0.85)
    assert outcome_crisis_staged == "STAGED_EXECUTE"
