"""Step-by-step comparison between SGA-RA and AMIS-RU in Bhuj Earthquake."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from backend.simulation.engine import SimulationEngine

def run_and_log(baseline_type):
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
    
    print(f"\n==================== {baseline_type} ====================")
    for step in range(1, 101):
        engine.step()
        if step % 20 == 0 or step in (1, 5, 10, 15):
            rescues = [a for a in engine.agents.values() if a.agent_type == "RESCUE"]
            idle_count = sum(1 for a in rescues if a.status.name == "IDLE")
            moving_count = sum(1 for a in rescues if a.status.name == "MOVING")
            rescuing_count = sum(1 for a in rescues if a.status.name == "RESCUING")
            print(f"Step {step:3d} | Saved: {engine.total_survivors_saved:5d} | Idle: {idle_count} | Moving: {moving_count} | Rescuing: {rescuing_count} | Stalls: {engine.route_failures}")

run_and_log("SGA-RA")
run_and_log("AMIS-RU")
