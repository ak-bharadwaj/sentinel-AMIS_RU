import math
import networkx as nx  # type: ignore
from backend.config import settings
from backend.belief.sensor_model import (
    ObservationContext, evaluate_observation_quality, SENSOR_MAX_RANGE_M, MIN_ETA
)
from backend.world_model.graph_builder import haversine_distance

def compute_bayesian_update(p_prior: float, observation: str, eta: float) -> float:
    """Computes Bayesian update on p_danger given a binary observation.
    observation: 'SAFE' or 'DANGER'
    """
    p = p_prior
    if observation == "SAFE":
        numerator = p * (1.0 - eta)
        denominator = p * (1.0 - eta) + (1.0 - p) * eta
    else:  # DANGER
        numerator = p * eta
        denominator = p * eta + (1.0 - p) * (1.0 - eta)
        
    if denominator == 0:
        return p
    from backend.config_params.parameters import params
    min_p = getattr(params, 'min_belief_probability', 1e-4)
    max_p = getattr(params, 'max_belief_probability', 1.0 - 1e-4)
    return max(min_p, min(max_p, numerator / denominator))

def apply_scout_observation(
    belief_graph: nx.Graph,
    ground_truth_graph: nx.Graph,
    node_id: str,
    sensor_type: str = "HUMAN_VISUAL",
    age_minutes: float = 0.0,
    visibility_km: float = 10.0,
    wind_speed_kmh: float = 0.0,
    smoke_present: bool = False
) -> None:
    """Simulates a scout reaching a node, verifying the node and incident edges.
    Updates the BeliefGraph using the rich sensor model.
    """
    if node_id not in belief_graph:
        return
        
    # 1. Read ground truth state of the node
    gt_node = ground_truth_graph.nodes[node_id]
    gt_status = gt_node.get('status', 'SAFE')
    
    # 2. Build observation context and compute quality metrics
    context = ObservationContext(
        sensor_type=sensor_type,
        age_minutes=age_minutes,
        visibility_km=visibility_km,
        distance_m=0.0,  # At the node
        disaster_type=getattr(settings, "DISASTER_TYPE", "FLOOD"),
        wind_speed_kmh=wind_speed_kmh,
        smoke_present=smoke_present
    )
    quality = evaluate_observation_quality(context)
    
    # Update Node Belief
    prior_p = belief_graph.nodes[node_id].get('p_danger', 0.0)
    updated_p = compute_bayesian_update(prior_p, gt_status, quality.eta)
    
    belief_graph.nodes[node_id]['p_danger'] = updated_p
    belief_graph.nodes[node_id]['status'] = gt_status
    # Node confidence ceiling accumulated probabilistically over repeated observations
    old_conf = belief_graph.nodes[node_id].get('p_state_correct', 0.5)
    belief_graph.nodes[node_id]['p_state_correct'] = max(quality.eta, 1.0 - (1.0 - old_conf) * (1.0 - quality.eta))
    # Sync verified population and triage metrics into belief graph
    belief_graph.nodes[node_id]['population'] = gt_node.get('population', 0)
    belief_graph.nodes[node_id]['triage_immediate'] = gt_node.get('triage_immediate', 0)
    belief_graph.nodes[node_id]['triage_delayed'] = gt_node.get('triage_delayed', 0)
    belief_graph.nodes[node_id]['triage_minor'] = gt_node.get('triage_minor', 0)
    
    # 3. Verify all incident edges and update neighbors using visibility range-based decay
    lat_u = belief_graph.nodes[node_id].get('lat', 0.0)
    lon_u = belief_graph.nodes[node_id].get('lon', 0.0)
    max_range = SENSOR_MAX_RANGE_M.get(sensor_type, 100.0)
    
    for neighbor in list(belief_graph.neighbors(node_id)):
        # Read true blocked state of this edge
        gt_edge_blocked = ground_truth_graph.edges[node_id, neighbor].get('blocked', False)
        
        # Scale-dependent observation logic for aerial assets (DRONE_CAMERA)
        is_major = belief_graph.edges[node_id, neighbor].get('speed_factor', 1.0) >= 1.2
        if sensor_type == "DRONE_CAMERA":
            edge_conf = quality.eta * 0.95 if is_major else 0.30
        else:
            edge_conf = quality.eta
            
        # Update edge belief
        belief_graph.edges[node_id, neighbor]['blocked'] = gt_edge_blocked
        old_edge_conf = belief_graph.edges[node_id, neighbor].get('confidence', 0.5)
        belief_graph.edges[node_id, neighbor]['confidence'] = max(edge_conf, 1.0 - (1.0 - old_edge_conf) * (1.0 - edge_conf))
        
        # Partially verify neighbor node based on distance, visibility and LOS modeling assumptions
        lat_v = belief_graph.nodes[neighbor].get('lat', 0.0)
        lon_v = belief_graph.nodes[neighbor].get('lon', 0.0)
        dist_m = haversine_distance(lat_u, lon_u, lat_v, lon_v)
        
        from backend.config_params.parameters import params
        if dist_m <= max_range and max_range > 0:
            range_ratio = max(0.0, min(1.0, math.exp(-max(0.0, dist_m) / max(1e-5, max_range))))
            # Fetch visibility and LOS parameters
            edge_visibility = belief_graph.edges[node_id, neighbor].get('visibility_factor', 1.0)
            line_of_sight = 1.0 if belief_graph.edges[node_id, neighbor].get('has_los', True) else getattr(params, 'los_obstruction_factor', 0.3)
            
            # Combine range decay, edge visibility and LOS multipliers
            decay_gain_factor = getattr(params, 'scout_observation_decay_gain_factor', 0.85)
            gain = range_ratio * edge_visibility * line_of_sight * decay_gain_factor
            neigh_state = belief_graph.nodes[neighbor].get('p_state_correct', 0.5)
            belief_graph.nodes[neighbor]['p_state_correct'] = max(neigh_state, 1.0 - (1.0 - neigh_state) * (1.0 - (quality.eta * gain)))


