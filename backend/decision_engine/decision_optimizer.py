import networkx as nx
import math
from typing import List, Dict, Any, Tuple, Optional
from backend.routing.confidence_dijkstra import find_confidence_route
from backend.agents.fleet_config import FLEET_SPECIFICATIONS

class DecisionOptimizer:
    """
    Solves multi-criteria coordination, assigning specialized vehicles to targets
    based on path confidence, travel times, vehicle capacity, and disaster-specific hazards.
    Computes a ranked list of top 5 decision alternatives under a multi-objective paradigm,
    including Mission Outcome Utility Forecasting and multi-objective scoring.
    """

    @classmethod
    def optimize_assignments(
        cls,
        belief_graph: nx.Graph,
        targets: List[str],
        vehicles: List[Dict[str, Any]],  # List of dicts: {"id": str, "location": str, "type": str}
        disaster_type: str = "FLOOD"
    ) -> List[Dict[str, Any]]:
        """
        Coordinates vehicle-to-target assignment.
        Returns a ranked list of top 5 decision alternatives:
        1. Balanced Objective Portfolio
        2. Maximize Lives Saved (Triage Urgency) Portfolio
        3. Risk Averse (Max Confidence / Min Hazard) Portfolio
        4. Rapid Response (Min Transit Time) Portfolio
        5. High Target Coverage Portfolio
        """
        if not targets or not vehicles:
            return []

        # Objective Weight Configurations
        # Weights: (w_lives, w_time, w_confidence, w_coverage)
        weight_configs = {
            "balanced": {
                "name": "Balanced Objective Portfolio",
                "weights": (1.0, 0.5, 0.8, 0.5),
                "desc": "Balances emergency urgency, rescue speed, and route safety."
            },
            "max_lives": {
                "name": "Aggressive Rescue (Maximize Lives Saved)",
                "weights": (2.5, 0.2, 0.3, 0.2),
                "desc": "Prioritizes immediate high-casualty targets despite higher terrain/path risks."
            },
            "risk_averse": {
                "name": "Risk Averse (Maximize Path Confidence & Safety)",
                "weights": (0.4, 0.3, 2.0, 0.6),
                "desc": "Selects highly reliable routes with verified clearances and low hazard exposure."
            },
            "rapid_response": {
                "name": "Rapid Response (Minimize Transit Time)",
                "weights": (0.6, 2.2, 0.4, 0.3),
                "desc": "Prioritizes the fastest arrival times and closest vehicle deployments."
            },
            "max_coverage": {
                "name": "High Target Coverage Portfolio",
                "weights": (0.8, 0.4, 0.6, 1.8),
                "desc": "Spreads resources across the widest set of communities to maximize assistance footprint."
            }
        }

        FUEL_RATES = {
            "HELICOPTER": 5.0,
            "HIGH_WATER_TRUCK": 2.0,
            "ZODIAC_BOAT": 1.5,
            "STANDARD_CAR": 1.0
        }

        alternatives = []

        # Precompute feasible routes for all (vehicle, target) pairs to speed up optimization
        route_cache = {}
        for vehicle in vehicles:
            v_id = vehicle["id"]
            v_loc = vehicle["location"]
            v_type = vehicle["type"]
            spec = FLEET_SPECIFICATIONS.get(v_type, FLEET_SPECIFICATIONS["STANDARD_CAR"])
            
            for target in targets:
                route_res = find_confidence_route(belief_graph, source=v_loc, target=target, vehicle_type=v_type)
                if not route_res:
                    continue
                
                path, distance, avg_confidence = route_res
                
                # Physical constraint check (water level depth)
                max_water_on_path = 0.0
                for node_id in path:
                    ndata = belief_graph.nodes.get(node_id, {})
                    w_level = ndata.get("water_level") or 0.0
                    if w_level > max_water_on_path:
                        max_water_on_path = w_level

                if max_water_on_path > spec.get("max_water_depth", 99.0):
                    continue

                speed_mult = spec.get("speed_multiplier", 1.0)
                estimated_time_min = (distance / max(0.1, speed_mult * 10.0)) / 60.0  # minutes

                route_cache[(v_id, target)] = {
                    "path": path,
                    "distance": distance,
                    "avg_confidence": avg_confidence,
                    "time_min": estimated_time_min,
                    "spec": spec
                }

        # --- NSGA-II Inspired Optimizer Helper Functions ---
        def dominates(objs_p: Tuple[float, float, float, float], objs_q: Tuple[float, float, float, float]) -> bool:
            better = False
            for p_val, q_val in zip(objs_p, objs_q):
                if p_val < q_val:
                    return False
                if p_val > q_val:
                    better = True
            return better

        def fast_non_dominated_sort(pop: List[List[Optional[str]]], fit: Dict[int, Tuple[float, float, float, float]]) -> List[List[int]]:
            domination_sets = {i: set() for i in range(len(pop))}
            dominated_counts = {i: 0 for i in range(len(pop))}
            fronts = [[]]
            
            for p in range(len(pop)):
                for q in range(len(pop)):
                    if p == q:
                        continue
                    if dominates(fit[p], fit[q]):
                        domination_sets[p].add(q)
                    elif dominates(fit[q], fit[p]):
                        dominated_counts[p] += 1
                if dominated_counts[p] == 0:
                    fronts[0].append(p)
                    
            i = 0
            while len(fronts[i]) > 0:
                next_front = []
                for p in fronts[i]:
                    for q in domination_sets[p]:
                        dominated_counts[q] -= 1
                        if dominated_counts[q] == 0:
                            next_front.append(q)
                i += 1
                fronts.append(next_front)
            return fronts[:-1]

        def calculate_crowding_distance(front: List[int], fit: Dict[int, Tuple[float, float, float, float]]) -> Dict[int, float]:
            if not front:
                return {}
            distances = {p: 0.0 for p in front}
            num_objectives = len(fit[front[0]])
            
            for m in range(num_objectives):
                sorted_front = sorted(front, key=lambda p: fit[p][m])
                distances[sorted_front[0]] = float('inf')
                distances[sorted_front[-1]] = float('inf')
                
                min_val = fit[sorted_front[0]][m]
                max_val = fit[sorted_front[-1]][m]
                norm = max_val - min_val
                if norm == 0:
                    continue
                    
                for idx in range(1, len(sorted_front) - 1):
                    p = sorted_front[idx]
                    distances[p] += (fit[sorted_front[idx+1]][m] - fit[sorted_front[idx-1]][m]) / norm
            return distances

        def generate_greedy_individual(w_lives: float, w_time: float, w_confidence: float, w_coverage: float) -> List[Optional[str]]:
            assigned_vehicles = set()
            assigned_targets = set()
            individual: List[Optional[str]] = [None] * len(vehicles)
            
            pair_utilities = []
            for target in targets:
                t_data = belief_graph.nodes.get(target, {})
                triage_immediate = t_data.get("triage_immediate", 0) or 0
                triage_delayed = t_data.get("triage_delayed", 0) or 0
                triage_minor = t_data.get("triage_minor", 0) or 0
                population = t_data.get("population", 0) or 0
                raw_lives = (triage_immediate * 2.0) + (triage_delayed * 1.0) + (triage_minor * 0.2) + (population * 0.02)
                
                for idx, vehicle in enumerate(vehicles):
                    v_id = vehicle["id"]
                    if (v_id, target) not in route_cache:
                        continue
                    r_data = route_cache[(v_id, target)]
                    capacity = r_data["spec"].get("capacity", 5)
                    expected_lives_saved = min(raw_lives, capacity)
                    
                    time_penalty = r_data["time_min"]
                    conf = r_data["avg_confidence"]
                    
                    utility = (
                        w_lives * expected_lives_saved * 12.0 -
                        w_time * time_penalty * 2.5 +
                        w_confidence * conf * 15.0
                    )
                    pair_utilities.append((utility, target, idx))

            pair_utilities.sort(key=lambda x: x[0], reverse=True)
            for utility, target, idx in pair_utilities:
                v_id = vehicles[idx]["id"]
                if v_id not in assigned_vehicles and target not in assigned_targets:
                    individual[idx] = target
                    assigned_vehicles.add(v_id)
                    assigned_targets.add(target)
            return individual

        def evaluate_individual(individual: List[Optional[str]]):
            assigned_vehicles = set()
            assigned_targets = set()
            assignments = []
            
            for i, tgt in enumerate(individual):
                if tgt is None:
                    continue
                veh = vehicles[i]
                v_id = veh["id"]
                if (v_id, tgt) not in route_cache:
                    continue
                
                if v_id in assigned_vehicles or tgt in assigned_targets:
                    continue
                
                r_data = route_cache[(v_id, tgt)]
                t_data = belief_graph.nodes.get(tgt, {})
                triage_immediate = t_data.get("triage_immediate", 0) or 0
                triage_delayed = t_data.get("triage_delayed", 0) or 0
                triage_minor = t_data.get("triage_minor", 0) or 0
                population = t_data.get("population", 0) or 0
                
                raw_lives = (triage_immediate * 2.0) + (triage_delayed * 1.0) + (triage_minor * 0.2) + (population * 0.02)
                capacity = r_data["spec"].get("capacity", 5)
                expected_lives_saved = min(raw_lives, capacity)
                
                assignments.append({
                    "target_node": tgt,
                    "vehicle_id": v_id,
                    "vehicle_type": veh["type"],
                    "path": r_data["path"],
                    "distance": r_data["distance"],
                    "path_confidence": r_data["avg_confidence"],
                    "estimated_time_minutes": r_data["time_min"],
                    "expected_lives_saved": expected_lives_saved
                })
                
                assigned_vehicles.add(v_id)
                assigned_targets.add(tgt)

            total_lives_saved = sum(a["expected_lives_saved"] for a in assignments)
            avg_time = sum(a["estimated_time_minutes"] for a in assignments) / max(1, len(assignments))
            avg_conf = sum(a["path_confidence"] for a in assignments) / max(1, len(assignments))
            coverage_ratio = len(assigned_targets) / max(1, len(targets))
            risk_score = sum(1.0 - a["path_confidence"] for a in assignments) / max(1, len(assignments))

            total_fuel = 0.0
            for a in assignments:
                v_type = a["vehicle_type"]
                dist_km = a["distance"] / 1000.0
                rate = FUEL_RATES.get(v_type, 1.0)
                total_fuel += dist_km * rate

            success_prob = 1.0
            for a in assignments:
                success_prob *= a["path_confidence"]
            if not assignments:
                success_prob = 0.0

            lives_score = min(100.0, total_lives_saved * 5.0)
            time_score = max(0.0, min(100.0, 100.0 - avg_time * 2.0))
            reliability_score = avg_conf * 100.0
            coverage_score_val = coverage_ratio * 100.0

            overall_score = (
                total_lives_saved * 10.0 - 
                avg_time * 2.0 + 
                avg_conf * 40.0 + 
                coverage_ratio * 30.0
            )

            objectives = (total_lives_saved, -avg_time if assignments else -999.0, avg_conf, coverage_ratio)

            res_dict = {
                "assignments": assignments,
                "metrics": {
                    "expected_lives_saved": round(total_lives_saved, 2),
                    "average_transit_time_minutes": round(avg_time, 2),
                    "average_route_confidence": round(avg_conf, 2),
                    "risk_score": round(risk_score, 2),
                    "coverage_ratio": round(coverage_ratio, 2)
                },
                "outcome_forecast": {
                    "expected_lives_saved": round(total_lives_saved, 2),
                    "expected_duration_minutes": round(avg_time, 2),
                    "success_probability": round(success_prob, 4),
                    "expected_fuel_consumed": round(total_fuel, 2)
                },
                "multi_objective_scores": {
                    "lives_saved_score": round(lives_score, 2),
                    "transit_time_score": round(time_score, 2),
                    "route_reliability_score": round(reliability_score, 2),
                    "coverage_score": round(coverage_score_val, 2)
                },
                "score": round(overall_score, 2)
            }
            return objectives, res_dict

        # Seed & Initial population Setup
        seeds = []
        seeds.append(generate_greedy_individual(1.0, 0.5, 0.8, 0.5))
        seeds.append(generate_greedy_individual(2.5, 0.2, 0.3, 0.2))
        seeds.append(generate_greedy_individual(0.4, 0.3, 2.0, 0.6))
        seeds.append(generate_greedy_individual(0.6, 2.2, 0.4, 0.3))
        seeds.append(generate_greedy_individual(0.8, 0.4, 0.6, 1.8))
        
        import random
        population = list(seeds)
        POP_SIZE = 50
        GENERATIONS = 30
        
        while len(population) < POP_SIZE:
            ind: List[Optional[str]] = []
            assigned = set()
            for vehicle in vehicles:
                v_id = vehicle["id"]
                feasible = [t for t in targets if (v_id, t) in route_cache and t not in assigned]
                if feasible and random.random() < 0.8:
                    tgt = random.choice(feasible)
                    ind.append(tgt)
                    assigned.add(tgt)
                else:
                    ind.append(None)
            population.append(ind)

        # NSGA-II Inspired Optimizer Tournament Selection
        def tournament_selection(pop: List[List[Optional[str]]]) -> List[Optional[str]]:
            c1 = random.choice(pop)
            c2 = random.choice(pop)
            _, d1 = evaluate_individual(c1)
            _, d2 = evaluate_individual(c2)
            if d1["score"] >= d2["score"]:
                return c1
            return c2

        # Evolutionary Loop
        for gen in range(GENERATIONS):
            offspring = []
            while len(offspring) < POP_SIZE:
                p1 = tournament_selection(population)
                p2 = tournament_selection(population)
                
                child1 = []
                child2 = []
                for g1, g2 in zip(p1, p2):
                    if random.random() < 0.5:
                        child1.append(g1)
                        child2.append(g2)
                    else:
                        child1.append(g2)
                        child2.append(g1)
                
                for child in (child1, child2):
                    mutated = list(child)
                    for i in range(len(mutated)):
                        if random.random() < 0.15:
                            v_id = vehicles[i]["id"]
                            feasible = [t for t in targets if (v_id, t) in route_cache]
                            if feasible:
                                mutated[i] = random.choice(feasible + [None])
                            else:
                                mutated[i] = None
                    offspring.append(mutated)
            
            combined_population = population + offspring
            
            repaired_combined = []
            for ind in combined_population:
                seen_targets = set()
                repaired = []
                for idx, tgt in enumerate(ind):
                    if tgt is None or tgt in seen_targets:
                        repaired.append(None)
                    else:
                        v_id = vehicles[idx]["id"]
                        if (v_id, tgt) in route_cache:
                            repaired.append(tgt)
                            seen_targets.add(tgt)
                        else:
                            repaired.append(None)
                repaired_combined.append(repaired)
            
            unique_combined = []
            seen_ind = set()
            for ind in repaired_combined:
                tup = tuple(ind)
                if tup not in seen_ind:
                    unique_combined.append(ind)
                    seen_ind.add(tup)
            
            fitnesses = {}
            detailed_results = {}
            for idx, ind in enumerate(unique_combined):
                objs, details = evaluate_individual(ind)
                fitnesses[idx] = objs
                detailed_results[idx] = details
                
            fronts = fast_non_dominated_sort(unique_combined, fitnesses)
            
            next_population = []
            for front in fronts:
                if len(next_population) + len(front) <= POP_SIZE:
                    for idx in front:
                        next_population.append(unique_combined[idx])
                else:
                    cd_dict = calculate_crowding_distance(front, fitnesses)
                    sorted_front = sorted(front, key=lambda idx: cd_dict.get(idx, 0.0), reverse=True)
                    for idx in sorted_front:
                        if len(next_population) < POP_SIZE:
                            next_population.append(unique_combined[idx])
                    break
            
            population = next_population

            # Resolve GA population collapse by checking size and replenishing
            while len(population) < POP_SIZE:
                if population and random.random() < 0.5:
                    parent = random.choice(population)
                    mutated = list(parent)
                    for i in range(len(mutated)):
                        if random.random() < 0.2:
                            v_id = vehicles[i]["id"]
                            feasible = [t for t in targets if (v_id, t) in route_cache]
                            if feasible:
                                mutated[i] = random.choice(feasible + [None])
                            else:
                                mutated[i] = None
                    seen_targets = set()
                    repaired = []
                    for idx, tgt in enumerate(mutated):
                        if tgt is None or tgt in seen_targets:
                            repaired.append(None)
                        else:
                            v_id = vehicles[idx]["id"]
                            if (v_id, tgt) in route_cache:
                                repaired.append(tgt)
                                seen_targets.add(tgt)
                            else:
                                repaired.append(None)
                    population.append(repaired)
                else:
                    ind = []
                    assigned = set()
                    for vehicle in vehicles:
                        v_id = vehicle["id"]
                        feasible = [t for t in targets if (v_id, t) in route_cache and t not in assigned]
                        if feasible and random.random() < 0.8:
                            tgt = random.choice(feasible)
                            ind.append(tgt)
                            assigned.add(tgt)
                        else:
                            ind.append(None)
                    population.append(ind)

        final_unique = []
        seen_ind = set()
        for ind in population:
            tup = tuple(ind)
            if tup not in seen_ind:
                final_unique.append(ind)
                seen_ind.add(tup)
                
        final_fitnesses = {}
        final_details = {}
        for idx, ind in enumerate(final_unique):
            objs, details = evaluate_individual(ind)
            final_fitnesses[idx] = objs
            final_details[idx] = details

        portfolio_profiles = {
            "balanced": {
                "name": "Balanced Objective Portfolio",
                "desc": "Balances emergency urgency, rescue speed, and route safety.",
                "select_fn": lambda idx: final_details[idx]["score"],
            },
            "max_lives": {
                "name": "Aggressive Rescue (Maximize Lives Saved)",
                "desc": "Prioritizes immediate high-casualty targets despite higher terrain/path risks.",
                "select_fn": lambda idx: (final_fitnesses[idx][0], -final_details[idx]["metrics"]["risk_score"])
            },
            "risk_averse": {
                "name": "Risk Averse (Maximize Path Confidence & Safety)",
                "desc": "Selects highly reliable routes with verified clearances and low hazard exposure.",
                "select_fn": lambda idx: (final_fitnesses[idx][2], final_details[idx]["score"])
            },
            "rapid_response": {
                "name": "Rapid Response (Minimize Transit Time)",
                "desc": "Prioritizes the fastest arrival times and closest vehicle deployments.",
                "select_fn": lambda idx: (final_fitnesses[idx][1], final_details[idx]["score"])
            },
            "max_coverage": {
                "name": "High Target Coverage Portfolio",
                "desc": "Spreads resources across the widest set of communities to maximize assistance footprint.",
                "select_fn": lambda idx: (final_fitnesses[idx][3], final_details[idx]["score"])
            }
        }
        
        selected_alternatives = []
        for alt_id, profile in portfolio_profiles.items():
            best_idx = max(range(len(final_unique)), key=profile["select_fn"])
            best_details = dict(final_details[best_idx])
            best_details.update({
                "alternative_id": alt_id,
                "name": profile["name"],
                "description": profile["desc"]
            })
            selected_alternatives.append(best_details)
            
        selected_alternatives.sort(key=lambda x: x["score"], reverse=True)
        for rank_idx, alt in enumerate(selected_alternatives):
            alt["rank"] = rank_idx + 1

        return selected_alternatives[:5]
