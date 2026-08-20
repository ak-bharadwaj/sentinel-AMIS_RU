import networkx as nx  # type: ignore
from backend.agents.fleet_config import get_effective_speed
from typing import Optional, Tuple, List, Dict, Any
from backend.routing.cost_config import WEIGHTS, SAFE_ROUTE_MULTIPLIER, REFERENCE_TIME_S
from backend.routing.helicopter_model import helicopter_edge_cost
from backend.world_model.terrain.slope import slope_accessibility_multiplier

IMPASSABLE_COST = 1e9

def get_vehicle_risk(node_data: dict, vehicle_type: str) -> float:
    """Extract vehicle-specific hazard danger probabilities from separate hazard layers."""
    # Projection matrix representation mapping vehicle index to relevant hazards
    # Boat cares only about structural, Helicopter cares about fire/wind, Cars care about flood/structural
    if vehicle_type == "ZODIAC_BOAT":
        return node_data.get('p_structural', node_data.get('p_danger', 0.0))
    elif vehicle_type == "HIGH_WATER_TRUCK":
        return node_data.get('p_structural', node_data.get('p_danger', 0.0))
    elif vehicle_type == "HELICOPTER":
        fire_p = node_data.get('p_fire')
        wind_p = node_data.get('p_wind')
        if fire_p is not None or wind_p is not None:
            return max(fire_p or 0.0, wind_p or 0.0)
        return node_data.get('p_danger', 0.0)
    else:  # STANDARD_CAR
        return max(node_data.get('p_flood', node_data.get('p_danger', 0.0)),
                   node_data.get('p_structural', node_data.get('p_danger', 0.0)))

def calculate_edge_cost(
    graph: nx.Graph,
    u: str,
    v: str,
    edge_data: Dict[str, Any],
    vehicle_type: str = "STANDARD_CAR",
    disaster_type: str = "FLOOD",
    weather_state: Optional[Dict[str, Any]] = None,
    safe_route_mode: bool = False
) -> float:
    node_u = graph.nodes[u]
    node_v = graph.nodes[v]

    # Retrieve water levels above road surface (water_level - effective_elevation)
    wl_u = node_u.get('water_level', 0.0)
    wl_v = node_v.get('water_level', 0.0)
    eff_elev_u = node_u.get("effective_elevation", node_u.get("elevation", 10.0))
    eff_elev_v = node_v.get("effective_elevation", node_v.get("elevation", 10.0))
    water_above_u = max(0.0, wl_u - eff_elev_u)
    water_above_v = max(0.0, wl_v - eff_elev_v)
    water_level = max(water_above_u, water_above_v)
    is_blocked = edge_data.get('blocked', False)

    # 1. Endpoints status check
    status_u = node_u.get('status', 'SAFE')
    status_v = node_v.get('status', 'SAFE')
    if status_u in ('BLOCKED', 'FLOODED') or status_v in ('BLOCKED', 'FLOODED'):
        if vehicle_type == "HELICOPTER":
            pass
        elif vehicle_type == "ZODIAC_BOAT" and disaster_type in ("FLOOD", "CYCLONE"):
            pass  # Note: Boat depth bounds and land speed penalties are strictly enforced by get_effective_speed below
        elif vehicle_type == "HIGH_WATER_TRUCK" and disaster_type in ("FLOOD", "CYCLONE") and water_level <= 8.0:
            pass
        else:
            return IMPASSABLE_COST
    
    distance = edge_data.get('distance', 1.0)
    
    # Helicopters fly directly over everything using custom operational bounds
    if vehicle_type == "HELICOPTER":
        return helicopter_edge_cost(distance, node_u, node_v, weather_state)
        
    p_danger_edge = (get_vehicle_risk(node_u, vehicle_type) + get_vehicle_risk(node_v, vehicle_type)) / 2.0
    is_cleared = edge_data.get('rubble_cleared', False)
    eff_speed = get_effective_speed(vehicle_type, 10.0, water_level, is_blocked, disaster_type=disaster_type, p_danger=p_danger_edge, is_cleared=is_cleared)

    if eff_speed <= 0.0:
        return IMPASSABLE_COST  # impassable

        
    speed_factor = edge_data.get('speed_factor', 1.0)
        
    # Calculate travel-time cost equivalent
    effective_speed_factor = (eff_speed / 10.0) * speed_factor
    time_cost_raw = distance / max(0.01, effective_speed_factor)
    time_cost_norm = time_cost_raw / REFERENCE_TIME_S
    
    confidence_edge = (node_u.get('p_state_correct', 1.0) + node_v.get('p_state_correct', 1.0)) / 2.0
    
    risk_mult = SAFE_ROUTE_MULTIPLIER if safe_route_mode else 1.0

    # Linear scalarization model combining physical hazard risk (aleatoric) and map confidence (epistemic)
    # Note: Scalarization is an explicit design choice for single-objective Dijkstra performance.
    risk_penalty = WEIGHTS["w_risk"] * p_danger_edge * risk_mult

    # Fix 2: Disaster-aware uncertainty penalty scaling
    # Static-hazard disasters (earthquake rubble) have lower epistemic routing penalty
    # because hazard map is mostly settled after initial event — unvisited ≠ dangerous.
    # Dynamic-hazard disasters (flood, cyclone) keep full penalty — water rises, uncertainty = real danger.
    # Literature: Bertsimas & Sim (2004) — uncertainty penalties should scale with rate of env change.
    _uncertainty_disaster_scale = {
        "FLOOD": 1.0,        # Dynamic: water rises continuously
        "CYCLONE": 0.80,     # Semi-dynamic: storm surge + wind shifts
        "EARTHQUAKE": 0.12,  # Static: rubble settles within first 30 min — minimal epistemic penalty
        "WILDFIRE": 0.50,    # Semi-dynamic: fire front moves but predictably
    }
    unc_scale = _uncertainty_disaster_scale.get(disaster_type, 1.0)
    uncertainty_penalty = WEIGHTS["w_uncertainty"] * (1.0 - confidence_edge) * unc_scale

    # Terrain cost — slope + surface quality, vehicle-aware
    terrain_penalty = 0.0
    if vehicle_type not in ("HELICOPTER", "ZODIAC_BOAT"):
        slope_u = node_u.get("slope", 0.0)
        slope_v = node_v.get("slope", 0.0)
        avg_slope = (slope_u + slope_v) / 2.0
        slope_mult = slope_accessibility_multiplier(avg_slope, vehicle_type)
        # Accessibility score: lower score → higher cost, normalized strictly to [0.0, 1.0]
        acc_u = max(0.0, min(1.0, node_u.get("accessibility_score", 1.0)))
        acc_v = max(0.0, min(1.0, node_v.get("accessibility_score", 1.0)))
        terrain_penalty = WEIGHTS.get("w_terrain", 0.8) * (slope_mult - 1.0) * (1.0 - min(acc_u, acc_v))

    return time_cost_norm + risk_penalty + uncertainty_penalty + terrain_penalty


def update_grid_edge_costs(graph: nx.Graph) -> None:
    """Fallback cache update (kept for interface compatibility)."""
    for u, v, data in graph.edges(data=True):
        data['cost'] = calculate_edge_cost(graph, u, v, data)

def find_confidence_route(
    graph: nx.Graph,
    source: str,
    target: str,
    vehicle_type: str = "STANDARD_CAR",
    cost_cache: Optional[Dict[str, float]] = None
) -> Optional[Tuple[List[str], float, float]]:
    """Finds the safest reliable route using Dijkstra with dynamic edge cost weights based on fleet capabilities.
    Uses cost_cache if supplied to skip recalculations.
    Returns: (path_list, total_distance, average_confidence) or None.
    """
    weight_key = f'cost_{vehicle_type}'
    
    # Pre-extract weather and safe route variables from the engine state to avoid imports in dynamic_weight hot paths
    from backend.simulation.engine import simulation_engine
    weather = getattr(simulation_engine, 'weather', None)
    safe_route = getattr(simulation_engine, 'safe_route_mode', False)
    dis_type = getattr(simulation_engine, 'disaster_type', 'FLOOD')
    
    def dynamic_weight(u, v, edge_attrs):
        cost = edge_attrs.get(weight_key)
        if cost is None:
            cache_key = f"{u}_{v}_{vehicle_type}"
            if cost_cache is not None and cache_key in cost_cache:
                return cost_cache[cache_key]
                
            cost = calculate_edge_cost(
                graph, u, v, edge_attrs, 
                vehicle_type=vehicle_type, 
                disaster_type=dis_type,
                weather_state=weather, 
                safe_route_mode=safe_route
            )
            if cost_cache is not None:
                cost_cache[cache_key] = cost
        return cost

    try:
        path = nx.shortest_path(
            graph, 
            source=source, 
            target=target, 
            weight=dynamic_weight
        )
        
        # Calculate statistics
        total_distance = 0.0
        confidences = []
        for i in range(len(path) - 1):
            u, v = path[i], path[i+1]
            edge_data = graph.edges[u, v]
            total_distance += edge_data.get('distance', 0.0)
            
            node_u = graph.nodes[u]
            node_v = graph.nodes[v]
            conf = (node_u.get('p_state_correct', 1.0) + node_v.get('p_state_correct', 1.0)) / 2.0
            confidences.append(conf)
            
        avg_confidence = sum(confidences) / len(confidences) if confidences else 1.0
        return path, total_distance, avg_confidence
        
    except nx.NetworkXNoPath:
        return None
    except nx.NodeNotFound:
        return None
