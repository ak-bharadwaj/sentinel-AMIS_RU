"""Test EV Rate ranking in Allocator across all 4 disaster scenarios."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from backend.simulation.engine import SimulationEngine
import numpy as np

def run_test(disaster_type, preset, baseline_type, steps=100, seed=42):
    coords = {
        "mumbai_2005": (19.0760, 72.8777),
        "bhuj_2001": (23.25, 69.67),
        "nisarga_2020": (18.65, 72.87),
        "aarey_2018": (19.14, 72.88)
    }
    c_lat, c_lon = coords.get(preset, (19.0760, 72.8777))
    
    engine = SimulationEngine()
    engine.setup_simulation(
        num_rescues=8, num_scouts=4,
        center_lat=c_lat, center_lon=c_lon,
        disaster_type=disaster_type,
        historical_preset=preset,
        baseline_type=baseline_type,
        seed=seed,
        env_mode="BENCHMARK"
    )
    
    for _ in range(steps):
        engine.step()
        
    initial_pop = max(1, engine.initial_total_population)
    saved_pct = (engine.total_survivors_saved / initial_pop) * 100.0
    
    return {
        "saved": engine.total_survivors_saved,
        "saved_pct": round(saved_pct, 2),
        "stalls": engine.route_failures
    }

scenarios = [
    ("FLOOD", "mumbai_2005", "Mumbai Flood"),
    ("EARTHQUAKE", "bhuj_2001", "Bhuj Earthquake"),
    ("CYCLONE", "nisarga_2020", "Nisarga Cyclone"),
    ("WILDFIRE", "aarey_2018", "Aarey Wildfire")
]

print("\n" + "="*90)
print("EVALUATING CURRENT ALLOCATOR ACROSS 4 SECTORS (100 STEPS)")
print("="*90)

for dtype, preset, name in scenarios:
    print(f"\n--- Scenario: {name} ---")
    for b in ["PSA-RA", "SGA-RA", "AMIS-RU"]:
        r = run_test(dtype, preset, b, steps=100, seed=42)
        print(f"  Model: {b:<10} | Saved: {r['saved']:>5} ({r['saved_pct']:>5}%) | Stalls: {r['stalls']}")

print("\n" + "="*90 + "\n")
