import networkx as nx
import math
from typing import List, Dict, Any, Tuple, Optional

class InformationGainEngine:
    """
    Formulates UAV scouting vs. Direct rescue decisions using Expected Value of Information (EVI)
    by comparing expected Mission Utility with and without UAV scouting scans.
    """

    @staticmethod
    def calculate_entropy(p: float) -> float:
        """
        Calculates Shannon entropy of a binary probability p.
        """
        p = max(1e-9, min(1.0 - 1e-9, p))
        return -p * math.log2(p) - (1.0 - p) * math.log2(1.0 - p)

    @classmethod
    def calculate_path_entropy(cls, path: List[str], belief_graph: nx.Graph) -> float:
        """
        Computes the total sum of confidence entropies along a path of nodes.
        An edge/node with confidence 1.0 has 0 entropy.
        An edge/node with confidence 0.5 has 1.0 entropy (maximum uncertainty).
        """
        total_entropy = 0.0
        for i in range(len(path) - 1):
            u, v = path[i], path[i+1]
            if belief_graph.has_edge(u, v):
                confidence = belief_graph.edges[u, v].get("confidence", 1.0)
                total_entropy += cls.calculate_entropy(confidence)
            else:
                total_entropy += 1.0  # High uncertainty for missing edges
        return total_entropy

    @classmethod
    def calculate_path_confidence(cls, path: List[str], belief_graph: nx.Graph) -> float:
        """
        Calculates path confidence as the product of individual edge and intermediate node confidences.
        """
        confidence = 1.0
        for i in range(len(path) - 1):
            u, v = path[i], path[i+1]
            # Edge confidence
            if belief_graph.has_edge(u, v):
                confidence *= belief_graph.edges[u, v].get("confidence", 1.0)
            else:
                confidence *= 0.1
            # Node confidence
            node_conf = belief_graph.nodes[v].get("confidence", belief_graph.nodes[v].get("p_state_correct", 1.0))
            confidence *= node_conf
        return max(0.0, min(1.0, confidence))

    @classmethod
    def evaluate_scout_vs_rescue(
        cls,
        path: List[str],
        target_node: str,
        belief_graph: nx.Graph,
        scout_speed_factor: float = 2.0,
        rescue_speed_factor: float = 1.0
    ) -> Dict[str, Any]:
        """
        Calculates the Expected Value of Information (EVI) for scouting the path before rescue.
        Formula:
          EVI = Expected Utility (Scout First) - Expected Utility (Direct Rescue)
          
        Where:
          Expected Utility (Direct Rescue) = P_conf * U_success + (1 - P_conf) * U_failure
          Expected Utility (Scout First) = P_conf * (U_success - Scout_Cost) + (1 - P_conf) * (U_alt - Scout_Cost)
        """
        node_data = belief_graph.nodes.get(target_node, {})
        triage_immediate = node_data.get("triage_immediate", 0) or 0
        triage_delayed = node_data.get("triage_delayed", 0) or 0
        population = node_data.get("population", 0) or 0
        
        # Target urgency score (lives saved reward baseline)
        u_success = (triage_immediate * 5.0) + (triage_delayed * 2.0) + (population * 0.1) + 1.0
        
        # Path properties
        path_entropy = cls.calculate_path_entropy(path, belief_graph)
        path_confidence = cls.calculate_path_confidence(path, belief_graph)
        
        # Estimate path length (distance sum)
        path_dist = 0.0
        for i in range(len(path) - 1):
            u, v = path[i], path[i+1]
            if belief_graph.has_edge(u, v):
                path_dist += belief_graph.edges[u, v].get("distance", 500.0)
            else:
                path_dist += 500.0
        
        # Convert distance to km
        dist_km = path_dist / 1000.0
        
        # Cost of scouting (depends on length and scout speed)
        scout_cost = (dist_km * 1.5) / max(0.5, scout_speed_factor)
        
        # Failure penalty (wasted rescue time, vehicle stranded, risk of injury)
        u_failure = -(u_success * 1.2) - (dist_km * 4.0 / max(0.5, rescue_speed_factor))
        
        # Alternative action utility (no rescue sent down this path, resources allocated elsewhere)
        u_alt = 0.0
        
        # Calculate Expected Utilities
        u_without_info = path_confidence * u_success + (1.0 - path_confidence) * u_failure
        u_with_info = path_confidence * (u_success - scout_cost) + (1.0 - path_confidence) * (u_alt - scout_cost)
        
        # EVI calculation
        evi = u_with_info - u_without_info
        
        # Recommendation decision threshold
        # Send scout if EVI is positive (scouting adds value) or confidence is extremely low (below 0.6)
        recommendation = "SCOUT" if (evi > 0.0 or path_confidence < 0.6) else "RESCUE"
        
        reasoning = (
            f"EVI is {evi:.2f} (Scouting Utility: {u_with_info:.2f} vs. Direct Rescue Utility: {u_without_info:.2f}). "
            f"Path confidence: {path_confidence*100:.1f}%, path entropy: {path_entropy:.2f}. "
            f"Scouting cost is {scout_cost:.2f}, while failure penalty is {u_failure:.2f}."
        )

        return {
            "recommendation": recommendation,
            "path_confidence": path_confidence,
            "path_entropy": path_entropy,
            "u_with_info": u_with_info,
            "u_without_info": u_without_info,
            "scout_cost": scout_cost,
            "evi": evi,
            "reasoning": reasoning
        }

    @classmethod
    def evaluate_active_scouting_loop(
        cls,
        scout_id: str,
        current_node: str,
        target_node: Optional[str],
        current_path: List[str],
        belief_graph: nx.Graph,
        weather_state: Optional[Dict[str, Any]] = None,
        battery_level: float = 100.0,
        evi_thresholds: Optional[Dict[str, float]] = None,
        scout_speed_factor: float = 2.0,
        rescue_speed_factor: float = 1.0,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Evaluates UAV status and surroundings to select the optimal information acquisition action:
        - WAIT: Grounded due to battery, severe weather, or lack of targets.
        - SCAN: Spend a step performing a high-resolution sensor scan of the current node.
        - DISPATCH: Direct UAV to target a high EVI node.
        - REROUTE: Swap active targets because a higher EVI node is detected or the current path degraded.
        - LAUNCH: Drone takes off from base shelter/hospital to inspect a target node.
        """
        # 1. Establish Default Thresholds
        if evi_thresholds is None:
            evi_thresholds = {
                "launch": 0.5,
                "scan": 0.8,
                "dispatch": 0.4,
                "reroute": 0.3,
                "wait": 0.1
            }

        # 2. Check Severe Environmental & Physical Fail-Safes
        if battery_level < 15.0:
            return {
                "action": "WAIT",
                "target_node": None,
                "path": [],
                "evi": 0.0,
                "reasoning": f"Battery is critically low at {battery_level:.1f}%. Halting operations for emergency recharge.",
                "metrics": {"battery_level": battery_level, "wind_speed": 0.0, "rain_intensity": 0.0}
            }

        wind_speed = 0.0
        rain_intensity = 0.0
        if weather_state:
            # Handle possible keys from different sources
            wind_speed = weather_state.get("wind_speed", weather_state.get("wind_speed_kmh", weather_state.get("windspeed", 0.0)))
            rain_intensity = weather_state.get("rain_intensity", weather_state.get("rainfall", 0.0))

        if wind_speed > 55.0 or rain_intensity > 75.0:
            return {
                "action": "WAIT",
                "target_node": None,
                "path": [],
                "evi": 0.0,
                "reasoning": f"Severe weather conditions detected (Wind: {wind_speed:.1f} km/h, Rain: {rain_intensity:.1f} mm/h). Grounding UAV for safety.",
                "metrics": {"battery_level": battery_level, "wind_speed": wind_speed, "rain_intensity": rain_intensity}
            }

        # 3. Find Best Candidate Target in the graph
        best_candidate = None
        best_evi = -float('inf')
        best_path = []
        best_eval_res = {}

        # Scan nodes that aren't safe havens and find a reachable path
        candidates = []
        for n_id, ndata in belief_graph.nodes(data=True):
            if n_id == current_node or ndata.get('node_type') in ("SHELTER", "HOSPITAL"):
                continue
            if not nx.has_path(belief_graph, current_node, n_id):
                continue
            candidates.append(n_id)

        # Limit search to 50 closest reachable nodes to avoid performance bottlenecks
        try:
            lengths = nx.single_source_dijkstra_path_length(belief_graph, current_node, weight='distance')
            valid_candidates = [c for c in candidates if c in lengths]
            valid_candidates.sort(key=lambda c: lengths[c])
        except Exception:
            valid_candidates = []

        for candidate_id in valid_candidates[:50]:
            try:
                path = nx.shortest_path(belief_graph, current_node, candidate_id, weight='distance')
                eval_res = cls.evaluate_scout_vs_rescue(
                    path=path,
                    target_node=candidate_id,
                    belief_graph=belief_graph,
                    scout_speed_factor=scout_speed_factor,
                    rescue_speed_factor=rescue_speed_factor
                )
                evi = eval_res["evi"]
                if evi > best_evi:
                    best_evi = evi
                    best_candidate = candidate_id
                    best_path = path
                    best_eval_res = eval_res
            except Exception:
                continue

        # 4. Check scan condition (at current location)
        node_data = belief_graph.nodes.get(current_node, {})
        node_conf = node_data.get("confidence", node_data.get("p_state_correct", 1.0))
        if node_conf < 0.8:
            local_scan_evi = (1.0 - node_conf) * 1.5
            if local_scan_evi >= evi_thresholds["scan"]:
                return {
                    "action": "SCAN",
                    "target_node": current_node,
                    "path": [current_node],
                    "evi": local_scan_evi,
                    "reasoning": f"UAV is at node {current_node} with high uncertainty (confidence: {node_conf*100:.1f}%). Performing local sensor scan to resolve state.",
                    "metrics": {"battery_level": battery_level, "node_confidence": node_conf, "local_scan_evi": local_scan_evi}
                }

        # 5. Check Reroute Condition
        if target_node is not None and current_path:
            try:
                current_eval = cls.evaluate_scout_vs_rescue(
                    path=current_path,
                    target_node=target_node,
                    belief_graph=belief_graph,
                    scout_speed_factor=scout_speed_factor,
                    rescue_speed_factor=rescue_speed_factor
                )
                current_evi = current_eval["evi"]
            except Exception:
                current_evi = -float('inf')

            path_confidence = cls.calculate_path_confidence(current_path, belief_graph)
            if path_confidence < 0.4:
                return {
                    "action": "REROUTE",
                    "target_node": best_candidate,
                    "path": best_path,
                    "evi": best_evi,
                    "reasoning": f"Current path confidence has deteriorated to {path_confidence*100:.1f}%. Rerouting to target {best_candidate} with EVI {best_evi:.2f}.",
                    "metrics": {"battery_level": battery_level, "best_evi": best_evi, "current_evi": current_evi, "path_confidence": path_confidence}
                }
            elif best_candidate and best_candidate != target_node and best_evi > current_evi + evi_thresholds["reroute"]:
                return {
                    "action": "REROUTE",
                    "target_node": best_candidate,
                    "path": best_path,
                    "evi": best_evi,
                    "reasoning": f"Found significantly higher value target {best_candidate} (EVI: {best_evi:.2f} vs. current EVI: {current_evi:.2f}). Initiating reroute.",
                    "metrics": {"battery_level": battery_level, "best_evi": best_evi, "current_evi": current_evi, "path_confidence": path_confidence}
                }

        # 6. Check Launch Condition (if at base/haven and idle)
        is_at_base = node_data.get("node_type") in ("SHELTER", "HOSPITAL")
        if is_at_base and (target_node is None or not current_path):
            if best_candidate and best_evi >= evi_thresholds["launch"]:
                return {
                    "action": "LAUNCH",
                    "target_node": best_candidate,
                    "path": best_path,
                    "evi": best_evi,
                    "reasoning": f"Launching UAV from base shelter/hospital to target {best_candidate}. Target EVI {best_evi:.2f} satisfies launch threshold {evi_thresholds['launch']:.2f}.",
                    "metrics": {"battery_level": battery_level, "best_evi": best_evi}
                }

        # 7. Check Dispatch Condition (in the field and idle)
        if best_candidate and best_evi >= evi_thresholds["dispatch"]:
            return {
                "action": "DISPATCH",
                "target_node": best_candidate,
                "path": best_path,
                "evi": best_evi,
                "reasoning": f"Dispatching active UAV in the field to target {best_candidate} with EVI {best_evi:.2f}.",
                "metrics": {"battery_level": battery_level, "best_evi": best_evi}
            }

        # 8. Check Wait Condition (EVI below wait threshold, or no candidates)
        wait_reason = "No candidates found to scout."
        if best_candidate:
            wait_reason = f"Best target candidate {best_candidate} EVI {best_evi:.2f} is below wait threshold {evi_thresholds['wait']:.2f}."
        
        return {
            "action": "WAIT",
            "target_node": None,
            "path": [],
            "evi": best_evi if best_candidate else 0.0,
            "reasoning": f"UAV is waiting. Reason: {wait_reason}",
            "metrics": {"battery_level": battery_level, "best_evi": best_evi if best_candidate else 0.0}
        }

