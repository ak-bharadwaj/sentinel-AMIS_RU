"""Log step 35-60 event trace for SGA-RA vs AMIS-RU."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from backend.simulation.engine import SimulationEngine

def log_trace(baseline_type):
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
    
    for step in range(1, 61):
        engine.step()
        if 35 <= step <= 60:
            rescues = [a for a in engine.agents.values() if a.agent_type == "RESCUE"]
            idle_ids = [a.id for a in rescues if a.status.name == "IDLE"]
            moving_ids = [(a.id, a.target_node) for a in rescues if a.status.name == "MOVING"]
            rescuing_ids = [(a.id, a.target_node) for a in rescues if a.status.name == "RESCUING"]
            print(f"Step {step:2d} [{baseline_type}] Saved: {engine.total_survivors_saved:4d} | Idle: {idle_ids} | Moving: {moving_ids} | Rescuing: {rescuing_ids}")

print("=== SGA-RA ===")
log_trace("SGA-RA")
print("\n=== AMIS-RU ===")
log_trace("AMIS-RU")
