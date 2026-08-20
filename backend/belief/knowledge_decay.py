import math
import networkx as nx  # type: ignore
from backend.config import settings
from typing import Any

def decay_confidence(belief_graph: nx.Graph, lambda_decay: float = 0.05) -> None:
    """Decays node p_state_correct and updates edge confidences as the average of node confidence."""
    from backend.config_params.parameters import params
    # 1. Decay nodes
    for n_id in belief_graph.nodes:
        p_state = belief_graph.nodes[n_id].get('p_state_correct', 1.0)
        # Exponential decay toward maximum uncertainty (0.5), not absolute zero
        # Formulation: P_new = 0.5 + (P - 0.5) * exp(-lambda)
        max_uncertainty = getattr(params, 'max_uncertainty_probability', 0.5)
        new_p = max_uncertainty + (p_state - max_uncertainty) * math.exp(-lambda_decay)
        belief_graph.nodes[n_id]['p_state_correct'] = max(0.0, min(1.0, new_p))
        
    # 2. Update edge confidences based on endpoint nodes
    for u, v in belief_graph.edges:
        conf_u = belief_graph.nodes[u].get('p_state_correct', 1.0)
        conf_v = belief_graph.nodes[v].get('p_state_correct', 1.0)
        
        belief_graph.edges[u, v]['confidence'] = (conf_u + conf_v) / 2.0
