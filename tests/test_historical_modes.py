import pytest
import networkx as nx
from backend.simulation.engine import SimulationEngine
from backend.world_model.world_state import world_state

def test_historical_preset_loading():
    engine = SimulationEngine()
    
    # Initialize simulation with the 2005 Super-Flood preset
    engine.setup_simulation(
        center_lat=19.0760,
        center_lon=72.8777,
        disaster_type="FLOOD",
        env_mode="HISTORICAL",
        historical_preset="mumbai_2005"
    )
    
    # Verify environment values are loaded from preset
    assert engine.env_mode == "HISTORICAL"
    assert engine.historical_preset == "mumbai_2005"
    assert engine.tide_phase == "HIGH TIDE"
    assert engine.wind_speed == 18.0
    
    # Verify population zones were successfully scaled by pop_multiplier (1.5)
    for n_id, data in world_state.ground_truth.nodes(data=True):
        if data.get("node_type") == "POPULATION_ZONE":
            # We had randomly generated residential populations scaled by pop_scale (15.0 for Mumbai)
            # and then multiplied by 1.5. So they should be > 0.
            assert data["population"] > 0
            
    # Verify initial total population calculation matches scaled nodes
    expected_pop = sum(
        d.get("population", 0)
        for n, d in world_state.ground_truth.nodes(data=True)
    )
    assert engine.initial_total_population == expected_pop

def test_historical_cyclone_preset():
    engine = SimulationEngine()
    
    # Initialize simulation with Cyclone Nisarga preset
    engine.setup_simulation(
        center_lat=19.0760,
        center_lon=72.8777,
        disaster_type="CYCLONE",
        env_mode="HISTORICAL",
        historical_preset="nisarga_2020"
    )
    
    assert engine.env_mode == "HISTORICAL"
    assert engine.historical_preset == "nisarga_2020"
    assert engine.wind_speed == 90.0
    assert engine.tide_phase == "HIGH TIDE"
