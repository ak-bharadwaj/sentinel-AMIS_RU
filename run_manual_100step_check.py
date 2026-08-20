import os
import sys
import argparse
import random
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def run_diagnostic_check(steps: int, baseline: str, disaster: str = "FLOOD", preset: str = "mumbai_2005", seed: int = 0):
    print(f"\n==============================================================")
    print(f"   RUNNING DIAGNOSTIC CHECK: {baseline} | {disaster} ({preset}) | {steps} steps")
    print(f"==============================================================")

    # Seed verification printout
    np.random.seed(42 + seed)
    random.seed(42 + seed)
    print(f"SEED CHECK: np_seed={42+seed}, random_seed={42+seed}")
    print(f"FIRST RANDOM: np={np.random.random():.6f}, random={random.random():.6f}")

    db_file = f"diag_check_seed_{seed}_{baseline}.db"
    db_url = f"sqlite:///{db_file}"
    os.environ['DATABASE_URL'] = db_url

    import backend.database
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    backend.database.engine = create_engine(db_url, connect_args={"check_same_thread": False})
    backend.database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=backend.database.engine)

    from backend.database import Base, engine as db_engine
    from backend.world_model.world_state import world_state
    from backend.simulation.engine import SimulationEngine, AgentStatus
    from backend.disaster.flood import FloodModule
    from backend.disaster.earthquake import EarthquakeModule
    from backend.disaster.wildfire import WildfireModule
    from backend.disaster.cyclone import CycloneModule

    Base.metadata.create_all(bind=db_engine)

    engine = SimulationEngine()

    world_state.initialize(
        osm_path=None,
        center_lat=19.0760 if "mumbai" in preset or "aarey" in preset else 20.0,
        center_lon=72.8777 if "mumbai" in preset or "aarey" in preset else 75.0,
        corruption_level=0.4,
        force_rebuild=True
    )

    engine.setup_simulation(
        baseline_type=baseline,
        center_lat=19.0760 if "mumbai" in preset or "aarey" in preset else 20.0,
        center_lon=72.8777 if "mumbai" in preset or "aarey" in preset else 75.0,
        disaster_type=disaster,
        env_mode="HISTORICAL",
        historical_preset=preset,
        num_scouts=4,
        num_rescues=8,
        seed=42 + seed
    )

    if disaster == "FLOOD":
        mod = FloodModule()
    elif disaster == "EARTHQUAKE":
        mod = EarthquakeModule()
    elif disaster == "WILDFIRE":
        mod = WildfireModule()
    else:
        mod = CycloneModule()

    mod.generate_prior(world_state.ground_truth)
    mod.generate_prior(world_state.belief)
    engine.recompile_and_sync_tensors()

    print(f"\nStep | Saved (Tot) | Evac(React) | Evac(Preempt) | Resc(Veh) | RouteFails | Exec | Defer | Escalate")
    print(f"-----------------------------------------------------------------------------------------------------")

    for s in range(1, steps + 1):
        engine.step()

        saved_tot = engine.total_survivors_saved
        react = engine.civilian_evacuated_reactive
        preempt = engine.civilian_evacuated_preemptive
        resc_veh = saved_tot - react - preempt
        fails = engine.route_failures

        exec_c = 0
        defer_c = 0
        esc_c = 0

        if engine.egl:
            exec_c = engine.egl.outcome_counts.get("EXECUTE", 0)
            defer_c = engine.egl.outcome_counts.get("DEFER", 0)
            esc_c = engine.egl.outcome_counts.get("ESCALATE", 0)

        # Print per-step line
        print(f"{s:4d} | {saved_tot:11d} | {react:11d} | {preempt:13d} | {resc_veh:9d} | {fails:10d} | {exec_c:4d} | {defer_c:5d} | {esc_c:8d}")

        if s % 20 == 0 or s == steps:
            # Fleet status check for earthquake or long runs
            fleet_statuses = [f"{a.id}:{a.status.name}" for a in engine.agents.values() if a.agent_type == "RESCUE"][:4]
            fleet_str = ", ".join(fleet_statuses)
            print(f"      +- [Fleet Snapshot @ {s}m] Stalls/Failures: {fails} | Fleet: {fleet_str}")

    db_engine.dispose()
    try:
        if os.path.exists(db_file):
            os.remove(db_file)
    except Exception:
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--baseline", type=str, default="AMIS-RU")
    parser.add_argument("--disaster", type=str, default="FLOOD")
    parser.add_argument("--preset", type=str, default="mumbai_2005")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    run_diagnostic_check(args.steps, args.baseline, args.disaster, args.preset, args.seed)
