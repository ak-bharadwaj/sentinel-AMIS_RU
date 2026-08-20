"""Trace step-by-step dispatch telemetry for PSA-RA vs AMIS-RU in Bhuj Earthquake."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from backend.simulation.engine import SimulationEngine, AgentStatus

def trace_model(baseline_type):
    engine = SimulationEngine()
    engine.setup_simulation(
        num_rescues=8, num_scouts=4,
        center_lat=23.25, center_lon=69.67,
        disaster_type="EARTHQUAKE",
        historical_preset="bhuj_2001",
        baseline_type=baseline_type,
        seed=42,
        env_mode="BENCHMARK"
    )
    
    status_counts = {"IDLE": 0, "MOVING": 0, "RESCUING": 0, "RETURNING": 0}
    
    for step in range(1, 101):
        engine.step()
        for a in engine.agents.values():
            if a.agent_type == "RESCUE":
                st_name = a.status.name if hasattr(a.status, 'name') else str(a.status)
                status_counts[st_name] = status_counts.get(st_name, 0) + 1
                
    rescues = [a for a in engine.agents.values() if a.agent_type == "RESCUE"]
    completed_trips = sum(getattr(a, 'completed_trips', 0) for a in rescues)
    
    print(f"=== {baseline_type} ===")
    print(f"Total Saved: {engine.total_survivors_saved}")
    print(f"Completed Trips: {completed_trips}")
    print(f"Agent Status Time Allocation (in agent-steps): {status_counts}")
    print(f"Route Failures: {engine.route_failures}")

trace_model("PSA-RA")
trace_model("AMIS-RU")
