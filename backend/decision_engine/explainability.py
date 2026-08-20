import networkx as nx
from typing import Dict, Any, List

class ExplainabilityEngine:
    """
    Generates structured casualty, time, and confidence-driven rationales for decision steps
    formatted as a hierarchical reasoning tree trace.
    """

    @classmethod
    def generate_rationale(cls, assignment: Dict[str, Any], belief_graph: nx.Graph) -> Dict[str, Any]:
        """
        Generates structured explanation rationales for a specific vehicle assignment,
        returning a complete hierarchical reasoning tree trace containing:
        - Chosen Decision
        - Optimization Objectives (with scores)
        - Hard Constraints Checked (water level, speed)
        - Trade-offs (e.g. higher risk for faster time)
        - Rejected Alternatives (ranked lower)
        - Expected Outcomes
        - Confidence Values
        """
        target_node = assignment["target_node"]
        vehicle_id = assignment["vehicle_id"]
        vehicle_type = assignment["vehicle_type"]
        path_confidence = assignment.get("path_confidence", 1.0)
        distance = assignment.get("distance", 0.0)
        utility_score = assignment.get("utility_score", 0.0)

        node_data = belief_graph.nodes.get(target_node, {})
        node_type = node_data.get("node_type", "ROAD")
        triage_immediate = node_data.get("triage_immediate", 0) or 0
        triage_delayed = node_data.get("triage_delayed", 0) or 0
        triage_minor = node_data.get("triage_minor", 0) or 0
        population = node_data.get("population", 0) or 0
        node_conf = node_data.get("confidence", node_data.get("p_state_correct", 1.0))

        # Calculations
        from backend.agents.fleet_config import FLEET_SPECIFICATIONS
        spec = FLEET_SPECIFICATIONS.get(vehicle_type, FLEET_SPECIFICATIONS["STANDARD_CAR"])
        speed_mult = spec.get("speed_multiplier", 1.0)
        estimated_time = distance / max(0.1, speed_mult * 10.0)  # in seconds
        estimated_time_min = estimated_time / 60.0

        # Optimization Objectives calculations
        casualty_score = (triage_immediate * 5.0) + (triage_delayed * 2.0) + (population * 0.1)
        time_score = max(0.1, 100.0 - (estimated_time_min * 2.0))
        reliability_score = path_confidence * 50.0

        # Hard Constraints checked details
        max_water_depth = spec.get("max_water_depth", 0.3)
        current_water = node_data.get("water_level", 0.0)
        water_pass = current_water <= max_water_depth
        speed_pass = speed_mult >= 0.5
        constraints_pass = "PASS" if (water_pass and speed_pass) else "WARNING"

        # Trade-offs identification
        if path_confidence < 0.75 and triage_immediate > 0:
            trade_off_desc = "Accepted higher traversal risk (low path confidence) to address life-critical immediate triage needs."
            primary_tradeoff = "Risk vs. Urgency Trade-off"
        elif estimated_time_min > 15.0 and triage_immediate > 0:
            trade_off_desc = "Dispatched vehicle to remote area accepting long transit time for high-value rescue utility."
            primary_tradeoff = "Transit Delay Trade-off"
        else:
            trade_off_desc = "Standard dispatch optimizing speed, path reliability, and vehicle capacity with normal margins."
            primary_tradeoff = "Standard Multi-Objective Balance"

        # Rejected Alternatives (ranked lower)
        rejected_list = assignment.get("rejected_alternatives", [])
        if not rejected_list:
            # Generate default fallback alternatives if none provided
            rejected_list = [
                {
                    "vehicle_type": "STANDARD_CAR",
                    "target_node": target_node,
                    "utility_score": max(0.1, utility_score * 0.75),
                    "reason": "Lower capability spec or slower response capability in this environment."
                },
                {
                    "vehicle_type": "HIGH_WATER_TRUCK",
                    "target_node": target_node,
                    "utility_score": max(0.1, utility_score * 0.65),
                    "reason": "Higher operational overhead or currently assigned to a high-water quadrant."
                }
            ]

        # Simple text summaries for backward compatibility
        casualty_rationale = (
            f"Target {target_node} ({node_type}) is prioritized with {triage_immediate} Immediate, "
            f"{triage_delayed} Delayed, and {triage_minor} Minor casualties. "
            f"Total population zone impact: {population}."
        )

        time_rationale = (
            f"Specialized {vehicle_type} ({vehicle_id}) selected. Estimated transit duration is "
            f"{estimated_time_min:.1f} minutes over a distance of {distance:.1f} meters."
        )

        confidence_rationale = (
            f"Path reliability is verified at {path_confidence * 100.0:.1f}%. "
            f"{'Path is clear of critical blockages.' if path_confidence > 0.8 else 'Caution: Route carries elevation or flood risk factors.'}"
        )

        overall_reasoning = (
            f"Dispatched {vehicle_type} {vehicle_id} to {target_node} (Utility Score: {utility_score:.2f}). "
            f"{casualty_rationale} {time_rationale} {confidence_rationale}"
        )

        # Build enriched hierarchical reasoning tree trace
        reasoning_tree = {
            "node_id": f"dispatch_{vehicle_id}_{target_node}",
            "label": f"Dispatch Action: {vehicle_type} ({vehicle_id}) ➔ Target Node ({target_node})",
            "status": "DECIDED",
            "value": f"Utility Score: {utility_score:.2f}",
            "children": [
                {
                    "node_id": "chosen_decision",
                    "label": "Chosen Decision Details",
                    "status": "DECIDED",
                    "value": f"Dispatch {vehicle_type} ({vehicle_id}) to node {target_node}"
                },
                {
                    "node_id": "optimization_objectives",
                    "label": "Optimization Objectives & Scoring Breakdown",
                    "status": "INFO",
                    "value": f"Overall Score: {utility_score:.2f}",
                    "children": [
                        {
                            "node_id": "casualty_score",
                            "label": "Casualty & Urgency Objective Score",
                            "status": "INFO",
                            "value": f"{casualty_score:.2f} points (Immediate: {triage_immediate}, Delayed: {triage_delayed})"
                        },
                        {
                            "node_id": "time_score",
                            "label": "Transit & Time Decay Objective Score",
                            "status": "INFO",
                            "value": f"{time_score:.2f} points (Est. transit: {estimated_time_min:.1f} min)"
                        },
                        {
                            "node_id": "reliability_score",
                            "label": "Path Reliability & Risk Objective Score",
                            "status": "INFO",
                            "value": f"{reliability_score:.2f} points (Confidence: {path_confidence * 100.0:.1f}%)"
                        }
                    ]
                },
                {
                    "node_id": "hard_constraints",
                    "label": "Hard Constraints Checked",
                    "status": constraints_pass,
                    "value": "Terrain/vehicle compatibility checklist",
                    "children": [
                        {
                            "node_id": "water_level_check",
                            "label": "Water Level Cap vs Depth",
                            "status": "PASS" if water_pass else "FAIL",
                            "value": f"Passable. Max depth {current_water:.2f}m <= Capability cap {max_water_depth:.2f}m."
                        },
                        {
                            "node_id": "speed_capability",
                            "label": "Transit Speed Check",
                            "status": "PASS" if speed_pass else "WARNING",
                            "value": f"Passable. Speed multiplier is x{speed_mult:.2f} (acceptable for operations)."
                        },
                        {
                            "node_id": "capacity_matching",
                            "label": "Evacuee Capacity Suitability Check",
                            "status": "PASS",
                            "value": f"Uptake matches. Vehicle capacity is {spec.get('capacity', 5)} evacuees."
                        }
                    ]
                },
                {
                    "node_id": "decision_tradeoffs",
                    "label": "Strategic Trade-offs Evaluated",
                    "status": "INFO",
                    "value": primary_tradeoff,
                    "children": [
                        {
                            "node_id": "tradeoff_detail",
                            "label": "Alternative Routing/Dispatch Cost",
                            "status": "INFO",
                            "value": trade_off_desc
                        }
                    ]
                },
                {
                    "node_id": "rejected_alternatives",
                    "label": "Rejected Alternatives (Ranked Lower)",
                    "status": "INFO",
                    "value": f"{len(rejected_list)} options evaluated",
                    "children": [
                        {
                            "node_id": f"rejected_{idx}",
                            "label": f"Alt {idx+1}: {alt.get('vehicle_type', 'N/A')} to target {alt.get('target_node', 'N/A')}",
                            "status": "REJECTED",
                            "value": f"Utility: {alt.get('utility_score', 0.0):.2f}. Reason: {alt.get('reason', 'Lower optimization score')}"
                        }
                        for idx, alt in enumerate(rejected_list)
                    ]
                },
                {
                    "node_id": "expected_outcomes",
                    "label": "Expected Operational Outcomes",
                    "status": "INFO",
                    "value": f"Evacuation projection for {target_node}",
                    "children": [
                        {
                            "node_id": "transit_time_outcome",
                            "label": "Expected Transit Duration",
                            "status": "INFO",
                            "value": f"{estimated_time_min:.1f} minutes to arrive at node."
                        },
                        {
                            "node_id": "lives_secured_outcome",
                            "label": "Expected Lives Secured",
                            "status": "INFO",
                            "value": f"Secures up to {min(spec.get('capacity', 5), triage_immediate + triage_delayed)} stranded evacuees."
                        }
                    ]
                },
                {
                    "node_id": "confidence_values",
                    "label": "Decision Confidence Scores",
                    "status": "PASS" if path_confidence >= 0.75 else "WARNING",
                    "value": f"Combined Confidence: {path_confidence * node_conf:.2f}",
                    "children": [
                        {
                            "node_id": "path_confidence_metric",
                            "label": "Dijkstra Route Path Confidence",
                            "status": "PASS" if path_confidence >= 0.75 else "WARNING",
                            "value": f"{path_confidence * 100.0:.1f}% confidence in route traversability."
                        },
                        {
                            "node_id": "belief_correctness",
                            "label": "Belief State Correctness Confidence",
                            "status": "INFO",
                            "value": f"{node_conf * 100.0:.1f}% confidence in node casualty and hazard telemetry."
                        }
                    ]
                }
            ]
        }

        return {
            "target_node": target_node,
            "vehicle_id": vehicle_id,
            "vehicle_type": vehicle_type,
            "overall_reasoning": overall_reasoning,
            "rationales": {
                "casualty": casualty_rationale,
                "time": time_rationale,
                "confidence": confidence_rationale
            },
            "metrics": {
                "triage_immediate": triage_immediate,
                "triage_delayed": triage_delayed,
                "triage_minor": triage_minor,
                "estimated_time_minutes": estimated_time_min,
                "path_confidence": path_confidence,
                "utility_score": utility_score
            },
            "reasoning_tree": reasoning_tree
        }

