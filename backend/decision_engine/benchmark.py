import networkx as nx
import time
import math
from typing import List, Dict, Any, Tuple
from backend.decision_engine.decision_optimizer import DecisionOptimizer
from backend.routing.confidence_dijkstra import find_confidence_route
from backend.agents.fleet_config import FLEET_SPECIFICATIONS

class BenchmarkSuite:
    """
    Compares Sentinel's multi-objective Decision Engine against standard baselines:
    - Greedy Allocation (Lives saved only)
    - Nearest-Resource Heuristic (Distance/time only)
    - Shortest-Path Routing (Standard physical distance Dijkstra)
    - Oracle Benchmark (Perfect information routing on ground truth)
    """

    FUEL_RATES = {
        "HELICOPTER": 5.0,
        "HIGH_WATER_TRUCK": 2.0,
        "ZODIAC_BOAT": 1.5,
        "STANDARD_CAR": 1.0
    }

    @staticmethod
    def calculate_gini(values: List[float]) -> float:
        """
        Calculates the Gini Fairness Index (Gini Coefficient) for a list of values.
        0.0 represents perfect equality, 1.0 represents perfect inequality.
        """
        n = len(values)
        if n == 0:
            return 0.0
        if sum(values) == 0.0:
            return 0.0
        sorted_vals = sorted(values)
        gini_sum = 0.0
        for i, val in enumerate(sorted_vals):
            # 1-indexed formula: 2*i - n - 1
            gini_sum += (2 * (i + 1) - n - 1) * val
        return round(gini_sum / (n * sum(sorted_vals)), 4)

    @classmethod
    def calculate_statistical_evaluations_from_run(
        cls,
        results: Dict[str, Dict[str, Any]],
        targets: List[str]
    ) -> Dict[str, Any]:
        """
        Computes Wilcoxon signed-rank tests pairwise and Friedman chi-square scores
        across the 5 models for the current run, treating individual targets as observations.
        """
        import scipy.stats as stats
        
        models = ["sentinel", "greedy", "nearest_resource", "shortest_path", "oracle"]
        
        # Build target-level observations for expected_lives_saved and travel time
        lives_obs = {model: [] for model in models}
        time_obs = {model: [] for model in models}
        
        for model in models:
            model_res = results.get(model, {})
            assign_map = {a["target_node"]: a for a in model_res.get("assignments", [])}
            for tgt in targets:
                if tgt in assign_map:
                    lives_obs[model].append(assign_map[tgt].get("expected_lives_saved", 0.0))
                    time_obs[model].append(assign_map[tgt].get("estimated_time_minutes", 0.0))
                else:
                    lives_obs[model].append(0.0)
                    time_obs[model].append(120.0) # Penalty time for unserved target
                    
        # 1. Friedman Chi-Square test across all 5 models
        friedman_results = {}
        for metric, obs_dict in [("expected_lives_saved", lives_obs), ("transit_time", time_obs)]:
            try:
                # Check if all models have identical observation vectors
                first_vec = obs_dict[models[0]]
                all_identical = True
                for m in models[1:]:
                    if not all(a == b for a, b in zip(first_vec, obs_dict[m])):
                        all_identical = False
                        break
                if all_identical or len(targets) < 3:
                    friedman_results[metric] = {
                        "statistic": 0.0,
                        "p_value": 1.0,
                        "significant": False,
                        "note": "Identical observations or too few targets."
                    }
                else:
                    stat, pval = stats.friedmanchisquare(
                        obs_dict["sentinel"],
                        obs_dict["greedy"],
                        obs_dict["nearest_resource"],
                        obs_dict["shortest_path"],
                        obs_dict["oracle"]
                    )
                    friedman_results[metric] = {
                        "statistic": round(float(stat), 4),
                        "p_value": round(float(pval), 5),
                        "significant": bool(pval < 0.05)
                    }
            except Exception as e:
                friedman_results[metric] = {
                    "statistic": 0.0,
                    "p_value": 1.0,
                    "significant": False,
                    "error": str(e)
                }

        # 2. Pairwise Wilcoxon Signed-Rank differences
        wilcoxon_results = {}
        for metric, obs_dict in [("expected_lives_saved", lives_obs), ("transit_time", time_obs)]:
            wilcoxon_results[metric] = {}
            for i in range(len(models)):
                for j in range(i + 1, len(models)):
                    m1, m2 = models[i], models[j]
                    pair_name = f"{m1}_vs_{m2}"
                    x, y = obs_dict[m1], obs_dict[m2]
                    try:
                        if all(a == b for a, b in zip(x, y)):
                            wilcoxon_results[metric][pair_name] = {
                                "statistic": 0.0,
                                "p_value": 1.0,
                                "significant": False,
                                "note": "Identical observation vectors."
                            }
                        else:
                            stat, pval = stats.wilcoxon(x, y)
                            wilcoxon_results[metric][pair_name] = {
                                "statistic": round(float(stat), 4),
                                "p_value": round(float(pval), 5),
                                "significant": bool(pval < 0.05)
                            }
                    except Exception as e:
                        wilcoxon_results[metric][pair_name] = {
                            "statistic": 0.0,
                            "p_value": 1.0,
                            "significant": False,
                            "error": str(e)
                        }

        return {
            "friedman_chi_square": friedman_results,
            "wilcoxon_pairwise": wilcoxon_results
        }

    @classmethod
    def calculate_statistical_evaluations_across_runs(
        cls,
        all_run_results: List[Dict[str, Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """
        Computes Wilcoxon signed-rank tests pairwise and Friedman chi-square scores
        across the 5 models, treating each historical benchmark run as a single sample observation.
        """
        import scipy.stats as stats
        
        models = ["sentinel", "greedy", "nearest_resource", "shortest_path", "oracle"]
        metrics = ["expected_lives_saved", "average_transit_time_minutes", "average_route_confidence", "total_fuel_consumed"]
        
        obs = {metric: {model: [] for model in models} for metric in metrics}
        
        for run in all_run_results:
            for model in models:
                model_res = run.get(model, {})
                for metric in metrics:
                    obs[metric][model].append(model_res.get(metric, 0.0))
                    
        friedman_results = {}
        wilcoxon_results = {}
        
        n_runs = len(all_run_results)
        
        for metric in metrics:
            # Friedman
            try:
                first_vec = obs[metric][models[0]]
                all_identical = True
                for m in models[1:]:
                    if not all(a == b for a, b in zip(first_vec, obs[metric][m])):
                        all_identical = False
                        break
                if all_identical or n_runs < 3:
                    friedman_results[metric] = {
                        "statistic": 0.0,
                        "p_value": 1.0,
                        "significant": False,
                        "note": "Identical observations or too few runs."
                    }
                else:
                    stat, pval = stats.friedmanchisquare(
                        obs[metric]["sentinel"],
                        obs[metric]["greedy"],
                        obs[metric]["nearest_resource"],
                        obs[metric]["shortest_path"],
                        obs[metric]["oracle"]
                    )
                    friedman_results[metric] = {
                        "statistic": round(float(stat), 4),
                        "p_value": round(float(pval), 5),
                        "significant": bool(pval < 0.05)
                    }
            except Exception as e:
                friedman_results[metric] = {
                    "statistic": 0.0,
                    "p_value": 1.0,
                    "significant": False,
                    "error": str(e)
                }
                
            # Wilcoxon pairwise
            wilcoxon_results[metric] = {}
            for i in range(len(models)):
                for j in range(i + 1, len(models)):
                    m1, m2 = models[i], models[j]
                    pair_name = f"{m1}_vs_{m2}"
                    x, y = obs[metric][m1], obs[metric][m2]
                    try:
                        if all(a == b for a, b in zip(x, y)):
                            wilcoxon_results[metric][pair_name] = {
                                "statistic": 0.0,
                                "p_value": 1.0,
                                "significant": False,
                                "note": "Identical observation vectors."
                            }
                        else:
                            stat, pval = stats.wilcoxon(x, y)
                            wilcoxon_results[metric][pair_name] = {
                                "statistic": round(float(stat), 4),
                                "p_value": round(float(pval), 5),
                                "significant": bool(pval < 0.05)
                            }
                    except Exception as e:
                        wilcoxon_results[metric][pair_name] = {
                            "statistic": 0.0,
                            "p_value": 1.0,
                            "significant": False,
                            "error": str(e)
                        }
                        
        return {
            "friedman_chi_square": friedman_results,
            "wilcoxon_pairwise": wilcoxon_results
        }

    @classmethod
    def run_comparative_benchmark(
        cls,
        belief_graph: nx.Graph,
        ground_truth_graph: nx.Graph,
        targets: List[str],
        vehicles: List[Dict[str, Any]],
        disaster_type: str = "FLOOD"
    ) -> Dict[str, Any]:
        """
        Runs the full comparative benchmark suite. Returns performance comparisons
        along with statistical evaluations (Gini Fairness Index, Wilcoxon, Friedman tests).
        """
        results = {}

        # 1. Sentinel (Balanced Objective Portfolio)
        t_start = time.perf_counter()
        sentinel_alts = DecisionOptimizer.optimize_assignments(belief_graph, targets, vehicles, disaster_type)
        t_end = time.perf_counter()
        
        sentinel_perf = None
        if sentinel_alts:
            # Find the Balanced portfolio or rank 1
            for alt in sentinel_alts:
                if alt["alternative_id"] == "balanced":
                    sentinel_perf = alt
                    break
            if not sentinel_perf:
                sentinel_perf = sentinel_alts[0]
        
        if sentinel_perf:
            results["sentinel"] = {
                "name": "Sentinel (Balanced MO)",
                "expected_lives_saved": sentinel_perf["outcome_forecast"]["expected_lives_saved"],
                "average_transit_time_minutes": sentinel_perf["outcome_forecast"]["expected_duration_minutes"],
                "average_route_confidence": sentinel_perf["metrics"]["average_route_confidence"],
                "total_fuel_consumed": sentinel_perf["outcome_forecast"]["expected_fuel_consumed"],
                "coverage_ratio": sentinel_perf["metrics"]["coverage_ratio"],
                "execution_time_ms": (t_end - t_start) * 1000.0,
                "assignments": sentinel_perf["assignments"]
            }
        else:
            results["sentinel"] = cls._empty_metrics("Sentinel (Balanced MO)")

        # 2. Greedy Allocation (Maximize expected lives saved only)
        t_start = time.perf_counter()
        results["greedy"] = cls._run_greedy_baseline(belief_graph, targets, vehicles, disaster_type)
        results["greedy"]["execution_time_ms"] = (time.perf_counter() - t_start) * 1000.0

        # 3. Nearest-Resource Heuristic (Minimize distance/time only)
        t_start = time.perf_counter()
        results["nearest_resource"] = cls._run_nearest_resource_baseline(belief_graph, targets, vehicles, disaster_type)
        results["nearest_resource"]["execution_time_ms"] = (time.perf_counter() - t_start) * 1000.0

        # 4. Shortest-Path Routing (Ignores path confidence and hazards)
        t_start = time.perf_counter()
        results["shortest_path"] = cls._run_shortest_path_baseline(belief_graph, targets, vehicles, disaster_type)
        results["shortest_path"]["execution_time_ms"] = (time.perf_counter() - t_start) * 1000.0

        # 5. Oracle Benchmark (Perfect ground truth routing, no blockages/uncertainty errors)
        t_start = time.perf_counter()
        results["oracle"] = cls._run_oracle_benchmark(ground_truth_graph, targets, vehicles, disaster_type)
        results["oracle"]["execution_time_ms"] = (time.perf_counter() - t_start) * 1000.0

        # Calculate Gini Fairness Index for each model
        for key in ["sentinel", "greedy", "nearest_resource", "shortest_path", "oracle"]:
            if key in results:
                assignments = results[key].get("assignments", [])
                
                # Lives saved per target
                lives_per_target = {tgt: 0.0 for tgt in targets}
                for assign in assignments:
                    tgt = assign["target_node"]
                    lives_per_target[tgt] = lives_per_target.get(tgt, 0.0) + assign.get("expected_lives_saved", 0.0)
                
                # Vehicles assigned per target
                vehicles_per_target = {tgt: 0.0 for tgt in targets}
                for assign in assignments:
                    tgt = assign["target_node"]
                    vehicles_per_target[tgt] = vehicles_per_target.get(tgt, 0.0) + 1.0
                
                results[key]["gini_fairness_lives"] = cls.calculate_gini(list(lives_per_target.values()))
                results[key]["gini_fairness_resources"] = cls.calculate_gini(list(vehicles_per_target.values()))

        # Compute Wilcoxon signed-rank and Friedman chi-square tests across models using targets as observations
        results["statistical_evaluation"] = cls.calculate_statistical_evaluations_from_run(results, targets)

        return results

    @classmethod
    def _empty_metrics(cls, name: str) -> Dict[str, Any]:
        return {
            "name": name,
            "expected_lives_saved": 0.0,
            "average_transit_time_minutes": 0.0,
            "average_route_confidence": 0.0,
            "total_fuel_consumed": 0.0,
            "coverage_ratio": 0.0,
            "execution_time_ms": 0.0,
            "assignments": []
        }

    @classmethod
    def _run_greedy_baseline(
        cls,
        belief_graph: nx.Graph,
        targets: List[str],
        vehicles: List[Dict[str, Any]],
        disaster_type: str
    ) -> Dict[str, Any]:
        """
        Assigns vehicle to targets with highest triage counts without considering confidence/time metrics.
        """
        # Sort targets by casualty weight descending
        target_priorities = []
        for tgt in targets:
            data = belief_graph.nodes.get(tgt, {})
            triage_immediate = data.get("triage_immediate", 0) or 0
            triage_delayed = data.get("triage_delayed", 0) or 0
            triage_minor = data.get("triage_minor", 0) or 0
            population = data.get("population", 0) or 0
            raw_lives = (triage_immediate * 2.0) + (triage_delayed * 1.0) + (triage_minor * 0.2) + (population * 0.02)
            target_priorities.append((tgt, raw_lives))
        
        target_priorities.sort(key=lambda x: x[1], reverse=True)

        assigned_vehicles = set()
        assignments = []
        total_lives = 0.0
        total_time = 0.0
        total_conf = 0.0
        total_fuel = 0.0

        for tgt, raw_lives in target_priorities:
            # Find first available vehicle that can route to this target
            best_veh = None
            best_route = None
            
            for veh in vehicles:
                v_id = veh["id"]
                if v_id in assigned_vehicles:
                    continue
                
                route_res = find_confidence_route(belief_graph, veh["location"], tgt, veh["type"])
                if route_res:
                    best_veh = veh
                    best_route = route_res
                    break
            
            if best_veh and best_route:
                path, dist, conf = best_route
                spec = FLEET_SPECIFICATIONS.get(best_veh["type"], FLEET_SPECIFICATIONS["STANDARD_CAR"])
                capacity = spec.get("capacity", 5)
                lives_saved = min(raw_lives, capacity)
                
                speed_mult = spec.get("speed_multiplier", 1.0)
                time_min = (dist / max(0.1, speed_mult * 10.0)) / 60.0
                fuel = (dist / 1000.0) * cls.FUEL_RATES.get(best_veh["type"], 1.0)

                assignments.append({
                    "target_node": tgt,
                    "vehicle_id": best_veh["id"],
                    "vehicle_type": best_veh["type"],
                    "path": path,
                    "distance": dist,
                    "path_confidence": conf,
                    "estimated_time_minutes": time_min,
                    "expected_lives_saved": lives_saved
                })
                
                assigned_vehicles.add(best_veh["id"])
                total_lives += lives_saved
                total_time += time_min
                total_conf += conf
                total_fuel += fuel

        n_assign = max(1, len(assignments))
        return {
            "name": "Greedy (Lives-Only)",
            "expected_lives_saved": round(total_lives, 2),
            "average_transit_time_minutes": round(total_time / n_assign, 2),
            "average_route_confidence": round(total_conf / n_assign, 2),
            "total_fuel_consumed": round(total_fuel, 2),
            "coverage_ratio": round(len(assignments) / max(1, len(targets)), 2),
            "assignments": assignments
        }

    @classmethod
    def _run_nearest_resource_baseline(
        cls,
        belief_graph: nx.Graph,
        targets: List[str],
        vehicles: List[Dict[str, Any]],
        disaster_type: str
    ) -> Dict[str, Any]:
        """
        Assigns vehicle to target based strictly on closest distance/travel time.
        """
        assigned_targets = set()
        assigned_vehicles = set()
        assignments = []
        total_lives = 0.0
        total_time = 0.0
        total_conf = 0.0
        total_fuel = 0.0

        # Calculate all possible routing combinations and sort by travel time
        candidates = []
        for veh in vehicles:
            v_id = veh["id"]
            for tgt in targets:
                route_res = find_confidence_route(belief_graph, veh["location"], tgt, veh["type"])
                if route_res:
                    path, dist, conf = route_res
                    spec = FLEET_SPECIFICATIONS.get(veh["type"], FLEET_SPECIFICATIONS["STANDARD_CAR"])
                    speed_mult = spec.get("speed_multiplier", 1.0)
                    time_min = (dist / max(0.1, speed_mult * 10.0)) / 60.0
                    candidates.append((veh, tgt, path, dist, conf, time_min))

        candidates.sort(key=lambda x: x[5])  # Sort by time ascending

        for veh, tgt, path, dist, conf, time_min in candidates:
            if veh["id"] in assigned_vehicles or tgt in assigned_targets:
                continue
            
            data = belief_graph.nodes.get(tgt, {})
            triage_immediate = data.get("triage_immediate", 0) or 0
            triage_delayed = data.get("triage_delayed", 0) or 0
            triage_minor = data.get("triage_minor", 0) or 0
            population = data.get("population", 0) or 0
            raw_lives = (triage_immediate * 2.0) + (triage_delayed * 1.0) + (triage_minor * 0.2) + (population * 0.02)
            
            spec = FLEET_SPECIFICATIONS.get(veh["type"], FLEET_SPECIFICATIONS["STANDARD_CAR"])
            capacity = spec.get("capacity", 5)
            lives_saved = min(raw_lives, capacity)
            fuel = (dist / 1000.0) * cls.FUEL_RATES.get(veh["type"], 1.0)

            assignments.append({
                "target_node": tgt,
                "vehicle_id": veh["id"],
                "vehicle_type": veh["type"],
                "path": path,
                "distance": dist,
                "path_confidence": conf,
                "estimated_time_minutes": time_min,
                "expected_lives_saved": lives_saved
            })
            
            assigned_vehicles.add(veh["id"])
            assigned_targets.add(tgt)
            total_lives += lives_saved
            total_time += time_min
            total_conf += conf
            total_fuel += fuel

        n_assign = max(1, len(assignments))
        return {
            "name": "Nearest-Resource Heuristic",
            "expected_lives_saved": round(total_lives, 2),
            "average_transit_time_minutes": round(total_time / n_assign, 2),
            "average_route_confidence": round(total_conf / n_assign, 2),
            "total_fuel_consumed": round(total_fuel, 2),
            "coverage_ratio": round(len(assignments) / max(1, len(targets)), 2),
            "assignments": assignments
        }

    @classmethod
    def _run_shortest_path_baseline(
        cls,
        belief_graph: nx.Graph,
        targets: List[str],
        vehicles: List[Dict[str, Any]],
        disaster_type: str
    ) -> Dict[str, Any]:
        """
        Uses standard NetworkX Dijkstra shortest path (by physical distance) ignoring hazards/confidence.
        """
        # Create a view filtering blocked edges from belief
        open_view = nx.subgraph_view(belief_graph, filter_edge=lambda u, v: not belief_graph.edges[u, v].get("blocked", False))

        assigned_targets = set()
        assigned_vehicles = set()
        assignments = []
        total_lives = 0.0
        total_time = 0.0
        total_conf = 0.0
        total_fuel = 0.0

        for tgt in targets:
            best_veh = None
            best_path = None
            best_dist = float('inf')
            
            for veh in vehicles:
                if veh["id"] in assigned_vehicles:
                    continue
                try:
                    if nx.has_path(open_view, veh["location"], tgt):
                        path = nx.shortest_path(open_view, veh["location"], tgt, weight="distance")
                        dist = sum(belief_graph.edges[path[i], path[i+1]].get("distance", 1.0) for i in range(len(path)-1))
                        if dist < best_dist:
                            best_dist = dist
                            best_path = path
                            best_veh = veh
                except nx.NetworkXNoPath:
                    pass
            
            if best_veh and best_path:
                conf = sum(belief_graph.edges[best_path[i], best_path[i+1]].get("confidence", 1.0) for i in range(len(best_path)-1)) / max(1, len(best_path)-1)
                
                data = belief_graph.nodes.get(tgt, {})
                triage_immediate = data.get("triage_immediate", 0) or 0
                triage_delayed = data.get("triage_delayed", 0) or 0
                triage_minor = data.get("triage_minor", 0) or 0
                population = data.get("population", 0) or 0
                raw_lives = (triage_immediate * 2.0) + (triage_delayed * 1.0) + (triage_minor * 0.2) + (population * 0.02)
                
                spec = FLEET_SPECIFICATIONS.get(best_veh["type"], FLEET_SPECIFICATIONS["STANDARD_CAR"])
                capacity = spec.get("capacity", 5)
                lives_saved = min(raw_lives, capacity)
                
                speed_mult = spec.get("speed_multiplier", 1.0)
                time_min = (best_dist / max(0.1, speed_mult * 10.0)) / 60.0
                fuel = (best_dist / 1000.0) * cls.FUEL_RATES.get(best_veh["type"], 1.0)

                assignments.append({
                    "target_node": tgt,
                    "vehicle_id": best_veh["id"],
                    "vehicle_type": best_veh["type"],
                    "path": best_path,
                    "distance": best_dist,
                    "path_confidence": conf,
                    "estimated_time_minutes": time_min,
                    "expected_lives_saved": lives_saved
                })
                
                assigned_vehicles.add(best_veh["id"])
                assigned_targets.add(tgt)
                total_lives += lives_saved
                total_time += time_min
                total_conf += conf
                total_fuel += fuel

        n_assign = max(1, len(assignments))
        return {
            "name": "Shortest Path Routing",
            "expected_lives_saved": round(total_lives, 2),
            "average_transit_time_minutes": round(total_time / n_assign, 2),
            "average_route_confidence": round(total_conf / n_assign, 2),
            "total_fuel_consumed": round(total_fuel, 2),
            "coverage_ratio": round(len(assignments) / max(1, len(targets)), 2),
            "assignments": assignments
        }

    @classmethod
    def _run_oracle_benchmark(
        cls,
        ground_truth_graph: nx.Graph,
        targets: List[str],
        vehicles: List[Dict[str, Any]],
        disaster_type: str
    ) -> Dict[str, Any]:
        """
        Oracle benchmark: Solves assignments using ground truth (actual blockages known perfectly).
        """
        # Optimize using ground truth graph instead of belief graph
        oracle_alts = DecisionOptimizer.optimize_assignments(ground_truth_graph, targets, vehicles, disaster_type)
        if not oracle_alts:
            return cls._empty_metrics("Oracle Benchmark")
        
        oracle_perf = oracle_alts[0] # Use highest scoring portfolio
        return {
            "name": "Oracle (Perfect Information)",
            "expected_lives_saved": oracle_perf["outcome_forecast"]["expected_lives_saved"],
            "average_transit_time_minutes": oracle_perf["outcome_forecast"]["expected_duration_minutes"],
            "average_route_confidence": oracle_perf["metrics"]["average_route_confidence"],
            "total_fuel_consumed": oracle_perf["outcome_forecast"]["expected_fuel_consumed"],
            "coverage_ratio": oracle_perf["metrics"]["coverage_ratio"],
            "assignments": oracle_perf["assignments"]
        }
