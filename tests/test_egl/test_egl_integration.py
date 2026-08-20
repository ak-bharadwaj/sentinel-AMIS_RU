import networkx as nx
import pytest
import os
from backend.agents.base_agent import BaseAgent
from backend.execution_governance.egl import ExecutionGovernanceLayer

@pytest.fixture
def clean_audit_db():
    db_file = os.path.abspath("test_egl_audit.db")
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    yield db_file
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass

@pytest.fixture
def base_test_graph():
    G = nx.Graph()
    # High danger population zone
    G.add_node("node_A", node_type="POPULATION_ZONE", population=50, p_danger=0.2, p_state_correct=0.8, consistency=0.7, observation_age=10)
    G.add_node("node_B", node_type="SHELTER", population=0, p_danger=0.1, p_state_correct=0.9, consistency=0.8, observation_age=5)
    G.add_edge("node_A", "node_B", distance=1000.0, confidence=0.9)
    return G

@pytest.fixture
def rescue_agent():
    agent = BaseAgent(agent_id="RESCUE_1", agent_type="RESCUE", speed=10.0, start_node="node_B")
    agent.fuel = 100.0
    agent.vehicle_type = "STANDARD_CAR"
    return agent

def test_egl_integration_evaluate(clean_audit_db, base_test_graph, rescue_agent):
    # Initialize with local test SQLite database file
    egl = ExecutionGovernanceLayer(shadow_mode=False)
    # Patch audit path to avoid writing to production egl_audit.db
    egl.am._db_path = clean_audit_db
    egl.am._initialise_db()
    
    fleet_state = {"active_agents": 0, "total_fleet": 3}
    
    decision = egl.evaluate(
        action_class="RESCUE_DISPATCH",
        agent=rescue_agent,
        target_node="node_A",
        route=["node_B", "node_A"],
        belief_graph=base_test_graph,
        fleet_state=fleet_state,
        blackout_zones=[],
        forecasts={},
        disaster_type="FLOOD",
        sim_time=10.0
    )
    
    # We should get a valid EGLDecision
    assert decision.outcome in ("EXECUTE", "DEFER", "ESCALATE", "STAGED_EXECUTE")
    assert decision.rationale != ""
    assert len(decision.xai_event) > 0
    
    # Confirm it was logged in audit
    recent = egl.am.get_recent(5)
    assert len(recent) > 0
    assert recent[0]["agent_id"] == "RESCUE_1"
    assert recent[0]["target_node"] == "node_A"

def test_egl_integration_mutex(clean_audit_db, base_test_graph, rescue_agent):
    egl = ExecutionGovernanceLayer(shadow_mode=False)
    egl.am._db_path = clean_audit_db
    egl.am._initialise_db()
    
    fleet_state = {"active_agents": 0, "total_fleet": 3}
    
    # First dispatch locks target node_A
    egl.evaluate(
        action_class="RESCUE_DISPATCH",
        agent=rescue_agent,
        target_node="node_A",
        route=["node_B", "node_A"],
        belief_graph=base_test_graph,
        fleet_state=fleet_state,
        blackout_zones=[],
        forecasts={},
        disaster_type="FLOOD",
        sim_time=10.0
    )
    
    # Second agent tries to dispatch to the same locked node_A -> must be DEFER'd by fleet mutex veto
    rescue_agent_2 = BaseAgent(agent_id="RESCUE_2", agent_type="RESCUE", speed=10.0, start_node="node_B")
    rescue_agent_2.fuel = 100.0
    
    decision_mutex = egl.evaluate(
        action_class="RESCUE_DISPATCH",
        agent=rescue_agent_2,
        target_node="node_A",
        route=["node_B", "node_A"],
        belief_graph=base_test_graph,
        fleet_state=fleet_state,
        blackout_zones=[],
        forecasts={},
        disaster_type="FLOOD",
        sim_time=10.0
    )
    
    assert decision_mutex.outcome == "DEFER"
    assert "FLEET_MUTEX" in decision_mutex.dap_result.veto

def test_egl_integration_re_evaluate_staged(clean_audit_db, base_test_graph, rescue_agent):
    egl = ExecutionGovernanceLayer(shadow_mode=False)
    egl.am._db_path = clean_audit_db
    egl.am._initialise_db()
    
    fleet_state = {"active_agents": 0, "total_fleet": 3}
    
    # 1. Register agent as staged
    route = ["node_B", "node_A"]
    egl.fcm.register_staged(rescue_agent.id, "node_A", "node_B", route)
    assert egl.fcm.is_agent_staged(rescue_agent.id)
    assert egl.fcm.check_mutex("node_A")
    
    # 2. Re-evaluate agent - should not self-block and return a valid decision
    decision = egl.re_evaluate_staged(
        agent=rescue_agent,
        belief_graph=base_test_graph,
        fleet_state=fleet_state,
        blackout_zones=[],
        forecasts={},
        disaster_type="FLOOD",
        sim_time=10.0
    )
    
    assert decision is not None
    assert decision.outcome in ("EXECUTE", "DEFER", "ESCALATE", "STAGED_EXECUTE")
    
    # Target lock should be released since re-evaluation was executed (and not self-blocked)
    # or updated according to the new decision outcome.
    if decision.outcome in ("DEFER", "ESCALATE"):
        assert not egl.fcm.check_mutex("node_A")
    else:
        assert egl.fcm.check_mutex("node_A")

