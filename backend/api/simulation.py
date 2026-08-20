import os
import threading
import httpx
from typing import Annotated
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from backend.schemas.simulation import SimulationStartSchema, AirdropRequest
from backend.world_model.world_state import world_state
from backend.database import get_db
from backend.simulation.engine import simulation_engine
from backend.api.dependencies import simulation_lock
from pydantic import BaseModel
from typing import List, Optional

DbDep = Annotated[Session, Depends(get_db)]
from backend.agents.scout import ScoutAgent
from backend.agents.rescue import RescueAgent
from backend.config import settings

class LocationConfig(BaseModel):
    lat: float
    lon: float
    vehicle_type: Optional[str] = None

class DeployUnitsSchema(BaseModel):
    havens: List[LocationConfig] = []
    hospitals: List[LocationConfig] = []
    scouts: List[LocationConfig] = []
    rescues: List[LocationConfig] = []

router = APIRouter(
    prefix="/simulation",
    tags=["simulation"]
)

@router.post("/wake-gpu")
def wake_gpu():
    from backend.world_model.global_memory import gmm
    from backend.world_model.world_state import world_state
    
    success = gmm.force_wake_gpu(world_state.belief)
    
    if success:
        return {"status": "success", "message": "GPU Wake Protocol Executed. CUDA Cores Active. Tensor Arrays loaded into VRAM."}
    else:
        return {"status": "fallback", "message": "GPU Activation Failed or Unavailable. Falling back to high-speed CPU C-Arrays."}

@router.post("/plan_phase")
def plan_phase():
    with simulation_lock:
        simulation_engine.generate_phase_plan()
        return {
            "status": "Phase planned", 
            "agents": [a.to_dict() for a in simulation_engine.agents.values()],
            "briefing": getattr(simulation_engine, 'latest_briefing', None)
        }

@router.post("/execute_phase")
def execute_phase():
    with simulation_lock:
        simulation_engine.execute_phase()
        from backend.world_model.global_memory import gmm
        return {
            "status": "Phase executed", 
            "agents": [a.to_dict() for a in simulation_engine.agents.values()],
            "cleared_edges": list(gmm.clearance_ledger)
        }

# Shared dependency alias for cleaner endpoint signatures


@router.post("/start")
def start_simulation(config: SimulationStartSchema):
    """Initializes the simulation graph and agents."""
    print(f"--- START SIMULATION CALL: lat={config.center_lat}, lon={config.center_lon}, map_mode={config.map_mode} ---")
    osm_path = None
    map_mode_used = "SYNTHETIC"  # track whether OSM actually loaded
    if config.map_mode.upper() == "REAL":
        lat_str = f"{config.center_lat:.4f}"
        lon_str = f"{config.center_lon:.4f}"
        span = config.span if config.span else 0.06
        lat_span = config.lat_span if config.lat_span else span
        lon_span = config.lon_span if config.lon_span else span
        osm_filename = f"osm_{lat_str}_{lon_str}_{lat_span:.4f}_{lon_span:.4f}.osm"
        osm_path = os.path.join("datasets", osm_filename)

        import xml.etree.ElementTree as ET
        import time as _time

        def _validate_osm(path: str) -> bool:
            """Returns True if the file exists, has content, and is valid XML."""
            if not os.path.exists(path) or os.path.getsize(path) < 500:
                return False
            try:
                ET.parse(path)
                return True
            except Exception:
                return False

        # If cached file exists but is corrupt, delete it so we re-download cleanly
        if os.path.exists(osm_path) and not _validate_osm(osm_path):
            print(f"[OSM] Cached file '{osm_filename}' is corrupt or empty. Deleting and re-downloading...")
            try:
                os.remove(osm_path)
            except Exception as del_err:
                print(f"[OSM] Could not delete corrupt cache: {del_err}")

        # Download if file does not exist or is empty / corrupt
        if not _validate_osm(osm_path):
            from backend.world_model.graph_builder import download_osm_data
            downloaded = False
            for attempt in range(2):  # retry once on failure
                try:
                    print(f"[OSM] Download attempt {attempt + 1}/2 for {lat_str},{lon_str} lat_span={lat_span} lon_span={lon_span}")
                    download_osm_data(config.center_lat, config.center_lon, osm_path, span=span, lat_span=lat_span, lon_span=lon_span)
                    if _validate_osm(osm_path):
                        downloaded = True
                        print(f"[OSM] Download successful and verified ({os.path.getsize(osm_path)//1024}KB)")
                        break
                    else:
                        print(f"[OSM] Downloaded file is invalid or empty, retrying...")
                        if os.path.exists(osm_path):
                            os.remove(osm_path)
                except Exception as e:
                    print(f"[OSM] Attempt {attempt + 1} failed: {e}")
                    _time.sleep(2)  # wait before retry
            if not downloaded:
                print(f"[OSM] All download attempts failed. Using synthetic grid.")
                osm_path = None

    # Override config params from historical preset if chosen
    if config.env_mode == "HISTORICAL" and config.historical_preset:
        from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
        preset = HISTORICAL_PRESETS.get(config.disaster_type.upper(), {}).get(config.historical_preset, {})
        if preset:
            if config.disaster_type.upper() == "EARTHQUAKE":
                config.magnitude_mw = preset.get("magnitude", config.magnitude_mw)
            elif config.disaster_type.upper() == "CYCLONE":
                config.magnitude_mw = preset.get("windspeed", 120.0) / 25.0

    # Fetch live weather data
    weather_data = {"temperature": 27.0, "windspeed": 15.0, "weathercode": 1}
    if config.env_mode == "LIVE":
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(
                    f"https://api.open-meteo.com/v1/forecast?latitude={config.center_lat}&longitude={config.center_lon}&current_weather=true"
                )
                if resp.status_code == 200:
                    weather_data = resp.json().get("current_weather", weather_data)
                    print(f"[WEATHER] Fetched live data: {weather_data}")
        except Exception as e:
            print(f"[WEATHER] Failed to fetch weather data: {e}")
    else:
        from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
        preset = HISTORICAL_PRESETS.get(config.disaster_type.upper(), {}).get(config.historical_preset, {})
        weather_data = {
            "temperature": 28.0,
            "windspeed": preset.get("windspeed", 15.0),
            "weathercode": 3 if config.disaster_type.upper() == "FLOOD" else 1,
            "simulated": True,
            "preset_name": preset.get("name", "Simulated")
        }

    # 1. Reset graphs and create agents
    try:
        simulation_engine.setup_simulation(
            baseline_type=config.baseline_type, 
            corruption_level=config.corruption_level,
            center_lat=config.center_lat,
            center_lon=config.center_lon,
            osm_path=osm_path,
            num_scouts=config.num_scouts,
            num_rescues=config.num_rescues,
            disaster_type=config.disaster_type,
            num_zodiacs=config.num_zodiacs,
            num_helicopters=config.num_helicopters,
            num_trucks=config.num_trucks,
            num_cars=config.num_cars,
            lat_span=config.lat_span,
            lon_span=config.lon_span,
            env_mode=config.env_mode,
            historical_preset=config.historical_preset
        )
        map_mode_used = "REAL" if osm_path else "SYNTHETIC"
    except Exception as e:
        print(f"[OSM] Error parsing OSM data: {e}. Removing cache and falling back to synthetic grid.")
        if osm_path and os.path.exists(osm_path):
            try:
                os.remove(osm_path)
            except Exception as del_err:
                print(f"Could not remove corrupted file {osm_path}: {del_err}")
        osm_path = None
        map_mode_used = "SYNTHETIC"
        simulation_engine.setup_simulation(
            baseline_type=config.baseline_type, 
            corruption_level=config.corruption_level,
            center_lat=config.center_lat,
            center_lon=config.center_lon,
            osm_path=None,
            num_scouts=config.num_scouts,
            num_rescues=config.num_rescues,
            disaster_type=config.disaster_type,
            num_zodiacs=config.num_zodiacs,
            num_helicopters=config.num_helicopters,
            num_trucks=config.num_trucks,
            num_cars=config.num_cars,
            lat_span=config.lat_span,
            lon_span=config.lon_span,
            env_mode=config.env_mode,
            historical_preset=config.historical_preset
        )

    simulation_engine.weather = weather_data
    
    # 2. Compute priors based on disaster type
    if config.disaster_type.upper() == "EARTHQUAKE":
        from backend.disaster.earthquake import EarthquakeModule
        module = EarthquakeModule(magnitude_mw=config.magnitude_mw)
    elif config.disaster_type.upper() == "CYCLONE":
        # Check if the region has any coast nearby (within 5 km)
        has_coast = any(
            data.get('dist_to_coast', 999999.0) < 5000.0
            for n, data in world_state.ground_truth.nodes(data=True)
        )
        if not has_coast:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="Cyclone disaster mode is only allowed for coastal regions (within 5km of ocean/sea)."
            )
        from backend.disaster.cyclone import CycloneModule
        module = CycloneModule(wind_speed=config.magnitude_mw * 25.0)  # Map slider input to wind speed profile
    elif config.disaster_type.upper() == "WILDFIRE":
        from backend.disaster.wildfire import WildfireModule
        # Use weather metadata to configure wind parameters
        wind_ms = 8.0
        wind_dir = 225.0
        if weather_data and 'current_weather' in weather_data:
            cw = weather_data['current_weather']
            wind_ms = cw.get('windspeed', 28.8) / 3.6  # convert km/h to m/s
            wind_dir = cw.get('winddirection', 225.0)
        module = WildfireModule(wind_speed_ms=wind_ms, wind_direction_deg=wind_dir)
    else:
        from backend.disaster.flood import FloodModule
        module = FloodModule()
        
    module.generate_prior(world_state.ground_truth)
    module.generate_prior(world_state.belief)
    
    # Pre-emptive Blockages for Floods (check both inland water and ocean coastline)
    if config.disaster_type.upper() == "FLOOD":
        for u, v, data in world_state.ground_truth.edges(data=True):
            u_node = world_state.ground_truth.nodes[u]
            v_node = world_state.ground_truth.nodes[v]
            
            u_water = u_node.get('dist_to_water')
            u_coast = u_node.get('dist_to_coast')
            u_dist = min(
                u_water if u_water is not None else 999999.0,
                u_coast if u_coast is not None else 999999.0
            )
            
            v_water = v_node.get('dist_to_water')
            v_coast = v_node.get('dist_to_coast')
            v_dist = min(
                v_water if v_water is not None else 999999.0,
                v_coast if v_coast is not None else 999999.0
            )
            
            if u_dist < 120.0 or v_dist < 120.0:
                data['blocked'] = True
                world_state.belief.edges[u, v]['blocked'] = True
                world_state.belief.edges[u, v]['confidence'] = 1.0
    
    # Sync coordinates to DB
    world_state.sync_to_db()

    # 3. Apply custom shelter / hospital designations from the operator
    def _snap_to_nearest_node(lat: float, lon: float):
        """Return the node_id of the nearest graph node to the given coordinates."""
        return world_state.get_nearest_node(lat, lon)

    for sh in config.custom_shelters:
        lat = sh.get('y', sh.get('y', sh.get('y', sh.get('lat')))) if isinstance(sh, dict) else sh.lat
        lon = sh.get('x', sh.get('x', sh.get('x', sh.get('lon')))) if isinstance(sh, dict) else sh.lon
        nid = _snap_to_nearest_node(lat, lon)
        if nid:
            world_state.belief.nodes[nid]["node_type"] = "SHELTER"
            world_state.belief.nodes[nid]["importance"] = 1.0
            world_state.ground_truth.nodes[nid]["node_type"] = "SHELTER"
            world_state.ground_truth.nodes[nid]["importance"] = 1.0
            print(f"[INIT] Custom SHELTER snapped to node {nid}")

    for hp in config.custom_hospitals:
        lat = hp.get('y', hp.get('y', hp.get('y', hp.get('lat')))) if isinstance(hp, dict) else hp.lat
        lon = hp.get('x', hp.get('x', hp.get('x', hp.get('lon')))) if isinstance(hp, dict) else hp.lon
        nid = _snap_to_nearest_node(lat, lon)
        if nid:
            world_state.belief.nodes[nid]["node_type"] = "HOSPITAL"
            world_state.belief.nodes[nid]["importance"] = 1.0
            world_state.ground_truth.nodes[nid]["node_type"] = "HOSPITAL"
            world_state.ground_truth.nodes[nid]["importance"] = 1.0
            print(f"[INIT] Custom HOSPITAL snapped to node {nid}")

    if config.custom_shelters or config.custom_hospitals:
        world_state.sync_to_db()
    
    return {
        "status": "Initialized",
        "baseline_type": config.baseline_type,
        "disaster_type": config.disaster_type,
        "corruption_level": config.corruption_level,
        "initial_population": simulation_engine.initial_total_population,
        "map_mode_used": map_mode_used,
        "weather": weather_data
    }

@router.post("/save")
def save_mission(db: DbDep):
    """Saves the current mission state to the database."""
    from backend.world_model.node import MissionState
    from backend.simulation.engine import simulation_engine

    # Serialize agents state
    agents_state = []
    for agent in simulation_engine.agents.values():
        agents_state.append({
            "id": agent.id,
            "agent_type": "SCOUT" if hasattr(agent, 'is_scout') or "scout" in agent.id.lower() else "RESCUE",
            "current_node": agent.current_node,
            "status": agent.status.value if hasattr(agent.status, 'value') else str(agent.status),
            "next_node": agent.next_node,
            "target_node": agent.target_node,
            "route": agent.route,
            "full_planned_route": getattr(agent, 'full_planned_route', []),
            "progress_on_edge": agent.progress_on_edge,
            "action_timer": agent.action_timer,
            "vehicle_type": getattr(agent, 'vehicle_type', 'STANDARD_CAR'),
            "capacity": getattr(agent, 'capacity', 4),
            "survivors_onboard": getattr(agent, 'survivors_onboard', 0),
            "zone_assignment": getattr(agent, 'zone_assignment', None)
        })

    # Upsert mission state record
    state = db.query(MissionState).filter(MissionState.id == "current_mission").first()
    if not state:
        state = MissionState(id="current_mission")
        db.add(state)

    state.simulation_time = simulation_engine.simulation_time
    state.active_baseline = simulation_engine.active_baseline
    state.disaster_type = simulation_engine.disaster_type
    state.total_survivors_saved = simulation_engine.total_survivors_saved
    state.initial_total_population = simulation_engine.initial_total_population
    state.history = getattr(simulation_engine, 'history', [])
    state.agents_state = agents_state

    db.commit()
    return {"status": "Success", "message": "Mission state saved successfully."}

@router.post("/load")
def load_mission(db: DbDep):
    """Loads the mission state from the database."""
    from backend.world_model.node import MissionState
    from backend.simulation.engine import simulation_engine
    from backend.agents.scout import ScoutAgent
    from backend.agents.rescue import RescueAgent
    
    state = db.query(MissionState).filter(MissionState.id == "current_mission").first()
    if not state:
        return {"status": "Error", "message": "No saved mission state found."}
        
    simulation_engine.simulation_time = state.simulation_time
    simulation_engine.active_baseline = state.active_baseline
    simulation_engine.disaster_type = state.disaster_type
    simulation_engine.total_survivors_saved = state.total_survivors_saved
    simulation_engine.initial_total_population = state.initial_total_population
    simulation_engine.history = state.history or []
    
    # Restore agents
    simulation_engine.agents.clear()
    from backend.agents.base_agent import AgentStatus
    
    for agent_data in (state.agents_state or []):
        agent_type = agent_data["agent_type"]
        if agent_type == "SCOUT":
            agent = ScoutAgent(agent_data["id"], agent_data["current_node"])
        else:
            # Restore vehicle type and capacity for Rescue Agents
            v_type = agent_data.get("vehicle_type", "STANDARD_CAR")
            cap = agent_data.get("capacity", 4)
            agent = RescueAgent(agent_data["id"], agent_data["current_node"], vehicle_type=v_type, capacity=cap)
            agent.survivors_onboard = agent_data.get("survivors_onboard", 0)
            agent.zone_assignment = agent_data.get("zone_assignment")
            
        agent.status = AgentStatus(agent_data["status"])
        agent.next_node = agent_data["next_node"]
        agent.target_node = agent_data["target_node"]
        agent.route = agent_data["route"]
        agent.full_planned_route = agent_data.get("full_planned_route", [])
        agent.progress_on_edge = agent_data["progress_on_edge"]
        agent.action_timer = agent_data["action_timer"]
        
        simulation_engine.agents[agent.id] = agent
        
    # Re-sync world state to database so visual UI loads the latest state
    from backend.world_model.world_state import world_state
    world_state.sync_to_db()
    
    return {"status": "Success", "message": "Mission state loaded."}

@router.get("/blackout_zones")
def get_blackout_zones():
    return {"blackout_zones": simulation_engine.blackout_zones}

@router.post("/step")
def step_simulation(background_tasks: BackgroundTasks):
    """Runs a single 1-minute step of the simulation."""
    if simulation_engine.coordinator is None:
        return {"status": "Error", "message": "Simulation not started. Call /api/simulation/start first."}
        
    simulation_engine.step()
    
    # Inject route geometries just like the /agents endpoint
    from backend.api.agents import _compute_route_geometry
    agents_data = []
    for agent in simulation_engine.agents.values():
        d = agent.to_dict()
        d["route_geometry"] = _compute_route_geometry(agent)
        if agent.current_node and agent.next_node and agent.current_node != agent.next_node:
            u, v = agent.current_node, agent.next_node
            if world_state.belief.has_edge(u, v):
                edge_data = world_state.belief.edges[u, v]
                geom = edge_data.get("geometry")
                if geom and len(geom) >= 2:
                    src = edge_data.get("edge_source") or u
                    d["current_edge_geometry"] = geom if src == u else list(reversed(geom))
        agents_data.append(d)
        
    stage_complete = not any(
        (
            (hasattr(a.status, 'name') and a.status.name == "MOVING") or 
            (isinstance(a.status, str) and a.status == "MOVING") or
            (a.status == "MOVING")
        ) and a.route for a in simulation_engine.agents.values()
    )
        
    replanning_req = getattr(simulation_engine, 'replanning_required', False)
    if replanning_req:
        simulation_engine.replanning_required = False
        
    # Compute quality metrics for uncertainty-aware coordination
    belief_nodes = len(world_state.belief.nodes)
    unknown_edges = sum(1 for u, v, d in world_state.belief.edges(data=True) if d.get('confidence', 1.0) < 0.5)
    current_blocked_count = sum(1 for uu, vv, d in world_state.ground_truth.edges(data=True) if d.get('blocked', False))
    
    weather_info = getattr(simulation_engine, "weather", {})
    if not isinstance(weather_info, dict):
        weather_info = {}
        
    result = {
        "status": "Success",
        "step": simulation_engine.simulation_time,
        "survivors_saved": simulation_engine.total_survivors_saved,
        "active_baseline": simulation_engine.active_baseline,
        "coverage": simulation_engine.history[-1]["coverage"] if simulation_engine.history else 0.0,
        "map_confidence": simulation_engine.history[-1]["map_confidence"] if simulation_engine.history else 1.0,
        "agents": agents_data,
        "events": simulation_engine.pop_new_events(),
        "stage_complete": stage_complete,
        "replanning_required": replanning_req,
        "replanning_reason": getattr(simulation_engine, 'replanning_reason', None),
        "telemetry": {
            "weather": {
                "temperature_c": weather_info.get("temperature", 24.5),
                "humidity_pct": weather_info.get("humidity", 65.0),
                "pressure_hpa": weather_info.get("pressure", 1012.0),
                "wind_speed_kmh": getattr(simulation_engine, "sensor_wind_speed_kmh", 12.0),
                "wind_direction_deg": weather_info.get("winddirection", 225.0),
                "rainfall_mm_hr": getattr(simulation_engine, "sensor_rainfall_rate", 0.0),
                "cloud_cover_pct": weather_info.get("cloudcover", 45.0),
                "visibility_m": weather_info.get("visibility", 10000.0),
                "preset_name": weather_info.get("preset_name"),
                "simulated": weather_info.get("simulated", False)
            },
            "hydrology": {
                "water_depth_m": getattr(simulation_engine, "sensor_water_level_m", 0.0),
                "water_rise_cm_min": getattr(simulation_engine, "sensor_rainfall_rate", 0.0) * 0.1,
                "flooded_roads": sum(1 for u, v, d in world_state.ground_truth.edges(data=True) if d.get('blocked', False) and simulation_engine.disaster_type == "FLOOD"),
                "drainage_efficiency": 85.0 if getattr(simulation_engine, "tide_phase", "LOW TIDE") == "LOW TIDE" else 15.0,
                "soil_saturation": min(100.0, 45.0 + simulation_engine.simulation_time * 1.5) if simulation_engine.disaster_type == "FLOOD" else 20.0,
                "river_overflow": True if getattr(simulation_engine, "sensor_water_level_m", 0.0) > 1.2 else False,
                "coastal_surge_m": getattr(simulation_engine, "sensor_surge_depth_m", 0.0),
                "tide_state": getattr(simulation_engine, "tide_phase", "LOW TIDE")
            },
            "cyclone": {
                "wind_gust_kmh": getattr(simulation_engine, "sensor_wind_speed_kmh", 0.0) * 1.25,
                "storm_surge_m": getattr(simulation_engine, "sensor_surge_depth_m", 0.0),
                "pressure_drop": max(0.0, 1013.0 - weather_info.get("pressure", 995.0)) if simulation_engine.disaster_type == "CYCLONE" else 0.0,
                "eye_distance_km": max(5.0, 100.0 - simulation_engine.simulation_time * 2.5) if simulation_engine.disaster_type == "CYCLONE" else 999.0,
                "damage_index": min(100.0, getattr(simulation_engine, "sensor_wind_speed_kmh", 0.0) * 0.6)
            },
            "seismic": {
                "pga_g": getattr(simulation_engine, "sensor_seismic_pga_g", 0.0),
                "mmi": max(1.0, min(12.0, getattr(simulation_engine, "sensor_seismic_pga_g", 0.0) * 10.0 + 1.0)),
                "aftershock_probability": max(0.0, 95.0 - simulation_engine.simulation_time * 2.5) if simulation_engine.disaster_type == "EARTHQUAKE" else 0.0,
                "aftershock_decay": math.exp(-simulation_engine.simulation_time / 10.0) if simulation_engine.disaster_type == "EARTHQUAKE" else 0.0,
                "epicenter_distance": 12.5
            },
            "infrastructure": {
                "roads_blocked": current_blocked_count,
                "bridges_damaged": sum(1 for uu, vv, d in world_state.ground_truth.edges(data=True) if d.get('blocked', False) and d.get('is_bridge', False)),
                "communication_health": max(0.0, 100.0 - len(simulation_engine.blackout_zones) * 10.0),
                "power_grid": "STABLE" if current_blocked_count < 10 else "DEGRADED",
                "hospital_capacity": sum(d.get('resources', {}).get('medicine', 100.0) for n, d in world_state.ground_truth.nodes(data=True) if d.get('node_type') == "HOSPITAL") / 12.0,
                "available_shelters": sum(1 for n, d in world_state.ground_truth.nodes(data=True) if d.get('node_type') == "SHELTER" and d.get('status') != "FLOODED")
            },
            "belief": {
                "belief_quality": getattr(simulation_engine, "history", [{}])[-1].get("map_confidence", 1.0) * 100.0 if simulation_engine.history else 100.0,
                "average_confidence": getattr(simulation_engine, "history", [{}])[-1].get("map_confidence", 1.0) if simulation_engine.history else 1.0,
                "unknown_edges": unknown_edges,
                "sensor_reliability": 100.0 - simulation_engine.corruption_level * 100.0 if hasattr(simulation_engine, 'corruption_level') else 100.0
            }
        },
        "situation_assessment": getattr(simulation_engine, "situation_assessment", {}),
        "forecasts_15_30_60": getattr(simulation_engine, "forecasts_15_30_60", {}),
        "ranked_portfolios": getattr(simulation_engine, "ranked_portfolios", []),
        "whatif_sensitivity": getattr(simulation_engine, "whatif_sensitivity", {})
    }
    simulation_engine.replanning_reason = None  # clear after sending
    
    from backend.api.websocket import manager
    import json
    
    payload_str = json.dumps(result)
    payload_size = len(payload_str.encode('utf-8'))
    
    if payload_size > 5 * 1024 * 1024:
        print(f"[TELEMETRY] Payload {payload_size} bytes exceeds 5MB. Downsampling geometry.")
        for agent_d in result.get("agents", []):
            if "route_geometry" in agent_d and isinstance(agent_d["route_geometry"], list):
                # Keep only start and end or a small sample to save size
                agent_d["route_geometry"] = agent_d["route_geometry"][::10] 
        payload_str = json.dumps(result)
        if len(payload_str.encode('utf-8')) > 5 * 1024 * 1024:
            for agent_d in result.get("agents", []):
                agent_d["route_geometry"] = []
                agent_d["current_edge_geometry"] = []
            payload_str = json.dumps(result)

    async def async_broadcast():
        await manager.broadcast(payload_str)
        
    background_tasks.add_task(async_broadcast)
    
    # Return the same truncated result
    return json.loads(payload_str)

@router.post("/airdrop")
def trigger_airdrop(request: AirdropRequest):
    """Adds supplies to the specified Haven node."""
    if request.node_id not in world_state.belief.nodes:
        return {"status": "Error", "message": f"Node {request.node_id} not found."}
        
    node = world_state.belief.nodes[request.node_id]
    if node.get("node_type") not in ("SHELTER", "HOSPITAL"):
        return {"status": "Error", "message": f"Node {request.node_id} is not a valid Haven (SHELTER or HOSPITAL)."}
        
    if 'supplies' not in node:
        node['supplies'] = 0.0
    node['supplies'] += request.amount
    
    gt_node = world_state.ground_truth.nodes[request.node_id]
    if 'supplies' not in gt_node:
        gt_node['supplies'] = 0.0
    gt_node['supplies'] += request.amount
    
    simulation_engine.add_event(f"🪂 Airdrop of {request.amount} supplies delivered to SHELTER {request.node_id}")
    
    return {
        "status": "Success", 
        "node_id": request.node_id, 
        "new_supplies_level": node['supplies']
    }

@router.post("/run_all")
def run_all_simulation():
    """Runs the simulation steps to completion."""
    if simulation_engine.coordinator is None:
        return {"status": "Error", "message": "Simulation not started."}
        
    steps_run = 0
    # Run until limit or all survivors saved
    while (simulation_engine.simulation_time < simulation_engine.max_time):
        simulation_engine.step()
        steps_run += 1
        
        # Early termination if all populations are safe
        active_pop = sum(
            d.get('population', 0)
            for n, d in world_state.ground_truth.nodes(data=True)
            if d.get('node_type') == "POPULATION_ZONE"
        )
        onboard = sum(a.survivors_onboard for a in simulation_engine.agents.values() if a.agent_type == "RESCUE")
        if active_pop == 0 and onboard == 0:
            break
            
    return {
        "status": "Completed",
        "steps_run": steps_run,
        "final_step": simulation_engine.simulation_time,
        "survivors_saved": simulation_engine.total_survivors_saved
    }

@router.get("/resources")
def get_resources():
    return simulation_engine.resource_pool.to_dict()

@router.post("/deploy_units")
def deploy_units(config: DeployUnitsSchema):
    """Manually deploys units and havens/hospitals at nearest nodes."""
    with simulation_lock:
        # 1. Pre-check resource availability
        scout_count = len(config.scouts)
        # We assume scouts use SCOUT_CAR by default for now (or a mix based on vehicle_type)
        scout_types = [s.vehicle_type or "SCOUT_CAR" for s in config.scouts]
        rescue_types = [r.vehicle_type or "STANDARD_CAR" for r in config.rescues]
        
        # Tally required resources
        required_assets = {}
        for t in scout_types + rescue_types:
            required_assets[t] = required_assets.get(t, 0) + 1
            
        for asset, count in required_assets.items():
            if not simulation_engine.resource_pool.can_deploy(asset, count):
                return {"status": "Error", "message": f"Insufficient {asset} resources in the national pool."}
                
        # 2. Deploy havens/hospitals
        modified_nodes = []
        for haven in config.havens:
            node_id = world_state.get_nearest_node(haven.lat, haven.lon)
            if node_id:
                world_state.belief.nodes[node_id]["node_type"] = "SHELTER"
                world_state.ground_truth.nodes[node_id]["node_type"] = "SHELTER"
                modified_nodes.append(node_id)
    
        for hospital in config.hospitals:
            node_id = world_state.get_nearest_node(hospital.lat, hospital.lon)
            if node_id:
                world_state.belief.nodes[node_id]["node_type"] = "HOSPITAL"
                world_state.ground_truth.nodes[node_id]["node_type"] = "HOSPITAL"
                modified_nodes.append(node_id)
    
        if modified_nodes:
            world_state.sync_nodes_to_db(modified_nodes)
    
        # 3. Spawning agents and allocating from pool
        scout_idx = len([a for a in simulation_engine.agents.values() if a.agent_type == "SCOUT"]) + 1
        for scout in config.scouts:
            v_type = scout.vehicle_type or "SCOUT_CAR"
            if simulation_engine.resource_pool.deploy(v_type):
                node_id = world_state.get_nearest_node(scout.lat, scout.lon)
                if node_id:
                    scout_id = f"Scout_{scout_idx}"
                    scout_idx += 1
                    agent = ScoutAgent(scout_id, start_node=node_id)
                    agent.vehicle_type = v_type
                    agent.zone_assignment = f"Zone S-M"
                    simulation_engine.agents[scout_id] = agent
    
        for rescue in config.rescues:
            v_type = rescue.vehicle_type or "STANDARD_CAR"
            if simulation_engine.resource_pool.deploy(v_type):
                node_id = world_state.get_nearest_node(rescue.lat, rescue.lon)
                if node_id:
                    prefix = "Rescue"
                    if v_type == "HELICOPTER":
                        prefix = "Heli"
                    elif v_type == "ZODIAC_BOAT" or v_type == "ZODIAC":
                        prefix = "Zodiac"
                    elif v_type == "HIGH_WATER_TRUCK":
                        prefix = "Truck"
                        
                    idx = len([a for a in simulation_engine.agents.values() if getattr(a, 'vehicle_type', None) == v_type]) + 1
                    rescue_id = f"{prefix}_{idx}"
                    
                    speed = settings.RESCUE_SPEED
                    capacity = 50
                    if v_type == "HELICOPTER":
                        speed = settings.RESCUE_SPEED * 2.5
                        capacity = 15
                    elif v_type == "ZODIAC_BOAT":
                        speed = settings.RESCUE_SPEED * 1.5
                        capacity = 25
                    elif v_type == "HIGH_WATER_TRUCK":
                        speed = settings.RESCUE_SPEED * 0.8
                        capacity = 40
    
                    agent = RescueAgent(rescue_id, start_node=node_id, capacity=capacity, vehicle_type=v_type)
                    agent.speed = speed
                    agent.zone_assignment = f"Zone R-M ({v_type.replace('_', ' ')})"
                    simulation_engine.agents[rescue_id] = agent
                    
        return {"status": "Success", "message": "Units deployed successfully."}

@router.post("/remove_unit")
def remove_unit(request: dict):
    unit_id = request.get("id")
    unit_type = request.get("type") # "agent" or "node"
    
    with simulation_lock:
        if unit_type == "agent":
            if unit_id in simulation_engine.agents:
                agent = simulation_engine.agents[unit_id]
                v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR' if agent.agent_type == 'RESCUE' else 'SCOUT_CAR')
                simulation_engine.resource_pool.recall(v_type)
                del simulation_engine.agents[unit_id]
                return {"status": "success", "message": f"Agent {unit_id} removed"}
        elif unit_type == "node":
            if unit_id in world_state.belief.nodes:
                world_state.belief.nodes[unit_id]["node_type"] = "NORMAL"
                world_state.ground_truth.nodes[unit_id]["node_type"] = "NORMAL"
                return {"status": "success", "message": f"Haven {unit_id} removed"}
    return {"status": "error", "message": "Unit not found"}

@router.post("/move_unit")
def move_unit(request: dict):
    unit_id = request.get("id")
    unit_type = request.get("type") # "agent" or "node"
    new_lat = request.get("lat")
    new_lon = request.get("lon")
    
    with simulation_lock:
        if unit_type == "agent":
            if unit_id in simulation_engine.agents:
                agent = simulation_engine.agents[unit_id]
                node_id = world_state.get_nearest_node(new_lat, new_lon)
                if node_id:
                    node_data = world_state.belief.nodes[node_id]
                    agent.current_node = node_id
                    agent.current_lat = node_data.get("y", node_data.get("lat"))
                    agent.current_lon = node_data.get("x", node_data.get("lon"))
                    agent.path = [] # Reset path
                    return {"status": "success", "message": f"Agent {unit_id} moved"}
    return {"status": "error", "message": "Unit not moved"}

@router.get("/decision")
def get_decision():
    """Returns the current pending decision status and choices."""
    return {
        "paused": simulation_engine.paused_for_decision,
        "active_decision": simulation_engine.active_decision,
        "broadcast_mode": simulation_engine.broadcast_mode
    }

class ResolveDecisionSchema(BaseModel):
    option_id: str

@router.post("/resolve_decision")
def resolve_decision(request: ResolveDecisionSchema):
    """Resolves the active command decision trigger, applying tactical benefits."""
    if not simulation_engine.paused_for_decision or not simulation_engine.active_decision:
        return {"status": "Error", "message": "No active decision pending."}
        
    opt = request.option_id.upper()
    if opt not in ("A", "B", "C"):
        return {"status": "Error", "message": "Invalid option. Must be A, B, or C."}
        
    if opt == "A":
        simulation_engine.safe_route_mode = True
        simulation_engine.scout_clear_mode = False
        simulation_engine.add_event(f"[{simulation_engine.simulation_time}m] 🛡️ COMMAND DECISION: Establish Safe Routing Corridors. Danger penalties scaled to 5x.")
    elif opt == "B":
        # Find haven with lowest food/water resources to supply
        lowest_haven = None
        lowest_val = 99999.0
        for n, data in world_state.ground_truth.nodes(data=True):
            if data.get('node_type') in ("SHELTER", "HOSPITAL"):
                food_val = data.get('resources', {}).get('food', 100.0)
                if food_val < lowest_val:
                    lowest_val = food_val
                    lowest_haven = n
                    
        if lowest_haven:
            simulation_engine.replenish_supplies(lowest_haven, amount=120.0)
            haven_name = world_state.get_node_human_name(lowest_haven)
            simulation_engine.add_event(f"[{simulation_engine.simulation_time}m] 🚁 COMMAND DECISION: Air Bridge cargo drops deployed. Haven '{haven_name}' restocked.")
        else:
            simulation_engine.add_event(f"[{simulation_engine.simulation_time}m] 🚁 COMMAND DECISION: Air Bridge coordinated, but no active Safe Havens found.")
    elif opt == "C":
        simulation_engine.scout_clear_mode = True
        simulation_engine.safe_route_mode = False
        simulation_engine.add_event(f"[{simulation_engine.simulation_time}m] 🛠️ COMMAND DECISION: Tactical Scout & Clear Protocol active. Road clearing speed penalties reduced.")
        
    # Resume the simulation
    simulation_engine.paused_for_decision = False
    simulation_engine.active_decision = None
    
    return {"status": "Success", "message": f"Decision resolved with Option {opt}."}

class ToggleBroadcastSchema(BaseModel):
    mode: str

@router.post("/toggle_broadcast")
def toggle_broadcast(request: ToggleBroadcastSchema):
    """Toggles civilian broadcast instruction mode."""
    mode = request.mode.upper()
    if mode not in ("SHELTER_IN_PLACE", "DIRECTED_EVACUATION"):
        return {"status": "Error", "message": "Invalid broadcast mode."}
        
    simulation_engine.broadcast_mode = mode
    simulation_engine.add_event(f"[{simulation_engine.simulation_time}m] 📣 STRATEGIC BROADCAST: Instructions updated to {mode.replace('_', ' ')}.")

@router.get("/benchmark")
def run_benchmark():
    """Runs a benchmark comparing Sentinel against greedy, nearest, shortest path, and oracle models."""
    from backend.decision_engine.benchmark import BenchmarkSuite
    from backend.world_model.world_state import world_state
    
    targets_list = [
        n_id for n_id, data in world_state.belief.nodes(data=True)
        if data.get("node_type") in ("POPULATION_ZONE", "BRIDGE", "JUNCTION")
        and (data.get("triage_immediate", 0) or 0) + (data.get("triage_delayed", 0) or 0) > 0
    ]
    vehicles_list = [
        {"id": agent.id, "location": agent.current_node, "type": agent.vehicle_type}
        for agent in simulation_engine.agents.values()
    ]
    
    benchmark_res = BenchmarkSuite.run_comparative_benchmark(
        world_state.belief,
        world_state.ground_truth,
        targets_list,
        vehicles_list,
        simulation_engine.disaster_type
    )
    return benchmark_res


class CounterfactualRequest(BaseModel):
    bridge_collapse: Optional[bool] = False
    rainfall_multiplier: Optional[float] = 1.2
    comms_decay_factor: Optional[float] = 0.5
    comms_failure: Optional[bool] = False
    helicopter_grounded: Optional[bool] = False
    mass_casualty: Optional[bool] = False
    triage_scale: Optional[float] = 1.0
    aftershock: Optional[bool] = False
    aftershock_magnitude: Optional[float] = 5.0
    delay_minutes: Optional[float] = 30.0


@router.post("/counterfactual")
def run_counterfactual(request: CounterfactualRequest):
    """Run a what-if sensitivity analysis scenario on the current simulation state."""
    from backend.world_model.world_state import world_state
    from backend.decision_engine.counterfactual import CounterfactualEngine
    import math

    if not simulation_engine.coordinator:
        return {
            "error": "No simulation running. Start a simulation first.",
            "impact_summary": "Simulation not initialized."
        }

    belief = world_state.belief
    base_node = simulation_engine.coordinator.base_node

    # Find a viable source->target pair for route analysis
    target_node = None
    for n_id, ndata in belief.nodes(data=True):
        if (ndata.get("triage_immediate", 0) or 0) + (ndata.get("triage_delayed", 0) or 0) > 0:
            target_node = n_id
            break

    results = {"scenario": "custom", "parameters": request.dict()}

    if target_node and base_node:
        import networkx as nx
        base_path = []
        try:
            base_path = nx.shortest_path(belief, base_node, target_node, weight="distance")
        except Exception:
            base_path = [base_node, target_node] if base_node != target_node else [base_node]

        sensitivity_options = {
            "rainfall_multiplier": request.rainfall_multiplier,
            "comms_decay_factor": request.comms_decay_factor,
            "helicopter_grounded": request.helicopter_grounded,
        }
        if request.bridge_collapse:
            # block a mid-path node to simulate bridge collapse
            if len(base_path) > 2:
                sensitivity_options["bridge_collapse_node"] = base_path[len(base_path) // 2]

        try:
            vehicle_type = "STANDARD_CAR"
            if request.helicopter_grounded is False:
                vehicle_type = "HELICOPTER"
            cf_results = CounterfactualEngine.run_whatif_sensitivity_analysis(
                belief, base_node, target_node, vehicle_type, base_path, sensitivity_options
            )
            results.update(cf_results)
        except Exception as e:
            results["analysis_error"] = str(e)

    # Delay penalty analysis
    triage_immediate = sum(
        (ndata.get("triage_immediate", 0) or 0) for _, ndata in belief.nodes(data=True)
    )
    triage_delayed = sum(
        (ndata.get("triage_delayed", 0) or 0) for _, ndata in belief.nodes(data=True)
    )
    scaled_immediate = int(triage_immediate * (request.triage_scale or 1.0))
    scaled_delayed = int(triage_delayed * (request.triage_scale or 1.0))

    try:
        delay_result = CounterfactualEngine.evaluate_delay_penalties(
            scaled_immediate, scaled_delayed, request.delay_minutes
        )
        results["delay_penalty"] = delay_result
    except Exception as e:
        results["delay_penalty"] = {"error": str(e)}

    # Comms failure impact
    if request.comms_failure:
        comms_nodes = [n for n, d in belief.nodes(data=True) if d.get("node_type") == "COMMS_TOWER"]
        failed = len(comms_nodes) // 2
        results["comms_failure"] = {
            "total_comms_nodes": len(comms_nodes),
            "nodes_failed": failed,
            "coverage_loss_pct": round(failed / max(1, len(comms_nodes)) * 100, 1),
            "impact": f"{failed} of {len(comms_nodes)} comms nodes lost. Confidence decay accelerates.",
            "remediation": "Deploy scout UAVs to relay zones. Activate satellite uplink."
        }

    # Aftershock impact
    if request.aftershock:
        mag = request.aftershock_magnitude
        intensity = 1 - math.exp(-0.2 * (mag - 4.0))
        results["aftershock"] = {
            "magnitude": mag,
            "intensity": round(intensity, 3),
            "expected_additional_damage_pct": round(intensity * 30, 1),
            "expected_additional_casualties": round(intensity * triage_immediate * 0.3),
            "impact": f"M{mag} aftershock: +{round(intensity*30)}% structural damage, +{round(intensity*triage_immediate*0.3)} new casualties.",
            "remediation": "Re-sweep cleared zones. Priority re-triage of immediate cases."
        }

    results["impact_summary"] = (
        f"What-if scenario completed. "
        f"{triage_immediate} immediate / {triage_delayed} delayed casualties in active simulation. "
        f"Delay of {request.delay_minutes}m estimated to cost ~{round(request.delay_minutes * 0.4)} lives."
    )

    return results


@router.get("/intelligence")
def get_intelligence():
    """Returns XAI reasoning tree and situation assessment from the latest decision cycle."""
    from backend.world_model.world_state import world_state
    from backend.decision_engine.explainability import ExplainabilityEngine
    from backend.decision_engine.situation_assessment import SituationAssessmentEngine

    result = {
        "reasoning_tree": None,
        "situation_assessment": None,
        "latest_xai_events": [],
        "decision_alternatives": []
    }

    try:
        situation = SituationAssessmentEngine.compute_indexes(
            world_state.belief,
            world_state.ground_truth,
            getattr(simulation_engine, "disaster_type", None)
        )
        result["situation_assessment"] = situation
    except Exception as e:
        result["situation_assessment"] = {"error": str(e)}

    try:
        latest_decision = None
        xai_events = getattr(simulation_engine, "xai_log", [])
        result["latest_xai_events"] = xai_events[-20:] if xai_events else []

        # Build reasoning tree from latest decision
        if simulation_engine.coordinator:
            latest_decision = {
                "action": f"Mission Phase {simulation_engine.simulation_time}m",
                "agents": len(simulation_engine.agents),
                "confidence": 0.85,
                "description": "AI decision cycle completed."
            }
            if xai_events:
                last = xai_events[-1]
                latest_decision["action"] = last.get("action", latest_decision["action"])
                latest_decision["confidence"] = last.get("confidence", 0.85)

        reasoning = ExplainabilityEngine.generate_rationale(
            world_state.belief,
            world_state.ground_truth,
            latest_decision or {}
        )
        result["reasoning_tree"] = reasoning
    except Exception as e:
        result["reasoning_tree"] = {"error": str(e)}

    except Exception as alt_err:
        print(f"[API] Warning: Failed fetching decision alternatives: {alt_err}")

    return result
