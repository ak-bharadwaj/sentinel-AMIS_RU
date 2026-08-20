import networkx as nx
import pytest
from backend.execution_governance.fleet_coordinator import FleetCoordinationManager

@pytest.fixture
def base_route_graph():
    G = nx.Graph()
    G.add_edge("node_0", "node_1", distance=100.0)
    G.add_edge("node_1", "node_2", distance=100.0)
    G.add_edge("node_2", "node_3", distance=100.0)
    return G

def test_fcm_mutex():
    fcm = FleetCoordinationManager()
    
    assert not fcm.check_mutex("node_A")
    
    fcm.register_dispatch("RESCUE_1", "node_A")
    assert fcm.check_mutex("node_A")
    
    fcm.release_target("node_A")
    assert not fcm.check_mutex("node_A")

def test_fcm_defer_decay():
    fcm = FleetCoordinationManager()
    
    # Base margin
    margin_0 = fcm.get_effective_margin("node_A")
    assert margin_0 == 0.15
    
    # Increment defer
    fcm.increment_defer("node_A")
    margin_1 = fcm.get_effective_margin("node_A")
    assert margin_1 == pytest.approx(0.13)  # decayed by 0.02
    
    # Pushed to escalation count (6 defers)
    for _ in range(4):
        fcm.increment_defer("node_A")
    
    assert fcm.get_effective_margin("node_A") == pytest.approx(0.05)
    
    # 6th defer forces escalation
    fcm.increment_defer("node_A")
    assert fcm.get_effective_margin("node_A") == -1.0  # Sentinel for ESCALATE

def test_fcm_compute_staging_node(base_route_graph):
    fcm = FleetCoordinationManager()
    route = ["node_0", "node_1", "node_2", "node_3"]
    
    # Staging node should be node_2 (approx 67% of cumulative 300.0 distance, i.e., 200.0)
    staging_node = fcm.compute_staging_node(route, base_route_graph)
    assert staging_node == "node_2"

def test_fcm_staged_agent_lifecycle():
    fcm = FleetCoordinationManager()
    route = ["node_0", "node_1", "node_2", "node_3"]
    
    fcm.register_staged("RESCUE_1", "node_3", "node_2", route)
    assert fcm.is_agent_staged("RESCUE_1")
    assert fcm.check_mutex("node_3")  # Locks target node
    
    # Staged state check
    state = fcm.get_staged_state("RESCUE_1")
    assert state.target_node == "node_3"
    assert state.staging_node == "node_2"
    
    # Clear stage dispatch -> yields remaining route from staging node index (idx=2) to target
    remaining = fcm.complete_staged("RESCUE_1")
    assert remaining == ["node_3"]
    assert not fcm.is_agent_staged("RESCUE_1")
