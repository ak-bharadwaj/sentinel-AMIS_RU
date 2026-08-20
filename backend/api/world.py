from fastapi import APIRouter
from backend.world_model.world_state import world_state

import asyncio

router = APIRouter(prefix="/world", tags=["World"])

@router.get("")
def get_world():
    """Returns the entire graph schema with nodes and edges."""
    from backend.world_model.global_memory import gmm
    node_names = {
        n_id: world_state.get_node_human_name(n_id)
        for n_id in world_state.belief.nodes
    }
    
    # Generate tiny delta indices under 50 bytes for offline Radio RDS/SMS broadcasts (Phase 2)
    blocked_list = []
    for u, v in world_state.belief.edges:
        if world_state.belief.edges[u, v].get('blocked', False):
            # Compact u->v representation
            blocked_list.append(f"{u}_{v}")
            
    haven_list = []
    for n, data in world_state.belief.nodes(data=True):
        if data.get('node_type') in ("SHELTER", "HOSPITAL"):
            haven_list.append(n)
            
    offline_deltas = f"B:{','.join(blocked_list)}|H:{','.join(haven_list)}"
    
    return {
        "nodes": world_state.get_nodes(),
        "edges": world_state.get_edges(),
        "coordinates": world_state.get_all_coordinates(),
        "cleared_edges": list(gmm.clearance_ledger),
        "node_names": node_names,
        "offline_deltas": offline_deltas
    }


@router.get("/nodes")
def get_nodes():
    """Returns only the list of nodes."""
    return world_state.get_nodes()

@router.get("/edges")
def get_edges():
    """Returns only the list of edges."""
    return world_state.get_edges()

from pydantic import BaseModel

class DesignateNodeSchema(BaseModel):
    node_id: str
    node_type: str  # "SHELTER" or "HOSPITAL"

@router.post("/node/designate")
def designate_node(config: DesignateNodeSchema):
    """Designates a node as a shelter or hospital."""
    if config.node_id in world_state.belief.nodes:
        world_state.belief.nodes[config.node_id]['node_type'] = config.node_type
        # Set to maximum safety/importance so the coordinator utilizes it correctly
        world_state.belief.nodes[config.node_id]['importance'] = 1.0
        world_state.belief.nodes[config.node_id]['status'] = "SAFE"
        world_state.belief.nodes[config.node_id]['p_danger'] = 0.0
        world_state.belief.nodes[config.node_id]['p_state_correct'] = 1.0
        
        # Also update ground truth so they align
        if config.node_id in world_state.ground_truth.nodes:
            world_state.ground_truth.nodes[config.node_id]['node_type'] = config.node_type
            world_state.ground_truth.nodes[config.node_id]['importance'] = 1.0
            world_state.ground_truth.nodes[config.node_id]['status'] = "SAFE"
            world_state.ground_truth.nodes[config.node_id]['p_danger'] = 0.0
            world_state.ground_truth.nodes[config.node_id]['p_state_correct'] = 1.0

        if hasattr(world_state, '_node_names_cache'):
            world_state._node_names_cache.pop(config.node_id, None)

        world_state.sync_to_db()
        
        return {"status": "Success", "node_id": config.node_id, "node_type": config.node_type}
    return {"status": "Error", "message": "Node not found"}

class ToggleEdgeBlockageSchema(BaseModel):
    source: str
    target: str

@router.post("/edge/toggle_blockage")
def toggle_edge_blockage(config: ToggleEdgeBlockageSchema):
    """Manually blocks or unblocks a road segment from EOC."""
    u = config.source
    v = config.target
    if not world_state.ground_truth.has_edge(u, v):
        return {"status": "Error", "message": "Edge not found"}
    
    current_blocked = world_state.ground_truth.edges[u, v].get("blocked", False)
    new_blocked = not current_blocked
    world_state.ground_truth.edges[u, v]["blocked"] = new_blocked
    world_state.belief.edges[u, v]["blocked"] = new_blocked
    world_state.belief.edges[u, v]["confidence"] = 1.0
    
    from backend.simulation.engine import simulation_engine
    status_text = "BLOCKED ⛔" if new_blocked else "CLEARED ✅"
    simulation_engine.add_event(f"[{simulation_engine.simulation_time}m] 🛠️ EOC Operator manually toggled road {u} ↔ {v} to {status_text}.")
    
    return {"status": "Success", "blocked": new_blocked}
