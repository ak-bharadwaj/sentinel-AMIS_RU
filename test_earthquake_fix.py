"""Test Sentinel DSS performance in Bhuj Earthquake with obstacle safeguard."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from backend.simulation.engine import SimulationEngine
import numpy as np

def run_bhuj():
    engine = SimulationEngine()
    engine.setup_simulation(
        num_rescues=8, num_scouts=4,
        center_lat=23.25, center_lon=69.67,
        disaster_type="EARTHQUAKE",
        historical_preset="bhuj_2001",
        baseline_type="AMIS-RU",
        seed=42,
        env_mode="BENCHMARK"
    )
    
    for _ in range(100):
        engine.step()
        
    initial_pop = max(1, engine.initial_total_population)
    saved_pct = (engine.total_survivors_saved / initial_pop) * 100.0
    print(f"AMIS-RU Bhuj 100 steps -> Saved: {engine.total_survivors_saved} ({saved_pct:.2f}%) | Stalls: {engine.route_failures}")

run_bhuj()
