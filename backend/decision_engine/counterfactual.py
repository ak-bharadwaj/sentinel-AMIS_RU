import networkx as nx
import math
from datetime import datetime
from typing import Dict, Any, List, Optional
from backend.routing.confidence_dijkstra import find_confidence_route, calculate_edge_cost
from backend.agents.fleet_config import FLEET_SPECIFICATIONS

class CounterfactualEngine:
    """
    Evaluates alternative decisions (alternative paths, alternative vehicles, delay penalties)
    and maps simulated outcomes. Supports 'What-If' sensitivity analysis and Human Override hooks.
    """

    override_logs: List[Dict[str, Any]] = []

    @classmethod
    def log_human_override(
        cls,
        user_id: str,
        action: str,
        original_recommendation: Dict[str, Any],
        overridden_decision: Dict[str, Any],
        reason: str
    ) -> None:
        """
        Logs a human override decision event for logging, compliance, and analysis.
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "action": action,
            "original_recommendation": original_recommendation,
            "overridden_decision": overridden_decision,
            "reason": reason
        }
        cls.override_logs.append(log_entry)

    @classmethod
    def evaluate_alternative_paths(
        cls,
        belief_graph: nx.Graph,
        source: str,
        target: str,
        vehicle_type: str,
        chosen_path: List[str]
    ) -> Dict[str, Any]:
        """
        Compares the chosen path to a backup path.
        Since short-cuts can be blocked, we look for a path with different risk profiles.
        """
        temp_graph = belief_graph.copy()
        if len(chosen_path) > 2:
            # Block one of the middle edges to force shortest path search to find an alternative route
            u, v = chosen_path[1], chosen_path[2]
            if temp_graph.has_edge(u, v):
                temp_graph.edges[u, v]["blocked"] = True
                temp_graph.edges[u, v]["confidence"] = 0.0

        alt_route = find_confidence_route(temp_graph, source, target, vehicle_type)
        if not alt_route:
            return {
                "has_alternative": False,
                "comparison": "No alternative path available if the primary route is blocked."
            }

        alt_path, alt_dist, alt_conf = alt_route
        spec = FLEET_SPECIFICATIONS.get(vehicle_type, FLEET_SPECIFICATIONS["STANDARD_CAR"])
        speed_mult = spec.get("speed_multiplier", 1.0)
        
        chosen_time = sum(belief_graph.edges[chosen_path[i], chosen_path[i+1]].get("distance", 1.0) for i in range(len(chosen_path)-1)) / max(0.1, speed_mult * 10.0) / 60.0
        alt_time = alt_dist / max(0.1, speed_mult * 10.0) / 60.0

        time_difference = alt_time - chosen_time
        
        return {
            "has_alternative": True,
            "alternative_path": alt_path,
            "alternative_distance": alt_dist,
            "alternative_confidence": alt_conf,
            "estimated_time_minutes": alt_time,
            "time_difference_minutes": time_difference,
            "comparison": f"Alternative path adds {time_difference:.1f} minutes but offers {alt_conf*100:.1f}% confidence profile."
        }

    @classmethod
    def evaluate_alternative_vehicles(
        cls,
        belief_graph: nx.Graph,
        source: str,
        target: str,
        chosen_vehicle_type: str,
        available_vehicle_types: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Evaluates what would happen if a different vehicle type was selected.
        """
        alternatives = []
        for v_type in available_vehicle_types:
            if v_type == chosen_vehicle_type:
                continue

            route_res = find_confidence_route(belief_graph, source, target, v_type)
            if not route_res:
                alternatives.append({
                    "vehicle_type": v_type,
                    "feasible": False,
                    "reason": "No route exists for this vehicle type due to terrain or blockages."
                })
                continue

            path, distance, confidence = route_res
            spec = FLEET_SPECIFICATIONS.get(v_type, FLEET_SPECIFICATIONS["STANDARD_CAR"])
            
            # Check maximum water depth constraint
            max_water = 0.0
            for node_id in path:
                w = belief_graph.nodes[node_id].get("water_level", 0.0)
                if w > max_water:
                    max_water = w

            if max_water > spec.get("max_water_depth", 99.0):
                alternatives.append({
                    "vehicle_type": v_type,
                    "feasible": False,
                    "reason": f"Water level ({max_water:.2fm}) exceeds vehicle's maximum capability ({spec.get('max_water_depth')}m)."
                })
                continue

            speed_mult = spec.get("speed_multiplier", 1.0)
            time_min = distance / max(0.1, speed_mult * 10.0) / 60.0

            alternatives.append({
                "vehicle_type": v_type,
                "feasible": True,
                "distance": distance,
                "path_confidence": confidence,
                "estimated_time_minutes": time_min,
                "reason": f"Feasible. Travel time is {time_min:.1f} minutes with {confidence*100:.1f}% route confidence."
            })
        return alternatives

    @classmethod
    def evaluate_delay_penalties(
        cls,
        triage_immediate: int,
        triage_delayed: int,
        delay_minutes: float
    ) -> Dict[str, Any]:
        """
        Simulates how delaying the rescue operation by delay_minutes affects triage health.
        """
        survival_rate_immediate = math.exp(-0.05 * delay_minutes)
        deterioration_rate_delayed = 1.0 - math.exp(-0.03 * delay_minutes)

        expected_surviving_immediate = triage_immediate * survival_rate_immediate
        expected_deceased = triage_immediate * (1.0 - survival_rate_immediate)

        new_delayed = triage_delayed * (1.0 - deterioration_rate_delayed)
        deteriorated_to_immediate = triage_delayed * deterioration_rate_delayed

        total_expected_immediate = expected_surviving_immediate + deteriorated_to_immediate

        return {
            "delay_minutes": delay_minutes,
            "original_immediate": triage_immediate,
            "original_delayed": triage_delayed,
            "expected_surviving_immediate": round(expected_surviving_immediate, 2),
            "expected_deteriorated_to_immediate": round(deteriorated_to_immediate, 2),
            "expected_deceased": round(expected_deceased, 2),
            "new_delayed": round(new_delayed, 2),
            "severity_increase_ratio": round((expected_deceased / max(1, triage_immediate + triage_delayed)), 3),
            "summary": f"A delay of {delay_minutes} minutes yields {expected_deceased:.1f} expected fatalities and causes {deteriorated_to_immediate:.1f} casualties to deteriorate to Immediate."
        }

    @classmethod
    def run_whatif_sensitivity_analysis(
        cls,
        belief_graph: nx.Graph,
        source: str,
        target: str,
        vehicle_type: str,
        base_path: List[str],
        sensitivity_options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Runs sensitivity scenarios and computes counterfactual impact.
        Customizable via sensitivity_options.
        Scenarios:
          1. Bridge Collapses: Blocks bridge nodes or path nodes.
          2. Rainfall increases by a custom percentage (e.g. +20% standard).
          3. Communications Failures: Decays path confidence by a custom factor.
          4. Grounding Helicopters: Forces standard car routing.
        """
        options = sensitivity_options or {}
        rainfall_mult = options.get("rainfall_multiplier", 1.2)
        comms_decay = options.get("comms_decay_factor", 0.5)
        bridge_node = options.get("bridge_collapse_node", None)
        copter_grounded = options.get("helicopter_grounded", True)

        results = {}

        # 1. Bridge Collapse Scenario
        collapsed_graph = belief_graph.copy()
        block_node = bridge_node
        if not block_node:
            for node in base_path[1:-1]:
                if belief_graph.nodes[node].get("node_type") == "BRIDGE" or True:
                    block_node = node
                    break
        
        if block_node:
            collapsed_graph.nodes[block_node]["status"] = "BLOCKED"
            collapsed_graph.nodes[block_node]["p_danger"] = 1.0
            for neighbor in list(collapsed_graph.neighbors(block_node)):
                collapsed_graph.edges[block_node, neighbor]["blocked"] = True
                collapsed_graph.edges[block_node, neighbor]["confidence"] = 0.0

        bridge_route = find_confidence_route(collapsed_graph, source, target, vehicle_type)
        if not bridge_route:
            results["bridge_collapse"] = {
                "feasible": False,
                "impact": "Route completely cut off. No alternative path available.",
                "remediation": "Deploy helicopter or clear debris."
            }
        else:
            _, dist, conf = bridge_route
            spec = FLEET_SPECIFICATIONS.get(vehicle_type, FLEET_SPECIFICATIONS["STANDARD_CAR"])
            speed_mult = spec.get("speed_multiplier", 1.0)
            time_min = (dist / max(0.1, speed_mult * 10.0)) / 60.0
            results["bridge_collapse"] = {
                "feasible": True,
                "impact": f"Alternative route found. Distance: {dist:.1f}m, Time: {time_min:.1f}m, Confidence: {conf*100:.1f}%.",
                "remediation": f"Route around collapsed point {block_node}."
            }

        # 2. Rainfall Scenario
        rain_graph = belief_graph.copy()
        for node in rain_graph.nodes:
            wl = rain_graph.nodes[node].get("water_level", 0.0)
            rain_graph.nodes[node]["water_level"] = wl * rainfall_mult

        rain_route = find_confidence_route(rain_graph, source, target, vehicle_type)
        if not rain_route:
            results["rainfall_sensitivity"] = {
                "feasible": False,
                "impact": f"Increased water levels (x{rainfall_mult}) render routes impassable.",
                "remediation": "Upgrade vehicle deployment to ZODIAC_BOAT or HIGH_WATER_TRUCK."
            }
        else:
            _, dist, conf = rain_route
            spec = FLEET_SPECIFICATIONS.get(vehicle_type, FLEET_SPECIFICATIONS["STANDARD_CAR"])
            speed_mult = spec.get("speed_multiplier", 1.0)
            time_min = (dist / max(0.1, speed_mult * 10.0)) / 60.0
            results["rainfall_sensitivity"] = {
                "feasible": True,
                "impact": f"Path remains open. Travel time is {time_min:.1f} minutes under wet conditions.",
                "remediation": "Proceed with caution, maintain telemetry monitoring."
            }

        # 3. Communications Failure Scenario
        comms_graph = belief_graph.copy()
        for u, v in comms_graph.edges:
            c = comms_graph.edges[u, v].get("confidence", 1.0)
            comms_graph.edges[u, v]["confidence"] = c * comms_decay
        for node in comms_graph.nodes:
            c = comms_graph.nodes[node].get("confidence", comms_graph.nodes[node].get("p_state_correct", 1.0))
            comms_graph.nodes[node]["confidence"] = c * comms_decay
            comms_graph.nodes[node]["p_state_correct"] = c * comms_decay

        comms_route = find_confidence_route(comms_graph, source, target, vehicle_type)
        if not comms_route:
            results["comms_failure"] = {
                "feasible": False,
                "impact": "Extreme uncertainty blocks routing algorithm.",
                "remediation": "Deploy UAV/Scout to recover signal and verify path state."
            }
        else:
            _, dist, conf = comms_route
            results["comms_failure"] = {
                "feasible": True,
                "impact": f"Route found but confidence is critically degraded to {conf*100:.1f}%.",
                "remediation": "Escort rescue vehicle with scouting drone."
            }

        # 4. Helicopter Grounding Scenario
        no_copter_type = "STANDARD_CAR" if (copter_grounded and vehicle_type == "HELICOPTER") else vehicle_type
        copter_route = find_confidence_route(belief_graph, source, target, no_copter_type)
        if not copter_route:
            results["no_helicopter"] = {
                "feasible": False,
                "impact": "Grounding helicopters cuts off travel options to this target.",
                "remediation": "Deploy boats or establish land staging zones."
            }
        else:
            _, dist, conf = copter_route
            spec = FLEET_SPECIFICATIONS.get(no_copter_type, FLEET_SPECIFICATIONS["STANDARD_CAR"])
            speed_mult = spec.get("speed_multiplier", 1.0)
            time_min = (dist / max(0.1, speed_mult * 10.0)) / 60.0
            results["no_helicopter"] = {
                "feasible": True,
                "impact": f"Routed via ground using {no_copter_type}. Time: {time_min:.1f}m, Confidence: {conf*100:.1f}%.",
                "remediation": f"Reallocate land resources to {no_copter_type}."
            }

        return results

    @classmethod
    def evaluate_scm_intervention(
        cls,
        belief_graph: nx.Graph,
        do_operators: Dict[str, Any],
        target_nodes: List[str]
    ) -> Dict[str, Any]:
        """
        Evaluates target hazard states under active do-operators using Pearl Structural Causal Model.
        Example: do_operators = {"Reinforce_Bridge": True} or {"Clear_Drainage": True}
        """
        results = {}
        for target in target_nodes:
            node_data = belief_graph.nodes.get(target, {})
            node_type = node_data.get("node_type", "NORMAL")
            
            # Extract state values from belief graph for this node
            water_level = node_data.get("water_level", 0.0)
            pga = node_data.get("seismic_pga", 0.0)
            triage_imm = node_data.get("triage_immediate", 0)
            triage_del = node_data.get("triage_delayed", 0)
            wind_speed = node_data.get("wind_speed", 45.0)
            
            # Setup SCM with base node values
            base_scm_vals = {
                "Rainfall": water_level * 5.0, # proxy rainfall from current water depth
                "WindSpeed": wind_speed,
                "SeismicPGA": pga,
                "Reinforce_Bridge": False,
                "Evacuation_Order": False,
                "Drainage_Clear": True,
                # Set initial states derived from node
                "FloodLevel": water_level
            }
            
            # Define observational (baseline) propagation
            scm_instance = PearlCausalSCM(base_scm_vals)
            baseline = scm_instance.evaluate({})
            
            # Define intervention (do-calculus)
            counterfactual = scm_instance.evaluate(do_operators)
            
            # Compute benefits of intervention
            imm_del_total = max(1.0, float(triage_imm + triage_del))
            expected_lives_saved_delta = max(
                0.0,
                (baseline["CasualtySeverity"] - counterfactual["CasualtySeverity"]) * imm_del_total
            )
            delay_reduction = max(0.0, baseline["RescueDelay"] - counterfactual["RescueDelay"])
            risk_reduction = max(0.0, baseline["BridgeCollapse"] - counterfactual["BridgeCollapse"])
            
            results[target] = {
                "node_type": node_type,
                "baseline": baseline,
                "counterfactual": counterfactual,
                "intervention_effect": {
                    "expected_lives_saved_delta": round(expected_lives_saved_delta, 2),
                    "rescue_delay_reduction_minutes": round(delay_reduction, 1),
                    "risk_reduction_pct": round(risk_reduction * 100.0, 1)
                }
            }
        return results


class PearlCausalSCM:
    """
    Lightweight Structural Causal Model (SCM) representing hazard propagation:
    We define endogenous variables, structural equations, and support active do-interventions.
    """
    def __init__(self, base_values: Dict[str, Any] = None):
        self.base_values = base_values or {
            "Rainfall": 15.0,            # mm/hr
            "WindSpeed": 45.0,           # km/h
            "SeismicPGA": 0.1,           # g
            "Reinforce_Bridge": False,   # Intervention node
            "Evacuation_Order": False,   # Intervention node
            "Drainage_Clear": True       # Intervention node
        }
        
    def evaluate(self, do_operators: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Evaluates the SCM under active do-interventions.
        Replaces structural equations of intervened variables with their do-values,
        then computes downstream effects.
        """
        do_ops = do_operators or {}
        vals = self.base_values.copy()
        
        # Apply do-interventions (active do-operators)
        for var, val in do_ops.items():
            vals[var] = val
            
        # Structural Equations
        # 1. Flood Level (depends on Rainfall and Drainage_Clear)
        if "FloodLevel" not in do_ops:
            drainage_factor = 0.4 if vals.get("Drainage_Clear", True) else 1.2
            vals["FloodLevel"] = max(0.0, 0.1 * vals.get("Rainfall", 15.0) * drainage_factor)
            
        # 2. Landslide/Debris Risk (depends on Rainfall and SeismicPGA)
        if "LandslideRisk" not in do_ops:
            vals["LandslideRisk"] = min(1.0, 0.02 * vals.get("Rainfall", 15.0) + 1.5 * vals.get("SeismicPGA", 0.1))
            
        # 3. Bridge Collapse Probability (depends on FloodLevel, SeismicPGA, and Reinforce_Bridge)
        if "BridgeCollapse" not in do_ops:
            reinforce_factor = 0.15 if vals.get("Reinforce_Bridge", False) else 1.0
            # Higher water and higher PGA increase collapse risk
            hazard_load = 0.5 * vals.get("FloodLevel", 0.0) + 2.0 * vals.get("SeismicPGA", 0.1)
            vals["BridgeCollapse"] = min(1.0, hazard_load * reinforce_factor)
            
        # 4. Road Blockage (depends on FloodLevel, LandslideRisk, BridgeCollapse, WindSpeed)
        if "RoadBlockage" not in do_ops:
            # high wind or water or collapse or landslides can block roads
            wind_blockage = max(0.0, (vals.get("WindSpeed", 45.0) - 60.0) / 100.0) if vals.get("WindSpeed", 45.0) > 60.0 else 0.0
            vals["RoadBlockage"] = min(
                1.0,
                0.3 * vals.get("FloodLevel", 0.0) + 
                0.7 * vals.get("LandslideRisk", 0.0) + 
                0.9 * vals.get("BridgeCollapse", 0.0) + 
                wind_blockage
            )
            
        # 5. Rescue Delay in minutes (depends on RoadBlockage)
        if "RescueDelay" not in do_ops:
            # Base delay plus blockage penalty
            vals["RescueDelay"] = 10.0 + 90.0 * vals.get("RoadBlockage", 0.0)
            
        # 6. Casualty Severity / Expected Fatalities (depends on RescueDelay, Evacuation_Order)
        if "CasualtySeverity" not in do_ops:
            evac_factor = 0.2 if vals.get("Evacuation_Order", False) else 1.0
            vals["CasualtySeverity"] = min(1.0, (0.015 * vals.get("RescueDelay", 10.0)) * evac_factor)
            
        return vals
