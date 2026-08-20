import networkx as nx
import numpy as np
from typing import Any, Dict, List, Optional, Tuple, Set
from backend.routing.confidence_dijkstra import find_confidence_route
from backend.uncertainty.information_gain import compute_global_ig
from backend.allocation.allocator import allocate_rescue_teams
from backend.agents.base_agent import AgentStatus
from backend.world_model.global_memory import gmm
from backend.config_params.parameters import params

class Coordinator:
    def __init__(self, base_node: str, egl: Optional[Any] = None) -> None:
        self.base_node = base_node
        self.egl = egl

    def assign_scouts(self, belief_graph: nx.Graph, idle_scouts: List[Any], weather_state: Optional[Dict[str, Any]] = None,
                      blackout_zones: List[Dict[str, float]] = [], forecasts: Dict[str, Any] = {},
                      disaster_type: str = "FLOOD", sim_time: float = 0.0, fleet_state: Dict[str, Any] = {}) -> List[Dict[str, Any]]:
        """Assigns idle scouts to targets using Rational Distance-Penalty matching (Cost-Benefit analysis).
        Formula: Cost = (Distance ^ 1.2) - (Urgency * 1000) + OverlapPenalty
        This prevents agents from driving across the entire city for a single threat.
        """
        # Maintain Cognitive Ledger
        if weather_state:
            gmm.log_weather(weather_state)
        if not idle_scouts:
            return []
            
        assignments: List[Dict[str, Any]] = []
        idle_scouts_list = list(idle_scouts)
        
        # --- RE-EVALUATE STAGED SCOUTS FIRST ---
        for scout in list(idle_scouts_list):
            if self.egl and self.egl.fcm.is_agent_staged(scout.id):
                decision = self.egl.re_evaluate_staged(
                    agent=scout,
                    belief_graph=belief_graph,
                    fleet_state=fleet_state,
                    blackout_zones=blackout_zones,
                    forecasts=forecasts,
                    disaster_type=disaster_type,
                    sim_time=sim_time
                )
                if decision and decision.outcome == "EXECUTE":
                    target_n = scout.staged_dispatch_target
                    path = []
                    if target_n and target_n in belief_graph:
                        try:
                            v_type = getattr(scout, 'vehicle_type', 'STANDARD_CAR')
                            cost_key = f'cost_{v_type}'
                            active_view = nx.subgraph_view(belief_graph, filter_edge=lambda u, v: belief_graph.edges[u, v].get(cost_key, 1e9) < 1e9)
                            if nx.has_path(active_view, scout.current_node, target_n):
                                full_p = nx.shortest_path(active_view, scout.current_node, target_n, weight='weight')
                                path = full_p[1:] if len(full_p) > 1 else []
                        except Exception:
                            path = []
                    if not path and scout.current_node in scout.full_planned_route:
                        try:
                            idx = scout.full_planned_route.index(scout.current_node)
                            path = scout.full_planned_route[idx + 1:]
                        except ValueError:
                            path = []
                    
                    if path and target_n:
                        assignments.append({
                            "scout_id": scout.id,
                            "target_node_id": target_n,
                            "path": path,
                            "full_route": [scout.current_node] + path
                        })
                    # Always clear staging fields when decision outcome is EXECUTE
                    scout.staged_dispatch_target = None
                    scout.staging_node = None
                elif decision and decision.outcome == "STAGED_EXECUTE":
                    # Staged dispatch continues: get the new staging node from FCM
                    staged_state = self.egl.fcm.get_staged_state(scout.id)
                    if staged_state:
                        staging_target = staged_state.staging_node
                        path = []
                        try:
                            v_type = getattr(scout, 'vehicle_type', 'STANDARD_CAR')
                            cost_key = f'cost_{v_type}'
                            active_view = nx.subgraph_view(belief_graph, filter_edge=lambda u, v: belief_graph.edges[u, v].get(cost_key, 1e9) < 1e9)
                            if nx.has_path(active_view, scout.current_node, staging_target):
                                full_p = nx.shortest_path(active_view, scout.current_node, staging_target, weight='weight')
                                path = full_p[1:] if len(full_p) > 1 else []
                        except Exception:
                            path = []
                        if not path and scout.current_node in scout.full_planned_route and staging_target in scout.full_planned_route:
                            try:
                                idx_curr = scout.full_planned_route.index(scout.current_node)
                                idx_stage = scout.full_planned_route.index(staging_target)
                                path = scout.full_planned_route[idx_curr + 1:idx_stage + 1]
                            except ValueError:
                                path = []
                        if path:
                            assignments.append({
                                "scout_id": scout.id,
                                "target_node_id": staging_target,
                                "path": path,
                                "full_route": [scout.current_node] + path
                            })
                            scout.staged_dispatch_target = staged_state.target_node
                            scout.staging_node = staged_state.staging_node
                else:
                    # Staging aborted or deferred/escalated again
                    scout.staged_dispatch_target = None
                    scout.staging_node = None
                
                # Remove from idle list so it is not processed again this tick
                idle_scouts_list.remove(scout)
        
        # --- REACHABILITY-BASED AUTO-DISPATCH (ISOLATION CHECK) ---
        try:
            active_edges_view = nx.subgraph_view(belief_graph, filter_edge=lambda u, v: not belief_graph.edges[u, v].get('blocked', False))
            isolated_population_nodes = []
            for n_id, ndata in belief_graph.nodes(data=True):
                if ndata.get('population', 0) > 0 and n_id != self.base_node:
                    if not nx.has_path(active_edges_view, self.base_node, n_id):
                        isolated_population_nodes.append(n_id)
            
            if isolated_population_nodes and idle_scouts_list:
                base_component = nx.descendants(active_edges_view, self.base_node)
                base_component.add(self.base_node)
                
                for target_id in isolated_population_nodes:
                    if not idle_scouts_list:
                        break
                    isolated_component = nx.descendants(active_edges_view, target_id)
                    isolated_component.add(target_id)
                    
                    bridging_edges = []
                    for u in isolated_component:
                        for v in belief_graph.neighbors(u):
                            if v in base_component:
                                bridging_edges.append((v, u))
                                
                    if bridging_edges:
                        best_scout = None
                        best_edge = None
                        best_path = None
                        min_dist = float('inf')
                        
                        for scout in idle_scouts_list:
                            scout_loc = scout.current_node
                            v_type = getattr(scout, 'vehicle_type', 'STANDARD_CAR')
                            w_key = f'cost_{v_type}'
                            
                            for v_node, u_node in bridging_edges:
                                if nx.has_path(active_edges_view, scout_loc, v_node):
                                    try:
                                        path = nx.shortest_path(active_edges_view, scout_loc, v_node, weight=w_key)
                                        d = sum(belief_graph.edges[path[i], path[i+1]].get('distance', 1.0) for i in range(len(path)-1))
                                        if d < min_dist:
                                            min_dist = d
                                            best_scout = scout
                                            best_edge = (v_node, u_node)
                                            best_path = path
                                    except Exception:
                                        continue
                                        
                        if best_scout and best_edge and best_path:
                            assignments.append({
                                "scout_id": best_scout.id,
                                "target_node_id": best_edge[0],
                                "path": best_path[1:] if len(best_path) > 1 else best_path
                            })
                            idle_scouts_list.remove(best_scout)
        except Exception as ex:
            print(f"[Auto-Dispatch] Error checking reachability / isolation: {ex}")
            
        # Calculate GlobalIG for all nodes
        global_ig = compute_global_ig(belief_graph)
        
        # Filter target candidates (high information gain)
        # Exclude base node, and only target nodes with substantial uncertainty
        # Also strictly exclude nodes with dist_to_water <= 0 (sometimes ocean/island edges)
        # to prevent straight lines across the ocean.
        locked_targets = self.egl.fcm.active_targets if self.egl else set()
        targets = [
            n_id for n_id, ig_val in global_ig.items()
            if ig_val > getattr(params, 'scout_ig_threshold', 0.05)
            and n_id != self.base_node
            and n_id not in locked_targets
        ]
        
        # Track edges assigned in this step to penalize overlapping routes
        assigned_edges: Set[Tuple[Any, Any]] = set()

        # Calculate map-size based dynamic phases
        node_count = len(belief_graph.nodes)
        phase_1_radius = 2500
        if node_count > 5000:
            phase_1_radius = 4500  # Massive map
        elif node_count < 1000:
            phase_1_radius = 1500  # Small grid

        # Boost priority if weather is severe (p_danger > 0.75)
        is_severe_weather = False
        if weather_state and (weather_state.get('rain_intensity', 0) > 80 or weather_state.get('storm_category', 0) >= 3):
            is_severe_weather = True

        for target_id in list(targets):
            danger_lvl = belief_graph.nodes[target_id].get('p_danger', 0)
            if is_severe_weather and danger_lvl > 0.75:
                global_ig[target_id] = global_ig.get(target_id, 0) + 1.5  # Artificial boost

        # State-Memory Cache to prevent lag from redundant graph traversals
        dijkstra_cache: Dict[str, Tuple[Dict[Any, float], Dict[Any, List[Any]]]] = {}

        # Assign scouts using a Phased Sector Sweep
        scouts = sorted(idle_scouts_list, key=lambda s: s.id)
        for scout in scouts:
            scout_loc = scout.current_node
            vehicle_type = getattr(scout, 'vehicle_type', 'STANDARD_CAR')
            weight_key = f'cost_{vehicle_type}'
            cache_key = f"{scout_loc}_{weight_key}"
            
            if cache_key not in dijkstra_cache:
                try:
                    lengths, paths = nx.single_source_dijkstra(belief_graph, scout_loc, weight=weight_key)
                    dijkstra_cache[cache_key] = (lengths, paths)
                except Exception:
                    dijkstra_cache[cache_key] = ({}, {})
                    
            full_lengths, full_paths = dijkstra_cache[cache_key]

            # Asymmetrical Human-like Danger Assessment
            # If the scout is physically near a severe catastrophe (high danger + population),
            # restrict their sweep radius severely so they focus ONLY on local emergencies.
            # Otherwise, allow them to execute massive map-scale sweeps.
            is_local_emergency = False
            for target_id in targets:
                if target_id in full_lengths and full_lengths[target_id] < 1000:
                    danger = belief_graph.nodes[target_id].get('p_danger', 0)
                    pop = belief_graph.nodes[target_id].get('population', 0)
                    if danger > 0.65 and pop > 10:
                        is_local_emergency = True
                        break
            
            # Dynamically restrict radius asymmetrically per unit
            active_radius = 800 if is_local_emergency else phase_1_radius

            # Filter targets to only those reachable within this unit's asymmetrical radius constraint
            local_targets = [t for t in targets if t in full_lengths and full_lengths[t] <= active_radius]
            
            # If no local targets, expand to global to ensure we don't stall
            if not local_targets:
                local_targets = [t for t in targets if t in full_lengths]

            # Sort local targets by information gain descending
            local_targets = sorted(local_targets, key=lambda t: global_ig.get(t, 0), reverse=True)
            available_targets = list(local_targets[:200])

            if not available_targets:
                continue
            
            full_path = [scout_loc]
            current_loc = scout_loc
            targets_to_visit: List[Any] = []
            
            for _ in range(5):  # Generate a multi-stop sweep of 5 targets
                if not available_targets:
                    break
                    
                loop_cache_key = f"{current_loc}_{weight_key}"
                if loop_cache_key not in dijkstra_cache:
                    try:
                        lengths, paths = nx.single_source_dijkstra(belief_graph, current_loc, cutoff=active_radius * 2.0, weight=weight_key)
                        dijkstra_cache[loop_cache_key] = (lengths, paths)
                    except Exception:
                        break
                lengths, paths = dijkstra_cache[loop_cache_key]
                    
                candidate_targets: List[Tuple[Any, float, float, float]] = []
                for target_id in available_targets:
                    if target_id == current_loc or target_id not in lengths:
                        continue
                        
                    # Validate against Persistent Ledger to prevent redundant scans
                    if gmm.is_cleared(target_id):
                        continue
                        
                    dist = lengths[target_id]
                    ig_val = global_ig.get(target_id, 0.0)
                    
                    # Linear distance scaling allows wide map exploration
                    scout_exponent = getattr(params, 'scout_distance_exponent', 1.0)
                    scout_ig_weight = getattr(params, 'scout_ig_weight', 5000.0)
                    raw_cost = (dist ** scout_exponent) - (ig_val * scout_ig_weight)
                    candidate_targets.append((target_id, dist, ig_val, raw_cost))
                    
                candidate_targets.sort(key=lambda x: x[3])
                top_candidates = candidate_targets[:20] # Bounded candidates for fast multi-stop sweep
                
                best_cost = float('inf')
                best_target: Optional[Any] = None
                best_path: Optional[List[Any]] = None
                
                for target_id, dist, ig_val, _ in top_candidates:
                    path = paths.get(target_id)
                    if not path:
                        continue
                    
                    # Calculate path overlap and check for known blockages
                    overlap_count = 0
                    path_is_blocked = False
                    for i in range(len(path) - 1):
                        u, v = path[i], path[i+1]
                        if belief_graph.edges[u, v].get('blocked', False):
                            path_is_blocked = True
                            break
                        if (u, v) in assigned_edges or (v, u) in assigned_edges:
                            overlap_count += 1
                            
                    if path_is_blocked:
                        continue
                    
                    # Rational Assignment Cost with Overlap Penalty
                    scout_overlap_penalty = getattr(params, 'scout_overlap_penalty', 2500.0)
                    cost = (dist ** scout_exponent) - (ig_val * scout_ig_weight) + (overlap_count * scout_overlap_penalty)
                    
                    if cost < best_cost:
                        best_cost = cost
                        best_target = target_id
                        best_path = path
                        
                if best_target:
                    # Note: clearance is logged upon physical arrival in _reached_target, not at dispatch time!
                    gmm.danger_history[best_target] = belief_graph.nodes[best_target].get('p_danger', 0)
                    
                    targets_to_visit.append(best_target)
                    if best_path and len(best_path) > 1:
                        full_path.extend(best_path[1:])
                    # Add edges to set of assigned edges to disperse subsequent scouts
                    if best_path:
                        for i in range(len(best_path) - 1):
                            assigned_edges.add((best_path[i], best_path[i+1]))
                    available_targets.remove(best_target)
                    current_loc = best_target
                else:
                    break
                    
            if len(full_path) > 1:
                target_node = targets_to_visit[-1] if targets_to_visit else scout_loc
                path = full_path[1:]
                
                if self.egl:
                    decision = self.egl.evaluate(
                        action_class="SCOUT_DISPATCH",
                        agent=scout,
                        target_node=target_node,
                        route=full_path,
                        belief_graph=belief_graph,
                        fleet_state=fleet_state,
                        blackout_zones=blackout_zones,
                        forecasts=forecasts,
                        disaster_type=disaster_type,
                        sim_time=sim_time
                    )
                    
                    if decision.outcome in ("DEFER", "ESCALATE"):
                        # If EGL deferred or escalated, we do NOT dispatch
                        continue
                        
                    if decision.outcome == "STAGED_EXECUTE":
                        # Staged dispatch: FCM registered staging, now adjust path
                        staged_state = self.egl.fcm.get_staged_state(scout.id)
                        if staged_state and staged_state.staging_node in full_path:
                            idx = full_path.index(staged_state.staging_node)
                            # Truncate path up to staging node
                            path = full_path[1:idx + 1]
                            target_node = staged_state.staging_node
                            scout.staged_dispatch_target = staged_state.target_node
                            scout.staging_node = staged_state.staging_node

                assignments.append({
                    "scout_id": scout.id,
                    "target_node_id": target_node,
                    "path": path,
                    "full_route": list(full_path)
                })
                
        return assignments

    def assign_rescues(self, belief_graph: nx.Graph, idle_rescues: List[Any], weather_state: Optional[Dict[str, Any]] = None,
                       blackout_zones: List[Dict[str, float]] = [], forecasts: Dict[str, Any] = {},
                       disaster_type: str = "FLOOD", sim_time: float = 0.0, fleet_state: Dict[str, Any] = {},
                       baseline_type: str = "AMIS-RU") -> List[Dict[str, Any]]:
        """Assigns idle rescue teams using GEVA or Naive Shortest Distance."""
        if not idle_rescues:
            return []
            
        RESCUABLE_TYPES = {"POPULATION_ZONE", "BRIDGE", "JUNCTION"}
        locked_targets = set()
        if self.egl:
            for t_id in self.egl.fcm.active_targets:
                t_pop = belief_graph.nodes.get(t_id, {}).get('population', 0)
                if self.egl.fcm.check_mutex(t_id, target_pop=t_pop):
                    locked_targets.add(t_id)

        targets = [
            n_id for n_id, data in belief_graph.nodes(data=True)
            if data.get('node_type') in RESCUABLE_TYPES
            and data.get('population', 0) > 0
            and n_id not in locked_targets
        ]

        
        # Weather-driven sorting
        is_severe_weather = False
        if weather_state and (weather_state.get('rain_intensity', 0) > 80 or weather_state.get('storm_category', 0) >= 3):
            is_severe_weather = True
            
        def urgency_score(t: Any) -> float:
            p_d = max(0.15, float(belief_graph.nodes[t].get('p_danger', 0.0) or 0.0))
            base_urgency = belief_graph.nodes[t].get('population', 0) * p_d
            if is_severe_weather and float(belief_graph.nodes[t].get('p_danger', 0.0) or 0.0) > 0.75:
                base_urgency *= 2.0  # Double urgency for high danger zones in severe weather
            return float(base_urgency)
            
        targets = sorted(targets, key=urgency_score, reverse=True)
        targets = targets[:200]

        # Re-evaluate staged rescue teams first
        staged_teams_processed = set()
        assignments: List[Dict[str, Any]] = []

        for agent in list(idle_rescues):
            if self.egl and self.egl.fcm.is_agent_staged(agent.id):
                staged_teams_processed.add(agent.id)
                decision = self.egl.re_evaluate_staged(
                    agent=agent,
                    belief_graph=belief_graph,
                    fleet_state=fleet_state,
                    blackout_zones=blackout_zones,
                    forecasts=forecasts,
                    disaster_type=disaster_type,
                    sim_time=sim_time
                )
                if decision and decision.outcome == "EXECUTE":
                    target_n = agent.staged_dispatch_target
                    path = []
                    if target_n and target_n in belief_graph:
                        try:
                            v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR')
                            cost_key = f'cost_{v_type}'
                            active_view = nx.subgraph_view(belief_graph, filter_edge=lambda u, v: belief_graph.edges[u, v].get(cost_key, 1e9) < 1e9)
                            if nx.has_path(active_view, agent.current_node, target_n):
                                full_p = nx.shortest_path(active_view, agent.current_node, target_n, weight='weight')
                                path = full_p[1:] if len(full_p) > 1 else []
                        except Exception:
                            path = []
                    if not path and agent.current_node in agent.full_planned_route:
                        try:
                            idx = agent.full_planned_route.index(agent.current_node)
                            path = agent.full_planned_route[idx + 1:]
                        except ValueError:
                            path = []
                    
                    if path and target_n:
                        assignments.append({
                            "team_id": agent.id,
                            "target_node_id": target_n,
                            "path": path,
                            "ev": 0.0,
                            "distance": 0.0,
                            "full_route": [agent.current_node] + path
                        })
                    # Always clear staging fields when decision outcome is EXECUTE
                    agent.staged_dispatch_target = None
                    agent.staging_node = None
                elif decision and decision.outcome == "STAGED_EXECUTE":
                    # Staged dispatch continues: get the new staging node from FCM
                    staged_state = self.egl.fcm.get_staged_state(agent.id)
                    if staged_state:
                        staging_target = staged_state.staging_node
                        path = []
                        try:
                            v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR')
                            cost_key = f'cost_{v_type}'
                            active_view = nx.subgraph_view(belief_graph, filter_edge=lambda u, v: belief_graph.edges[u, v].get(cost_key, 1e9) < 1e9)
                            if nx.has_path(active_view, agent.current_node, staging_target):
                                full_p = nx.shortest_path(active_view, agent.current_node, staging_target, weight='weight')
                                path = full_p[1:] if len(full_p) > 1 else []
                        except Exception:
                            path = []
                        if not path and agent.current_node in agent.full_planned_route and staging_target in agent.full_planned_route:
                            try:
                                idx_curr = agent.full_planned_route.index(agent.current_node)
                                idx_stage = agent.full_planned_route.index(staging_target)
                                path = agent.full_planned_route[idx_curr + 1:idx_stage + 1]
                            except ValueError:
                                path = []
                        if path:
                            assignments.append({
                                "team_id": agent.id,
                                "target_node_id": staging_target,
                                "path": path,
                                "ev": 0.0,
                                "distance": 0.0,
                                "full_route": [agent.current_node] + path
                            })
                            agent.staged_dispatch_target = staged_state.target_node
                            agent.staging_node = staged_state.staging_node
                else:
                    # Aborted or deferred/escalated again — allow agent to join general allocation pool
                    agent.staged_dispatch_target = None
                    agent.staging_node = None
                    staged_teams_processed.discard(agent.id)


        # Convert rescue agents list to list of dicts for allocator, excluding staged
        idle_teams_dict = [
            {
                "id": r.id, 
                "current_node": r.current_node,
                "vehicle_type": getattr(r, 'vehicle_type', 'STANDARD_CAR')
            }
            for r in idle_rescues if r.id not in staged_teams_processed
        ]
        
        raw_assignments = allocate_rescue_teams(belief_graph, idle_teams_dict, targets, disaster_type, baseline_type=baseline_type)

        # Now process new allocations from allocator
        for assign in raw_assignments:
            team_id = assign["team_id"]
            if team_id in staged_teams_processed:
                continue
                
            agent = next((a for a in idle_rescues if a.id == team_id), None)
            if not agent:
                continue
            agent._logged_route_failure = False

                
            target_node = assign["target_node_id"]
            path = assign["path"]
            full_route = [agent.current_node] + path
            
            # Action class for rescue dispatch is RESCUE_DISPATCH or HELICOPTER_AIRLIFT depending on vehicle type
            action_class = "RESCUE_DISPATCH"
            v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR')
            if v_type == "HELICOPTER":
                action_class = "HELICOPTER_AIRLIFT"
                
            if self.egl:
                decision = self.egl.evaluate(
                    action_class=action_class,
                    agent=agent,
                    target_node=target_node,
                    route=full_route,
                    belief_graph=belief_graph,
                    fleet_state=fleet_state,
                    blackout_zones=blackout_zones,
                    forecasts=forecasts,
                    disaster_type=disaster_type,
                    sim_time=sim_time
                )
                
                if decision.outcome in ("DEFER", "ESCALATE"):
                    # Free GMM capacity for the deferred target
                    from backend.agents.fleet_config import FLEET_SPECIFICATIONS
                    spec = FLEET_SPECIFICATIONS.get(v_type, {})
                    vehicle_cap = spec.get("capacity", 50)
                    gmm.free_capacity(target_node, vehicle_cap)
                    
                    # Try fallback targets in order of urgency/EV score
                    # Fix 6: Cap at MAX_FALLBACK_ATTEMPTS to prevent tick-waste
                    MAX_FALLBACK_ATTEMPTS = 5
                    fallback_found = False
                    fallback_attempts = 0
                    for fallback_target in targets:
                        if fallback_target == target_node:
                            continue
                        pop_fb = belief_graph.nodes[fallback_target].get('population', 0)
                        if gmm.get_remaining_demand(fallback_target, pop_fb) <= 0:
                            continue
                        
                        weight_key = f'cost_{v_type}'
                        try:
                            costs_fb, paths_fb = nx.single_source_dijkstra(belief_graph, agent.current_node, target=fallback_target, weight=weight_key)
                            path_fb = paths_fb.get(fallback_target)
                            if not path_fb or len(path_fb) < 2:
                                continue
                            path_only = path_fb[1:]
                            full_route_fb = path_fb
                        except Exception:
                            continue
                            
                        fb_decision = self.egl.evaluate(
                            action_class=action_class,
                            agent=agent,
                            target_node=fallback_target,
                            route=full_route_fb,
                            belief_graph=belief_graph,
                            fleet_state=fleet_state,
                            blackout_zones=blackout_zones,
                            forecasts=forecasts,
                            disaster_type=disaster_type,
                            sim_time=sim_time
                        )
                        
                        if fb_decision.outcome not in ("DEFER", "ESCALATE"):
                            target_node = fallback_target
                            path = path_only
                            full_route = full_route_fb
                            decision = fb_decision
                            gmm.allocate_capacity(fallback_target, vehicle_cap)
                            fallback_found = True
                            break
                        
                        fallback_attempts += 1
                        if fallback_attempts >= MAX_FALLBACK_ATTEMPTS:
                            # Anti-starvation: force-assign this target rather than idle
                            target_node = fallback_target
                            path = path_only
                            full_route = full_route_fb
                            decision = fb_decision
                            gmm.allocate_capacity(fallback_target, vehicle_cap)
                            fallback_found = True
                            break
                            
                    if not fallback_found:
                        continue
                    
                if decision.outcome == "STAGED_EXECUTE":
                    staged_state = self.egl.fcm.get_staged_state(agent.id)
                    if staged_state and staged_state.staging_node in full_route:
                        idx = full_route.index(staged_state.staging_node)
                        path = full_route[1:idx + 1]
                        target_node = staged_state.staging_node
                        agent.staged_dispatch_target = staged_state.target_node
                        agent.staging_node = staged_state.staging_node
                else:
                    agent.staged_dispatch_target = None
                    agent.staging_node = None

            
            assignments.append({
                "team_id": team_id,
                "target_node_id": target_node,
                "path": path,
                "ev": assign.get("ev", 0.0),
                "distance": assign.get("distance", 0.0),
                "full_route": list(full_route)
            })
            
        return assignments
 
    def find_nearest_safe_haven(self, belief_graph: nx.Graph, source_node: str, needs_medical: bool = False, vehicle_type: str = "STANDARD_CAR") -> Optional[List[str]]:
        """Finds the path to the nearest shelter or hospital that is traversable and active."""
        if needs_medical:
            # Injured survivors requiring medical attention must be routed to an open, working hospital
            safe_havens = [
                n_id for n_id, data in belief_graph.nodes(data=True)
                if data.get('node_type') == "HOSPITAL"
                and data.get('status') not in ("BLOCKED", "COMPROMISED", "FLOODED")
            ]
        else:
            safe_havens = [
                n_id for n_id, data in belief_graph.nodes(data=True)
                if data.get('node_type') in ["SHELTER", "HOSPITAL"]
                and data.get('status') not in ("BLOCKED", "COMPROMISED", "FLOODED")
            ]
        if self.base_node and self.base_node not in safe_havens:
            safe_havens.append(self.base_node)
        
        if not safe_havens:
            return None
        
        havens_with_supplies: List[str] = []
        for haven_id in safe_havens:
            res = belief_graph.nodes[haven_id].get('resources', {})
            if res.get('food', 100) >= 5.0 and res.get('water', 100) >= 5.0:
                havens_with_supplies.append(haven_id)
            elif haven_id == self.base_node:
                havens_with_supplies.append(haven_id)
            
        target_havens = havens_with_supplies if havens_with_supplies else safe_havens
        
        best_path: Optional[List[str]] = None
        min_dist = float('inf')
        cost_cache: Dict[str, float] = {}
        
        for haven_id in target_havens:
            route_info = find_confidence_route(belief_graph, source_node, haven_id, vehicle_type, cost_cache)
            if route_info:
                path, dist, _ = route_info
                if dist < min_dist:
                    min_dist = dist
                    best_path = path
                    
        return best_path
