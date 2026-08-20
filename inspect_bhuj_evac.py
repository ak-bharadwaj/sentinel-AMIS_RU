"""Inspect broadcast trigger and evacuation breakdown in Bhuj Earthquake."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from backend.simulation.engine import SimulationEngine

def inspect_bhuj(baseline_type):
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
    
    for _ in range(100):
        engine.step()
        
    print(f"[{baseline_type}] Total Saved: {engine.total_survivors_saved} | Vehicle: {engine.total_survivors_saved - engine.civilian_evacuated_preemptive - engine.civilian_evacuated_reactive} | Pre-Evac: {engine.civilian_evacuated_preemptive} | React-Evac: {engine.civilian_evacuated_reactive}")
    print(f"[{baseline_type}] Broadcast Mode: {engine.broadcast_mode} at step {getattr(engine, 'broadcast_trigger_step', 'NEVER')}")

inspect_bhuj("PSA-RA")
inspect_bhuj("AMIS-RU")
