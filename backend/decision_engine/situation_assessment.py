import networkx as nx
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.world_model.node import NodeModel
from backend.world_model.edge import EdgeModel

class SituationAssessmentEngine:
    """
    Computes aggregate structured state (severity metrics, triage demands, and damage ratios)
    from the current disaster situation using the database and/or NetworkX belief graph.
    Computes indices on a 0-100 scale. Also computes decision stability index and explainability scores.
    """

    _last_portfolio: Optional[List[Dict[str, Any]]] = None

    @staticmethod
    def calculate_decision_stability(
        current_portfolio: Optional[List[Dict[str, Any]]],
        previous_portfolio: Optional[List[Dict[str, Any]]] = None
    ) -> float:
        """
        Calculates a decision stability index on a 0-100 scale.
        Tracks recommendation fluctuations between steps based on vehicle-target assignment overlap.
        """
        if previous_portfolio is None:
            previous_portfolio = SituationAssessmentEngine._last_portfolio
        
        if not previous_portfolio or not current_portfolio:
            return 100.0
            
        curr_assignments = {}
        for alt in current_portfolio:
            alt_id = alt.get("alternative_id", "default")
            for a in alt.get("assignments", []):
                curr_assignments[(alt_id, a.get("vehicle_id"))] = a.get("target_node")

        prev_assignments = {}
        for alt in previous_portfolio:
            alt_id = alt.get("alternative_id", "default")
            for a in alt.get("assignments", []):
                prev_assignments[(alt_id, a.get("vehicle_id"))] = a.get("target_node")

        if not curr_assignments or not prev_assignments:
            return 100.0

        matches = 0
        total = max(len(curr_assignments), len(prev_assignments))
        for key, target in curr_assignments.items():
            if key in prev_assignments and prev_assignments[key] == target:
                matches += 1

        return (matches / total) * 100.0

    @classmethod
    def assess_from_graph(
        cls, 
        belief_graph: nx.Graph, 
        current_portfolio: Optional[List[Dict[str, Any]]] = None,
        previous_portfolio: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Computes assessment metrics directly from the NetworkX belief graph.
        Vectorized using NodeStateTensor and EdgeStateTensor fallback compilation.
        Returns indices on a 0-100 scale.
        """
        total_nodes = len(belief_graph.nodes)
        if total_nodes == 0:
            return {
                "severity_index": 0.0,
                "medical_severity_index": 0.0,
                "infrastructure_damage_index": 0.0,
                "communication_coverage_index": 100.0,
                "resource_stress_index": 0.0,
                "decision_confidence_index": 100.0,
                "decision_stability_index": 100.0,
                "total_triage_immediate": 0,
                "total_triage_delayed": 0,
                "total_triage_minor": 0,
                "active_demands": {"medical": 0.0, "evacuation": 0.0, "scouting": 0.0},
                "damage_ratios": {
                    "blocked_roads": 0.0,
                    "compromised_hospitals": 0.0,
                    "compromised_shelters": 0.0,
                    "affected_population": 0.0
                },
                "explainability_scores": {
                    "coverage": 100.0,
                    "transparency": 100.0,
                    "evidence_sources": 100.0,
                    "forecast_dependency": 0.0
                }
            }

        import numpy as np
        from backend.world_model.world_state import world_state
        
        # Load or compile tensors
        nst = getattr(world_state, 'node_state_tensor', None)
        est = getattr(world_state, 'edge_state_tensor', None)
        
        if nst is None or est is None:
            # Lazy initialize and sync for standalone tests
            from backend.world_model.node_state_tensor import NodeStateTensor
            from backend.world_model.edge_state_tensor import EdgeStateTensor
            
            nst = NodeStateTensor(len(belief_graph.nodes))
            nst.sync_from_graph(belief_graph)
            
            est = EdgeStateTensor(len(belief_graph.edges))
            est.sync_from_graph(belief_graph)

        total_edges = len(belief_graph.edges)
        
        # Vectorized calculations from EdgeStateTensor (est)
        blocked_edges = int(np.sum(est.blocked[:total_edges]))
        
        # Vectorized calculations from NodeStateTensor (nst)
        danger_sum = float(np.sum(nst.p_danger[:total_nodes]))
        total_population = int(np.sum(nst.population[:total_nodes]))
        
        # status codes: SAFE=0, DANGER=1, COMPROMISED=2, FLOODED=3
        status_arr = nst.status_mask[:total_nodes]
        dangers_arr = nst.p_danger[:total_nodes]
        
        status_danger_mask = (status_arr == 1) | (status_arr == 2) | (status_arr == 3)
        prob_danger_mask = dangers_arr > 0.5
        affected_mask = status_danger_mask | prob_danger_mask
        
        affected_population = int(np.sum(nst.population[:total_nodes][affected_mask]))
        
        total_immediate = int(np.sum(nst.triage[:total_nodes, 0]))
        total_delayed = int(np.sum(nst.triage[:total_nodes, 1]))
        total_minor = int(np.sum(nst.triage[:total_nodes, 2]))
        
        # node types: ROAD=0, BRIDGE=1, HOSPITAL=2, SHELTER=3, POPULATION_ZONE=4, JUNCTION=5, DEPOT=6
        type_arr = nst.node_type_mask[:total_nodes]
        
        hospital_mask = type_arr == 2
        total_hospitals = int(np.sum(hospital_mask))
        compromised_hospitals = int(np.sum((status_arr == 2) & hospital_mask))
        
        shelter_mask = type_arr == 3
        total_shelters = int(np.sum(shelter_mask))
        compromised_shelters = int(np.sum(((status_arr == 2) | (status_arr == 3)) & shelter_mask))

        # Calculate Demands
        medical_demand = (total_immediate * 1.0) + (total_delayed * 0.5) + (total_minor * 0.1)
        evacuation_demand = (affected_population * 0.1) + (total_immediate * 1.5) + (total_delayed * 1.0)
        
        avg_danger = danger_sum / total_nodes
        scouting_demand = avg_danger * (blocked_edges / max(1, total_edges))

        blocked_ratio = blocked_edges / total_edges if total_edges > 0 else 0.0
        hospital_ratio = compromised_hospitals / total_hospitals if total_hospitals > 0 else 0.0
        shelter_ratio = compromised_shelters / total_shelters if total_shelters > 0 else 0.0
        pop_ratio = affected_population / total_population if total_population > 0 else 0.0

        # Severity index
        severity_index = min(100.0, max(0.0, (
            0.3 * avg_danger +
            0.3 * blocked_ratio +
            0.2 * hospital_ratio +
            0.2 * pop_ratio
        ) * 100.0))

        # medical_severity_index
        total_triage = total_immediate + total_delayed + total_minor
        if total_triage > 0:
            medical_severity_index = min(100.0, (total_immediate * 20.0 + total_delayed * 8.0 + total_minor * 2.0) / max(1, total_triage) * 10.0)
        else:
            medical_severity_index = 0.0

        # infrastructure_damage_index
        infrastructure_damage_index = min(100.0, max(0.0, (
            0.4 * blocked_ratio +
            0.3 * hospital_ratio +
            0.3 * shelter_ratio
        ) * 100.0))

        # communication_coverage_index
        communication_coverage_index = float(np.mean(nst.comm_coverage[:total_nodes]) * 100.0)

        # resource_stress_index
        num_depots = int(np.sum(type_arr == 6))
        if num_depots == 0:
            num_depots = 2
        resource_stress_index = min(100.0, max(0.0, (medical_demand + evacuation_demand + scouting_demand) * 10.0 / max(1.0, num_depots * 5.0)))

        # decision_confidence_index
        node_confs = nst.p_state_correct[:total_nodes]
        edge_confs = est.confidence[:total_edges]
        all_confs = np.concatenate([node_confs, edge_confs])
        decision_confidence_index = float(np.mean(all_confs) * 100.0) if len(all_confs) > 0 else 100.0

        # Decision Stability
        stability_index = cls.calculate_decision_stability(current_portfolio, previous_portfolio)
        if current_portfolio is not None:
            cls._last_portfolio = current_portfolio

        # Explainability Scores
        observed_nodes = int(np.sum(nst.observation_age[:total_nodes] >= 0.0))
        coverage_score = (observed_nodes / total_nodes * 100.0) if total_nodes > 0 else 100.0
        
        transparency_score = decision_confidence_index
        
        high_conf_nodes = int(np.sum(nst.p_state_correct[:total_nodes] >= 0.8))
        evidence_sources_score = (high_conf_nodes / total_nodes * 100.0) if total_nodes > 0 else 100.0

        ages = nst.observation_age[:total_nodes]
        avg_age = float(np.mean(ages)) if len(ages) > 0 else 0.0
        forecast_dependency_score = min(100.0, (avg_age / 120.0) * 100.0)

        return {
            "severity_index": severity_index,
            "medical_severity_index": medical_severity_index,
            "infrastructure_damage_index": infrastructure_damage_index,
            "communication_coverage_index": communication_coverage_index,
            "resource_stress_index": resource_stress_index,
            "decision_confidence_index": decision_confidence_index,
            "decision_stability_index": stability_index,
            "total_triage_immediate": total_immediate,
            "total_triage_delayed": total_delayed,
            "total_triage_minor": total_minor,
            "active_demands": {
                "medical": medical_demand,
                "evacuation": evacuation_demand,
                "scouting": scouting_demand
            },
            "damage_ratios": {
                "blocked_roads": blocked_ratio,
                "compromised_hospitals": hospital_ratio,
                "compromised_shelters": shelter_ratio,
                "affected_population": pop_ratio
            },
            "explainability_scores": {
                "coverage": round(coverage_score, 2),
                "transparency": round(transparency_score, 2),
                "evidence_sources": round(evidence_sources_score, 2),
                "forecast_dependency": round(forecast_dependency_score, 2)
            }
        }

    @classmethod
    def assess_from_db(
        cls, 
        db: Session, 
        current_portfolio: Optional[List[Dict[str, Any]]] = None,
        previous_portfolio: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Computes situation assessment metrics directly from the DB models.
        Returns indices on a 0-100 scale.
        """
        nodes = db.query(NodeModel).all()
        edges = db.query(EdgeModel).all()

        total_nodes = len(nodes)
        if total_nodes == 0:
            return {
                "severity_index": 0.0,
                "medical_severity_index": 0.0,
                "infrastructure_damage_index": 0.0,
                "communication_coverage_index": 100.0,
                "resource_stress_index": 0.0,
                "decision_confidence_index": 100.0,
                "decision_stability_index": 100.0,
                "total_triage_immediate": 0,
                "total_triage_delayed": 0,
                "total_triage_minor": 0,
                "active_demands": {"medical": 0.0, "evacuation": 0.0, "scouting": 0.0},
                "damage_ratios": {
                    "blocked_roads": 0.0,
                    "compromised_hospitals": 0.0,
                    "compromised_shelters": 0.0,
                    "affected_population": 0.0
                },
                "explainability_scores": {
                    "coverage": 100.0,
                    "transparency": 100.0,
                    "evidence_sources": 100.0,
                    "forecast_dependency": 0.0
                }
            }

        total_edges = len(edges)
        blocked_edges = sum(1 for e in edges if e.blocked)

        total_population = 0
        affected_population = 0
        total_immediate = 0
        total_delayed = 0
        total_minor = 0

        total_hospitals = 0
        compromised_hospitals = 0
        total_shelters = 0
        compromised_shelters = 0
        danger_sum = 0.0

        for node in nodes:
            status = node.status
            pop = node.population or 0
            p_danger = node.p_danger or 0.0

            danger_sum += p_danger
            total_population += pop
            if status in ("DANGER", "COMPROMISED", "FLOODED") or p_danger > 0.5:
                affected_population += pop

            total_immediate += node.triage_immediate or 0
            total_delayed += node.triage_delayed or 0
            total_minor += node.triage_minor or 0

            if node.node_type == "HOSPITAL":
                total_hospitals += 1
                if status == "COMPROMISED":
                    compromised_hospitals += 1
            elif node.node_type == "SHELTER":
                total_shelters += 1
                if status in ("COMPROMISED", "FLOODED"):
                    compromised_shelters += 1

        avg_danger = danger_sum / total_nodes
        medical_demand = (total_immediate * 1.0) + (total_delayed * 0.5) + (total_minor * 0.1)
        evacuation_demand = (affected_population * 0.1) + (total_immediate * 1.5) + (total_delayed * 1.0)
        scouting_demand = avg_danger * (blocked_edges / max(1, total_edges))

        blocked_ratio = blocked_edges / total_edges if total_edges > 0 else 0.0
        hospital_ratio = compromised_hospitals / total_hospitals if total_hospitals > 0 else 0.0
        shelter_ratio = compromised_shelters / total_shelters if total_shelters > 0 else 0.0
        pop_ratio = affected_population / total_population if total_population > 0 else 0.0

        # Severity index combines node danger, blocked roads, and critical facility compromise (scaled 0-100)
        severity_index = min(100.0, max(0.0, (
            0.3 * avg_danger +
            0.3 * blocked_ratio +
            0.2 * hospital_ratio +
            0.2 * pop_ratio
        ) * 100.0))

        # medical_severity_index (0-100 scale)
        total_triage = total_immediate + total_delayed + total_minor
        if total_triage > 0:
            medical_severity_index = min(100.0, (total_immediate * 20.0 + total_delayed * 8.0 + total_minor * 2.0) / max(1, total_triage) * 10.0)
        else:
            medical_severity_index = 0.0

        # infrastructure_damage_index (0-100 scale)
        infrastructure_damage_index = min(100.0, max(0.0, (
            0.4 * blocked_ratio +
            0.3 * hospital_ratio +
            0.3 * shelter_ratio
        ) * 100.0))

        # communication_coverage_index (0-100 scale)
        comm_vals = []
        for node in nodes:
            comm = getattr(node, "comm_coverage", None)
            if comm is None:
                status = node.status
                if status == "COMPROMISED":
                    comm = 0.0
                elif status in ("DANGER", "FLOODED"):
                    comm = 0.5
                else:
                    comm = 1.0
            comm_vals.append(comm)
        communication_coverage_index = (sum(comm_vals) / len(comm_vals) * 100.0) if comm_vals else 100.0

        # resource_stress_index (0-100 scale)
        num_depots = sum(1 for node in nodes if node.node_type == "DEPOT")
        if num_depots == 0:
            num_depots = 2
        resource_stress_index = min(100.0, max(0.0, (medical_demand + evacuation_demand + scouting_demand) * 10.0 / max(1.0, num_depots * 5.0)))

        # decision_confidence_index (0-100 scale)
        node_confs = [node.p_state_correct if node.p_state_correct is not None else 1.0 for node in nodes]
        edge_confs = [edge.confidence if edge.confidence is not None else 1.0 for edge in edges]
        all_confs = node_confs + edge_confs
        decision_confidence_index = (sum(all_confs) / len(all_confs) * 100.0) if all_confs else 100.0

        # Decision Stability
        stability_index = cls.calculate_decision_stability(current_portfolio, previous_portfolio)
        if current_portfolio is not None:
            cls._last_portfolio = current_portfolio

        # Explainability Scores
        observed_nodes = sum(1 for node in nodes if getattr(node, "last_observed", None) is not None)
        coverage_score = (observed_nodes / total_nodes * 100.0) if total_nodes > 0 else 100.0

        transparency_score = decision_confidence_index

        high_conf_nodes = sum(1 for node in nodes if (node.p_state_correct if node.p_state_correct is not None else 1.0) >= 0.8)
        evidence_sources_score = (high_conf_nodes / total_nodes * 100.0) if total_nodes > 0 else 100.0

        # Forecast dependency calculation from observation ages
        from datetime import datetime
        current_time = datetime.utcnow()
        ages = []
        for node in nodes:
            last_obs = getattr(node, "last_observed", None)
            if last_obs:
                if isinstance(last_obs, str):
                    try:
                        last_obs = datetime.fromisoformat(last_obs)
                    except ValueError:
                        last_obs = current_time
                diff = (current_time - last_obs).total_seconds()
                ages.append(max(0.0, diff / 60.0))
            else:
                ages.append(120.0)
        avg_age = sum(ages) / len(ages) if ages else 0.0
        forecast_dependency_score = min(100.0, (avg_age / 120.0) * 100.0)

        return {
            "severity_index": severity_index,
            "medical_severity_index": medical_severity_index,
            "infrastructure_damage_index": infrastructure_damage_index,
            "communication_coverage_index": communication_coverage_index,
            "resource_stress_index": resource_stress_index,
            "decision_confidence_index": decision_confidence_index,
            "decision_stability_index": stability_index,
            "total_triage_immediate": total_immediate,
            "total_triage_delayed": total_delayed,
            "total_triage_minor": total_minor,
            "active_demands": {
                "medical": medical_demand,
                "evacuation": evacuation_demand,
                "scouting": scouting_demand
            },
            "damage_ratios": {
                "blocked_roads": blocked_ratio,
                "compromised_hospitals": hospital_ratio,
                "compromised_shelters": shelter_ratio,
                "affected_population": pop_ratio
            },
            "explainability_scores": {
                "coverage": round(coverage_score, 2),
                "transparency": round(transparency_score, 2),
                "evidence_sources": round(evidence_sources_score, 2),
                "forecast_dependency": round(forecast_dependency_score, 2)
            }
        }
