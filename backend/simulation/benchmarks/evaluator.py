import sys
import os
import time
from typing import Dict, Any

# Ensure workspace root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from backend.simulation.engine import SimulationEngine
from backend.world_model.world_state import world_state
from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS

def run_benchmark_evaluation(preset_id: str, disaster_type: str, steps: int = 30) -> Dict[str, Any]:
    """Runs a simulated benchmark run for a preset across the AMIS-RU and SGA-RA models."""
    results = {}
    baselines = ["AMIS-RU", "SGA-RA"]
    
    for baseline in baselines:
        print(f"Evaluating Baseline={baseline} against Historical Preset={preset_id}...")
        engine = SimulationEngine()
        
        # Load preset parameters at center location (Mumbai)
        engine.setup_simulation(
            baseline_type=baseline,
            center_lat=19.0760,
            center_lon=72.8777,
            disaster_type=disaster_type,
            env_mode="HISTORICAL",
            historical_preset=preset_id
        )
        
        # Execute steps
        start_time = time.time()
        for _ in range(steps):
            engine.step()
        execution_time = time.time() - start_time
        
        saved = engine.total_survivors_saved
        initial_pop = engine.initial_total_population
        save_rate = (saved / initial_pop * 100.0) if initial_pop > 0 else 100.0
        
        results[baseline] = {
            "survivors_saved": saved,
            "initial_population": initial_pop,
            "save_rate_pct": round(save_rate, 2),
            "execution_time_sec": round(execution_time, 3),
            "simulated_steps": steps
        }
        
    return results

if __name__ == "__main__":
    # Default test run: Mumbai 2005 Super-Flood
    preset_id = "mumbai_2005"
    disaster_type = "FLOOD"
    res = run_benchmark_evaluation(preset_id, disaster_type, steps=20)
    
    # Load targets
    preset_data = HISTORICAL_PRESETS.get(disaster_type, {}).get(preset_id, {})
    targets = preset_data.get("validation_targets", {})
    
    print("\n==============================================================")
    print("               SENTINEL BENCHMARK EVALUATOR")
    print(f" Scenario: {preset_data.get('name', 'Mumbai Flood')} (20 Steps)")
    print("==============================================================")
    print(" HISTORICAL VALIDATION TARGETS (REAL-WORLD REFERENCE):")
    print(f"  - Target Extrication Rate: {targets.get('historical_survivors_saved_pct')}%")
    print(f"  - Manual Saved Count:      {targets.get('historical_manual_saved_count')} survivors")
    print(f"  - Target Area Covered:     {targets.get('historical_area_covered_pct')}%")
    print(f"  - Target Response Time:    {targets.get('historical_rescue_time_mins')} mins")
    print(f"  - Historical EOC Level:    {targets.get('eoc_intelligence_level')}")
    print("==============================================================")
    for baseline, metrics in res.items():
        print(f"Model Configuration: {baseline}")
        print(f"  - Initial Population: {metrics['initial_population']}")
        print(f"  - Saved Survivors:    {metrics['survivors_saved']}")
        print(f"  - Extrication Rate:   {metrics['save_rate_pct']}%")
        print(f"  - Solver CPU time:    {metrics['execution_time_sec']}s")
        # Direct verification delta
        target_pct = targets.get('historical_survivors_saved_pct', 0.0)
        perf_delta = metrics['save_rate_pct'] - target_pct
        delta_str = f"+{round(perf_delta, 2)}%" if perf_delta >= 0 else f"{round(perf_delta, 2)}%"
        print(f"  - Performance vs Historical Target: {delta_str}")
        print("--------------------------------------------------------------")
