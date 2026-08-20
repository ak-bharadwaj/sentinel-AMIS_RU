import networkx as nx
import math
from datetime import datetime
from typing import Dict, Any, Optional, List

class UncertaintyEngine:
    """
    Attaches probability, confidence, observation age, reliability, consistency,
    and visual confidence overlays (Known/Green, Partially Known/Yellow, Unknown/Red, No obs/Grey)
    properties to nodes and edges of the NetworkX belief graph.
    Supports Bayesian prior updates based on historical failed/successful nodes and edges.
    """

    @staticmethod
    def calculate_observation_age(last_observed: Optional[datetime], current_time: datetime) -> float:
        """
        Returns the age of observation in minutes.
        """
        if not last_observed:
            return 120.0  # Default to 2 hours if unknown
        if last_observed.tzinfo is not None and current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=last_observed.tzinfo)
        elif last_observed.tzinfo is None and current_time.tzinfo is not None:
            last_observed = last_observed.replace(tzinfo=current_time.tzinfo)
        diff = (current_time - last_observed).total_seconds()
        return max(0.0, diff / 60.0)

    @staticmethod
    def calculate_node_consistency(n_id: str, belief_graph: nx.Graph) -> float:
        """
        Calculates the consistency index of a node relative to its spatial neighbors.
        If neighbor statuses or dangers are similar, consistency is high (approaches 1.0).
        """
        neighbors = list(belief_graph.neighbors(n_id))
        if not neighbors:
            return 1.0  # Isolated node is consistent by default
        
        current_danger = belief_graph.nodes[n_id].get("p_danger", 0.0)
        diff_sum = 0.0
        for neighbor in neighbors:
            neighbor_danger = belief_graph.nodes[neighbor].get("p_danger", 0.0)
            diff_sum += abs(current_danger - neighbor_danger)
        
        avg_diff = diff_sum / len(neighbors)
        return max(0.0, 1.0 - avg_diff)

    @staticmethod
    def get_confidence_metadata(confidence: float, age: float, has_observed: bool) -> Dict[str, str]:
        """
        Returns confidence tier and color according to:
        - Known/Green (confidence >= 0.8)
        - Partially Known/Yellow (0.5 <= confidence < 0.8)
        - Unknown/Red (0.0 < confidence < 0.5)
        - No obs/Grey (confidence == 0 or not observed)
        """
        if not has_observed or confidence <= 0.01:
            return {"confidence_tier": "No obs/Grey", "confidence_color": "grey"}
        elif confidence >= 0.8:
            return {"confidence_tier": "Known/Green", "confidence_color": "green"}
        elif confidence >= 0.5:
            return {"confidence_tier": "Partially Known/Yellow", "confidence_color": "yellow"}
        else:
            return {"confidence_tier": "Unknown/Red", "confidence_color": "red"}

    @classmethod
    def update_bayesian_priors(cls, belief_graph: nx.Graph, observations: List[Dict[str, Any]]) -> nx.Graph:
        """
        Performs Bayesian prior updates using a Beta-Binomial conjugacy model.
        Adjusts node hazard probabilities (p_danger) and edge blocked states based on feedback.
        Each observation is a dict:
          - For nodes: {"type": "node", "id": str, "status": "SAFE" | "BLOCKED" | "COMPROMISED" | "FLOODED"}
          - For edges: {"type": "edge", "u": str, "v": str, "status": "SAFE" | "BLOCKED"}
        """
        for obs in observations:
            obs_type = obs.get("type")
            if obs_type == "node":
                n_id = obs.get("id")
                if n_id not in belief_graph.nodes:
                    continue
                
                # Direct observation update with Bayesian smoothing (prevents tick-by-tick accumulation inflation)
                status = obs.get("status")
                obs_danger = float(obs.get("p_danger", 0.8 if status in ("BLOCKED", "COMPROMISED", "DANGER", "FLOODED") else 0.1))
                
                prev_danger = belief_graph.nodes[n_id].get("p_danger", 0.2)
                # Exponential moving average with high gain for new observations (alpha=0.7)
                updated_p_danger = round(0.3 * prev_danger + 0.7 * obs_danger, 4)
                belief_graph.nodes[n_id]["p_danger"] = updated_p_danger
                
                # High confidence upon direct observation (95% state certainty)
                confidence = 0.95
                belief_graph.nodes[n_id]["p_state_correct"] = confidence
                belief_graph.nodes[n_id]["confidence"] = confidence
                belief_graph.nodes[n_id]["last_observed"] = datetime.utcnow().isoformat()


            elif obs_type == "edge":
                u = obs.get("u")
                v = obs.get("v")
                if not belief_graph.has_edge(u, v):
                    continue
                
                # Fetch edge priors or default: Beta(2.0, 0.2)
                successes = belief_graph.edges[u, v].get("bayesian_success", 2.0)
                failures = belief_graph.edges[u, v].get("bayesian_failure", 0.2)
                
                status = obs.get("status")
                if status in ("BLOCKED", "SUBMERGED", "COLLAPSED"):
                    failures += 1.0
                else:
                    successes += 1.0
                
                belief_graph.edges[u, v]["bayesian_success"] = successes
                belief_graph.edges[u, v]["bayesian_failure"] = failures
                
                p_blocked = failures / (successes + failures)
                belief_graph.edges[u, v]["blocked_probability"] = round(p_blocked, 4)
                belief_graph.edges[u, v]["blocked"] = p_blocked > 0.5
                
                total_evidence = successes + failures
                confidence = min(0.99, 1.0 - (1.0 / (total_evidence + 1.0)))
                belief_graph.edges[u, v]["confidence"] = round(confidence, 4)
                belief_graph.edges[u, v]["last_observed"] = datetime.utcnow().isoformat()

        return belief_graph

    @classmethod
    def enrich_belief_graph(cls, belief_graph: nx.Graph, current_time: Optional[datetime] = None) -> nx.Graph:
        """
        Enriches the graph in-place with uncertainty properties:
          Nodes:
            - probability: node p_danger
            - confidence: p_state_correct
            - observation_age: age in minutes
            - reliability: source confidence decayed by age
            - consistency: similarity to neighbors
            - confidence_tier: "Known/Green", etc.
            - confidence_color: "green", etc.
          Edges:
            - probability: block probability (1.0 if blocked, 0.0 if open, or intermediate based on source)
            - confidence: edge confidence
            - observation_age: age in minutes
            - reliability: decayed edge confidence
            - confidence_tier: "Known/Green", etc.
            - confidence_color: "green", etc.
        """
        if current_time is None:
            current_time = datetime.utcnow()

        # 0. Spatial MRF propagation: propagate danger to neighbors of blocked/collapsed nodes
        mrf_damping = 0.35
        for _ in range(2):
            updates = {}
            for u in belief_graph.nodes:
                u_data = belief_graph.nodes[u]
                u_danger = u_data.get("p_danger", 0.0)
                u_status = u_data.get("status", "SAFE")
                is_danger_source = u_danger > 0.8 or u_status in ("BLOCKED", "COMPROMISED", "DANGER", "FLOODED")
                
                if is_danger_source:
                    for v in list(belief_graph.neighbors(u)):
                        edge_data = belief_graph.edges[u, v]
                        edge_blocked = edge_data.get("blocked", False)
                        factor = mrf_damping * (1.5 if edge_blocked else 1.0)
                        
                        v_danger = belief_graph.nodes[v].get("p_danger", 0.0)
                        propagated_danger = min(0.95, u_danger * factor)
                        if propagated_danger > v_danger:
                            updates[v] = max(updates.get(v, 0.0), propagated_danger)
            
            for v, val in updates.items():
                belief_graph.nodes[v]["p_danger"] = round(val, 4)

        # Enrich nodes
        for n_id, data in belief_graph.nodes(data=True):
            last_obs = data.get("last_observed")
            has_observed = last_obs is not None
            if isinstance(last_obs, str):
                try:
                    last_obs = datetime.fromisoformat(last_obs)
                except ValueError:
                    last_obs = datetime.utcnow()

            age = cls.calculate_observation_age(last_obs, current_time)
            p_danger = data.get("p_danger", 0.0)
            p_state_correct = data.get("p_state_correct", 1.0)
            
            # Reliability decay formula over time
            decay_rate = 0.01  # 1% decay per minute
            reliability = p_state_correct * math.exp(-decay_rate * age)

            consistency = cls.calculate_node_consistency(n_id, belief_graph)

            # Determine visual confidence overlay
            meta = cls.get_confidence_metadata(reliability, age, has_observed)

            # Update node attributes
            data["probability"] = p_danger
            data["confidence"] = p_state_correct
            data["observation_age"] = age
            data["reliability"] = max(0.0, min(1.0, reliability))
            data["consistency"] = consistency
            data["confidence_tier"] = meta["confidence_tier"]
            data["confidence_color"] = meta["confidence_color"]

        # Enrich edges
        for u, v, data in belief_graph.edges(data=True):
            last_obs = data.get("last_observed")
            has_observed = last_obs is not None
            if isinstance(last_obs, str):
                try:
                    last_obs = datetime.fromisoformat(last_obs)
                except ValueError:
                    last_obs = datetime.utcnow()

            age = cls.calculate_observation_age(last_obs, current_time)
            blocked = data.get("blocked", False)
            confidence = data.get("confidence", 1.0)

            # Map blocked boolean to probability
            prob = 1.0 if blocked else 0.0
            
            # Reliability decay for edges
            decay_rate = 0.015  # 1.5% decay per minute for roads (more dynamic)
            reliability = confidence * math.exp(-decay_rate * age)

            meta = cls.get_confidence_metadata(reliability, age, has_observed)

            data["probability"] = prob
            data["confidence"] = confidence
            data["observation_age"] = age
            data["reliability"] = max(0.0, min(1.0, reliability))
            data["confidence_tier"] = meta["confidence_tier"]
            data["confidence_color"] = meta["confidence_color"]

        return belief_graph
