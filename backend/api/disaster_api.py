from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List
import math
from backend.world_model.world_state import world_state
from backend.simulation.engine import simulation_engine

router = APIRouter(prefix="/disaster", tags=["Disaster"])

class LatLon(BaseModel):
    lat: float
    lon: float

class DisasterInjectSchema(BaseModel):
    disaster_type: str  # "FLOOD" or "EARTHQUAKE"
    shape: str  # "CIRCLE" or "RECTANGLE"
    center: Optional[LatLon] = None
    radius_m: Optional[float] = 500.0  # Default 500 meters
    bounds: Optional[List[float]] = None  # [min_lat, min_lon, max_lat, max_lon]
    intensity: float = 1.0  # 0.0 to 1.0

class DisasterAnalyzeSchema(BaseModel):
    shape: str  # "CIRCLE" or "RECTANGLE"
    center: Optional[LatLon] = None
    radius_m: Optional[float] = 500.0
    bounds: Optional[List[float]] = None

def get_distance(lat1, lon1, lat2, lon2):
    # Quick distance in meters
    d_lat = (lat1 - lat2) * 111000.0
    d_lon = (lon1 - lon2) * 111000.0 * math.cos(math.radians(lat1))
    return math.hypot(d_lat, d_lon)

def is_node_in_selection(node_lat, node_lon, config):
    if config.shape.upper() == "CIRCLE" and config.center:
        dist = get_distance(node_lat, node_lon, config.center.lat, config.center.lon)
        return dist <= config.radius_m
    elif config.shape.upper() == "RECTANGLE" and config.bounds and len(config.bounds) == 4:
        min_lat, min_lon, max_lat, max_lon = config.bounds
        return min_lat <= node_lat <= max_lat and min_lon <= node_lon <= max_lon
    return False

@router.post("/analyze")
def analyze_area(config: DisasterAnalyzeSchema):
    """Calculates aggregate stats and geographic susceptibility for a selected map sub-region."""
    from backend.world_model.graph_builder import FAULT_LINE, RIVER_LINE, calculate_distance_to_line_segment
    
    total_pop = 0
    blocked_roads_count = 0
    agents_count = 0
    threats_sum = 0.0
    nodes_count = 0
    
    elevations = []
    min_dist_to_water = float('inf')
    min_dist_to_fault = float('inf')
    
    # 1. Find nodes inside selection
    nodes_in_selection = []
    for n_id, data in world_state.belief.nodes(data=True):
        nlat = data.get("lat")
        nlon = data.get("lon")
        if nlat is not None and nlon is not None:
            if is_node_in_selection(nlat, nlon, config):
                nodes_in_selection.append(n_id)
                total_pop += data.get("population", 0)
                threats_sum += data.get("p_danger", 0.0)
                nodes_count += 1
                
                # Proximity analysis
                elev = data.get("elevation", 50.0)
                elevations.append(elev)
                
                is_coastal = data.get("is_coastal", False)
                is_bridge = data.get("is_bridge", False)
                if is_coastal or is_bridge:
                    min_dist_to_water = 0.0
                else:
                    dist_w = calculate_distance_to_line_segment(nlat, nlon, RIVER_LINE[0], RIVER_LINE[1])
                    min_dist_to_water = min(min_dist_to_water, dist_w)
                    
                dist_f = calculate_distance_to_line_segment(nlat, nlon, FAULT_LINE[0], FAULT_LINE[1])
                min_dist_to_fault = min(min_dist_to_fault, dist_f)
                
    # 2. Find blocked roads inside selection
    selection_set = set(nodes_in_selection)
    for u, v, data in world_state.belief.edges(data=True):
        if u in selection_set and v in selection_set:
            if data.get("blocked", False):
                blocked_roads_count += 1
                
    # 3. Find active agents inside selection
    for agent in simulation_engine.agents.values():
        agent_node = agent.current_node
        if agent_node in selection_set:
            agents_count += 1
            
    avg_threat = (threats_sum / nodes_count) if nodes_count > 0 else 0.0
    avg_elev = (sum(elevations) / len(elevations)) if elevations else 25.0
    
    # Classify Susceptibility
    if min_dist_to_water == float('inf'):
        min_dist_to_water = 5000.0
    if min_dist_to_fault == float('inf'):
        min_dist_to_fault = 5000.0
        
    if avg_elev < 15.0 and min_dist_to_water < 600.0:
        flood_susceptibility = "HIGH"
    elif avg_elev < 30.0 or min_dist_to_water < 1500.0:
        flood_susceptibility = "MEDIUM"
    else:
        flood_susceptibility = "LOW"
        
    if min_dist_to_fault < 900.0:
        seismic_susceptibility = "HIGH"
    elif min_dist_to_fault < 2200.0:
        seismic_susceptibility = "MEDIUM"
    else:
        seismic_susceptibility = "LOW"
        
    return {
        "stranded_population": total_pop,
        "blocked_roads": blocked_roads_count,
        "active_agents": agents_count,
        "avg_threat_level": round(avg_threat, 2),
        "avg_elevation": round(avg_elev, 1),
        "dist_to_water": round(min_dist_to_water, 1),
        "flood_susceptibility": flood_susceptibility,
        "seismic_susceptibility": seismic_susceptibility
    }

@router.post("/inject")
def inject_disaster(config: DisasterInjectSchema):
    """Dynamically injects a localized disaster into the specified zone, constrained by geography."""
    # First, calculate susceptibility for the target region to determine intensity scaling
    stats = analyze_area(DisasterAnalyzeSchema(
        shape=config.shape, center=config.center, radius_m=config.radius_m, bounds=config.bounds
    ))
    
    scale_factor = 1.0
    reason = "Normal impact"
    
    if config.disaster_type.upper() == "FLOOD":
        if stats["flood_susceptibility"] == "LOW":
            scale_factor = 0.0 if stats["avg_elevation"] > 40.0 else 0.15
            reason = "High elevation / inland zone (restricted flow)"
        elif stats["flood_susceptibility"] == "MEDIUM":
            scale_factor = 0.5
            reason = "Moderate risk inland grid"
    else:  # EARTHQUAKE
        if stats["seismic_susceptibility"] == "LOW":
            scale_factor = 0.2
            reason = "Far from active geological fault ruptures"
        elif stats["seismic_susceptibility"] == "MEDIUM":
            scale_factor = 0.6
            reason = "Moderate proximity to fault lines"
            
    effective_intensity = config.intensity * scale_factor
    nodes_affected = 0
    edges_blocked = 0
    
    if effective_intensity > 0.0:
        # 1. Identify nodes in selection
        affected_nodes = []
        for n_id, data in world_state.ground_truth.nodes(data=True):
            nlat = data.get("lat")
            nlon = data.get("lon")
            if nlat is not None and nlon is not None:
                if is_node_in_selection(nlat, nlon, config):
                    affected_nodes.append(n_id)
                    nodes_affected += 1
                    
                    # Update danger level and status
                    data["p_danger"] = min(1.0, data.get("p_danger", 0.0) + effective_intensity * 0.8)
                    
                    if config.disaster_type.upper() == "FLOOD":
                        data["water_level"] = float(data.get("water_level", 0.0) or 0.0) + effective_intensity * 30.0
                        if data["water_level"] > 15.0 and data.get("node_type") not in ("HOSPITAL", "SHELTER"):
                            data["status"] = "FLOODED"
                    else:  # EARTHQUAKE
                        if float(data.get("p_danger", 0.0) or 0.0) > 0.75 and data.get("node_type") not in ("HOSPITAL", "SHELTER"):
                            data["status"] = "DANGER"
                            
                    # Sync back to belief state immediately
                    if n_id in world_state.belief:
                        world_state.belief.nodes[n_id]["p_danger"] = data["p_danger"]
                        world_state.belief.nodes[n_id]["status"] = data["status"]
                        if config.disaster_type.upper() == "FLOOD":
                            world_state.belief.nodes[n_id]["water_level"] = data["water_level"]
                            
        # 2. Block edges in selection
        affected_set = set(affected_nodes)
        for u, v, data in world_state.ground_truth.edges(data=True):
            if u in affected_set and v in affected_set:
                # Under high intensity, block the roads
                if not data.get("blocked", False) and effective_intensity > 0.4:
                    data["blocked"] = True
                    data["confidence"] = 1.0
                    edges_blocked += 1
                    
                    # Sync edge blockage to belief immediately
                    if world_state.belief.has_edge(u, v):
                        world_state.belief.edges[u, v]["blocked"] = True
                        world_state.belief.edges[u, v]["confidence"] = 1.0
                        
        world_state.sync_to_db()
        
    # Log manual injection event
    shape_desc = f"circle (r={config.radius_m}m)" if config.shape.upper() == "CIRCLE" else "bounding rectangle"
    dis_desc = "Torrential Flood Surge" if config.disaster_type.upper() == "FLOOD" else "Local Seismic Tremor"
    
    simulation_engine.add_event(
        f"[{simulation_engine.simulation_time}m] 🚨 INJECTION PROTOCOL: Manual trigger of {dis_desc} inside {shape_desc}. "
        f"Constraint: {reason} (Effective Severity: {int(effective_intensity*100)}%). Affected {nodes_affected} nodes."
    )
    
    return {
        "status": "Success",
        "nodes_affected": nodes_affected,
        "edges_blocked": edges_blocked,
        "effective_intensity": effective_intensity
    }
