import networkx as nx
from backend.routing.confidence_dijkstra import find_confidence_route
from backend.allocation.geva import calculate_ev, get_vulnerability_multiplier
from backend.config import settings
from backend.world_model.global_memory import gmm

def compute_reachability(graph: nx.Graph, path: list) -> float:
    """Reachability is the product of edge confidences along the route."""
    if not path or len(path) < 2:
        return 1.0
        
    reachability = 1.0
    for i in range(len(path) - 1):
        u, v = path[i], path[i+1]
        confidence = graph.edges[u, v].get('confidence', 1.0)
        reachability *= confidence
        
    return reachability

def allocate_rescue_teams(belief_graph: nx.Graph, idle_teams: list, target_nodes: list, disaster_type: str = "FLOOD", baseline_type: str = "AMIS-RU") -> list:
    assignments = []
    available_targets = list(target_nodes)  # Copy targets list
    
    # Sort teams to make assignment deterministic
    teams = sorted(idle_teams, key=lambda t: t['id'])
    
    # NAIVE BASELINE (BASELINE-B / PSA-RA): Naive greedy shortest distance assignment (no GEVA, no EV, no overlap penalty)
    if baseline_type in ("BASELINE-B", "PSA-RA"):
        for team in teams:
            if not available_targets:
                break
                
            team_loc = team['current_node']
            vehicle_type = team.get('vehicle_type', 'STANDARD_CAR')
            
            try:
                # Naive distance-only Dijkstra shortest path
                costs, paths = nx.single_source_dijkstra(belief_graph, team_loc, weight='distance')
            except Exception:
                costs, paths = {}, {}
                
            best_target = None
            best_dist = 999999999.0
            best_path = None
            
            for target_id in available_targets:
                target_data = belief_graph.nodes[target_id]
                pop = target_data.get('population', 0)
                remaining_demand = gmm.get_remaining_demand(target_id, pop)
                
                if remaining_demand > 0 and target_id in costs:
                    dist_val = costs[target_id]
                    if dist_val < best_dist:
                        best_dist = dist_val
                        best_target = target_id
                        best_path = paths.get(target_id)
                        
            if best_target and best_path:
                assignments.append({
                    "team_id": team['id'],
                    "target_node_id": best_target,
                    "path": best_path,
                    "distance": best_dist,
                    "ev": 1.0
                })
                
                from backend.agents.fleet_config import FLEET_SPECIFICATIONS
                spec = FLEET_SPECIFICATIONS.get(vehicle_type, {})
                vehicle_cap = spec.get("capacity", 50)
                gmm.allocate_capacity(best_target, vehicle_cap)
                
                target_data = belief_graph.nodes[best_target]
                pop = target_data.get('population', 0)
                if gmm.get_remaining_demand(best_target, pop) <= 0:
                    available_targets.remove(best_target)
                    
        return assignments

    # FULL GEVA ALLOCATOR (AMIS-RU & SGA-RA)
    # Track edges assigned to teams in this allocation cycle to penalize overlapping routes
    assigned_edges = set()
    cache_dijkstra = {}
    
    for team in teams:
        if not available_targets:
            break
            
        best_ev = -999999.0
        best_target = None
        best_path = None
        best_dist = 0.0
        
        team_loc = team['current_node']
        vehicle_type = team.get('vehicle_type', 'STANDARD_CAR')
        base_speed = getattr(team, 'speed', settings.RESCUE_SPEED)
        weight_key = f'cost_{vehicle_type}'

        cache_key = (team_loc, weight_key)
        if cache_key not in cache_dijkstra:
            try:
                costs, paths = nx.single_source_dijkstra(belief_graph, team_loc, weight=weight_key)
                cache_dijkstra[cache_key] = (costs, paths)
            except Exception as dijk_err:
                print(f"[Allocator] Warning: Dijkstra path search failed for team location {team_loc} ({vehicle_type}): {dijk_err}")
                cache_dijkstra[cache_key] = ({}, {})
        costs, paths = cache_dijkstra[cache_key]
            
        candidate_targets = []
        for target_id in available_targets:
            target_data = belief_graph.nodes[target_id]
            pop = target_data.get('population', 0)
            
            # Swarm Capacity Check via GMM
            remaining_demand = gmm.get_remaining_demand(target_id, pop)
            
            if remaining_demand > 0 and target_id in costs and costs[target_id] < 1e8:
                candidate_targets.append((target_id, costs[target_id]))
                
        # If no hazard-free path exists, fall back to distance-based perimeter routing so vehicles don't sit idle
        if not candidate_targets:
            try:
                costs_fb, paths_fb = nx.single_source_dijkstra(belief_graph, team_loc, weight='distance')
                for target_id in available_targets:
                    target_data = belief_graph.nodes[target_id]
                    pop = target_data.get('population', 0)
                    if gmm.get_remaining_demand(target_id, pop) > 0 and target_id in costs_fb:
                        candidate_targets.append((target_id, costs_fb[target_id]))
                if candidate_targets:
                    costs, paths = costs_fb, paths_fb
            except Exception:
                pass

        best_ev = -999999.0
        best_target = None
        best_path = None
        best_dist = 0.0

        for target_id in available_targets:
            target_data = belief_graph.nodes[target_id]
            pop = target_data.get('population', 0)
            if pop <= 0:
                continue
                
            remaining_demand = gmm.get_remaining_demand(target_id, pop)
            if remaining_demand <= 0:
                continue
                
            path = paths.get(target_id)
            if not path or len(path) < 2:
                continue
                
            cost_val = costs.get(target_id, 1e9)
            if cost_val >= 1e8:
                continue

            p_danger_current = target_data.get('p_danger', 0.0)
            forecasted_danger = target_data.get('forecasted_p_danger', None)
            
            # Forecasted danger increases urgency rather than destroying expected survivors
            urgency_boost = 1.0
            if forecasted_danger is not None and forecasted_danger > p_danger_current:
                urgency_boost = 1.0 + 0.5 * (forecasted_danger - p_danger_current)

            reachability = compute_reachability(belief_graph, path)

            total_dist_m = 0.0
            t_arrival = 0.0
            overlap_dist_m = 0.0

            from backend.agents.fleet_config import get_effective_speed
            for i in range(len(path) - 1):
                u, v = path[i], path[i+1]
                edge_data = belief_graph.edges[u, v]
                d = edge_data.get('distance', 1.0)
                total_dist_m += d
                
                wl_u = belief_graph.nodes[u].get('water_level', 0.0)
                wl_v = belief_graph.nodes[v].get('water_level', 0.0)
                elev_u = belief_graph.nodes[u].get('effective_elevation', belief_graph.nodes[u].get('elevation', 10.0))
                elev_v = belief_graph.nodes[v].get('effective_elevation', belief_graph.nodes[v].get('elevation', 10.0))
                water_lvl = max(max(0.0, wl_u - elev_u), max(0.0, wl_v - elev_v))

                is_blk = edge_data.get('blocked', False)
                is_c = edge_data.get('rubble_cleared', False)
                p_danger_edge = (belief_graph.nodes[u].get('p_danger', 0.0) + belief_graph.nodes[v].get('p_danger', 0.0)) / 2.0
                eff_s = get_effective_speed(vehicle_type, base_speed, water_lvl, is_blk, disaster_type=disaster_type, p_danger=p_danger_edge, is_cleared=is_c)


                if eff_s <= 0.0:
                    t_arrival = 1e9
                    break
                sf = edge_data.get('speed_factor', 1.0)
                eff = max(0.1, eff_s * sf)
                t_arrival += (d / eff) / 60.0

                if (u, v) in assigned_edges or (v, u) in assigned_edges:
                    overlap_dist_m += d

            if t_arrival >= 1e8:
                continue

            vulnerability_multiplier = get_vulnerability_multiplier(target_data)
            p_state_correct = target_data.get('p_state_correct', 0.5)
            
            ev = calculate_ev(p_danger_current, pop, reachability, t_arrival, vulnerability_multiplier, p_state_correct, disaster_type)
            ev *= urgency_boost
            ev -= (overlap_dist_m / 1000.0) * 0.5

            # EV Rate: Expected lives saved per minute of operational time (2.0 min standard patient loading)
            load_time = 2.0
            ev_rate = ev / (t_arrival + load_time)


            if ev_rate > best_ev:
                best_ev = ev_rate
                best_target = target_id
                best_dist = total_dist_m
                best_path = path



                
        # Assign if we found a valid route and target with reasonable EV
        if best_target and best_ev > -9999.0:
            assignments.append({
                "team_id": team['id'],
                "target_node_id": best_target,
                "path": best_path,
                "distance": best_dist,
                "ev": best_ev
            })
            for i in range(len(best_path) - 1):
                assigned_edges.add((best_path[i], best_path[i+1]))
                
            from backend.agents.fleet_config import FLEET_SPECIFICATIONS
            spec = FLEET_SPECIFICATIONS.get(vehicle_type, {})
            vehicle_cap = spec.get("capacity", 50)
            gmm.allocate_capacity(best_target, vehicle_cap)
            
            target_data = belief_graph.nodes[best_target]
            pop = target_data.get('population', 0)
            if gmm.get_remaining_demand(best_target, pop) <= 0:
                available_targets.remove(best_target)
            
    return assignments
