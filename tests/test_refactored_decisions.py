import pytest
import networkx as nx
from backend.decision_engine.information_gain import InformationGainEngine
from backend.decision_engine.explainability import ExplainabilityEngine

def test_active_scouting_loop_battery_safesport():
    # Setup standard belief graph
    g = nx.Graph()
    g.add_node("BASE", node_type="SHELTER", confidence=1.0)
    g.add_node("A", node_type="POPULATION_ZONE", population=50, triage_immediate=5, triage_delayed=2, confidence=0.5)
    g.add_edge("BASE", "A", distance=1000.0, confidence=0.8)

    # Test battery threshold check (< 15%)
    res = InformationGainEngine.evaluate_active_scouting_loop(
        scout_id="UAV_01",
        current_node="BASE",
        target_node=None,
        current_path=[],
        belief_graph=g,
        battery_level=12.0
    )
    assert res["action"] == "WAIT"
    assert "Battery is critically low" in res["reasoning"]

def test_active_scouting_loop_weather_grounding():
    g = nx.Graph()
    g.add_node("BASE", node_type="SHELTER", confidence=1.0)
    g.add_node("A", node_type="POPULATION_ZONE", population=50, triage_immediate=5, triage_delayed=2, confidence=0.5)
    g.add_edge("BASE", "A", distance=1000.0, confidence=0.8)

    # Test extreme weather check
    res = InformationGainEngine.evaluate_active_scouting_loop(
        scout_id="UAV_01",
        current_node="BASE",
        target_node=None,
        current_path=[],
        belief_graph=g,
        weather_state={"wind_speed": 60.0, "rain_intensity": 20.0},
        battery_level=90.0
    )
    assert res["action"] == "WAIT"
    assert "Severe weather conditions" in res["reasoning"]

def test_active_scouting_loop_launch_success():
    g = nx.Graph()
    g.add_node("BASE", node_type="SHELTER", confidence=1.0)
    g.add_node("A", node_type="POPULATION_ZONE", population=50, triage_immediate=5, triage_delayed=2, confidence=0.5)
    g.add_edge("BASE", "A", distance=1000.0, confidence=0.8)

    # Test launch condition from base
    res = InformationGainEngine.evaluate_active_scouting_loop(
        scout_id="UAV_01",
        current_node="BASE",
        target_node=None,
        current_path=[],
        belief_graph=g,
        weather_state={"wind_speed": 10.0, "rain_intensity": 5.0},
        battery_level=95.0,
        evi_thresholds={"launch": 0.1, "scan": 0.8, "dispatch": 0.4, "reroute": 0.3, "wait": 0.1}
    )
    assert res["action"] == "LAUNCH"
    assert res["target_node"] == "A"
    assert len(res["path"]) > 0

def test_enriched_explainability_tree():
    g = nx.Graph()
    g.add_node("A", node_type="POPULATION_ZONE", population=30, triage_immediate=3, triage_delayed=1, confidence=0.8, water_level=0.1)
    g.add_edge("BASE", "A", distance=1200.0, confidence=0.9)

    assignment = {
        "target_node": "A",
        "vehicle_id": "RESCUE_CAR_01",
        "vehicle_type": "STANDARD_CAR",
        "path_confidence": 0.85,
        "distance": 1200.0,
        "utility_score": 15.6,
        "rejected_alternatives": [
            {
                "vehicle_type": "ZODIAC_BOAT",
                "target_node": "A",
                "utility_score": 8.5,
                "reason": "Zodiac boat travel over dry road sections has severe speed penalties."
            }
        ]
    }

    res = ExplainabilityEngine.generate_rationale(assignment, g)
    
    assert "reasoning_tree" in res
    tree = res["reasoning_tree"]
    
    # Check decision choice exists
    chosen_node = next(child for child in tree["children"] if child["node_id"] == "chosen_decision")
    assert "Dispatch STANDARD_CAR" in chosen_node["value"]
    
    # Check optimization objectives exists
    obj_node = next(child for child in tree["children"] if child["node_id"] == "optimization_objectives")
    assert len(obj_node["children"]) == 3 # Casualty, time, reliability
    
    # Check hard constraints exists
    const_node = next(child for child in tree["children"] if child["node_id"] == "hard_constraints")
    assert const_node["status"] == "PASS"
    
    # Check trade offs exists
    trade_node = next(child for child in tree["children"] if child["node_id"] == "decision_tradeoffs")
    assert "Strategic Trade-offs Evaluated" in trade_node["label"]
    
    # Check rejected alternatives exists
    rej_node = next(child for child in tree["children"] if child["node_id"] == "rejected_alternatives")
    assert len(rej_node["children"]) == 1
    assert rej_node["children"][0]["status"] == "REJECTED"
