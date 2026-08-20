import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict

from backend.simulation.engine import simulation_engine

router = APIRouter(
    prefix="/egl",
    tags=["egl"]
)

class SetProfileSchema(BaseModel):
    profile_name: str
    officer_id: str
    custom_weights: Optional[Dict[str, float]] = None

class OverrideSchema(BaseModel):
    decision: str  # "APPROVE_EXECUTE" or "CONFIRM_DEFER"
    officer_id: str

@router.get("/config")
def get_egl_config():
    """Returns the EGL constants configuration."""
    cfg_path = os.path.join(
        os.path.dirname(__file__), "..", "config_params", "egl_config.json"
    )
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read EGL config: {exc}")

@router.get("/status")
def get_egl_status():
    """Returns EGL status and metrics (override rates, profile details)."""
    return simulation_engine.egl.status_dict()

@router.post("/ethical-profile")
def set_ethical_profile(config: SetProfileSchema):
    """Sets/Queues a new ethical weight profile."""
    errors = simulation_engine.egl.epm.set_profile(
        profile_name=config.profile_name,
        officer_id=config.officer_id,
        custom_weights=config.custom_weights
    )
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return {"status": "success", "message": f"Queued ethical profile '{config.profile_name}' for next cycle."}

@router.get("/audit")
def get_egl_audit(limit: int = 50):
    """Returns the recent append-only forensic audit records."""
    return simulation_engine.egl.am.get_recent(limit)

@router.get("/pending-overrides")
def get_pending_overrides():
    """Returns list of pending TBHO requests for dashboard polling."""
    return [req.to_sse_payload() for req in simulation_engine.egl.hom.get_pending_requests()]

@router.post("/override/{request_id}")
def receive_override_response(request_id: str, payload: OverrideSchema):
    """Submits a commander decision response to a pending TBHO request."""
    if payload.decision not in ("APPROVE_EXECUTE", "CONFIRM_DEFER"):
        raise HTTPException(status_code=400, detail="Invalid decision. Must be APPROVE_EXECUTE or CONFIRM_DEFER.")
        
    result = simulation_engine.egl.hom.receive_response(
        request_id=request_id,
        decision=payload.decision,
        officer_id=payload.officer_id
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Override request '{request_id}' not found or already resolved.")
        
    # Apply override outcome immediately to the agent if active
    agent_id = None
    req = simulation_engine.egl.hom.get_request(request_id)
    if req:
        agent_id = req.agent_id
        
    if agent_id and agent_id in simulation_engine.agents:
        agent = simulation_engine.agents[agent_id]
        if result.final_outcome == "EXECUTE":
            # Resume/Clear execution path
            if simulation_engine.egl.fcm.is_agent_staged(agent.id):
                remaining_path = simulation_engine.egl.fcm.complete_staged(agent.id)
                if remaining_path:
                    agent.route = remaining_path
                    agent.target_node = agent.route[-1] if agent.route else agent.current_node
                    from backend.agents.base_agent import AgentStatus
                    agent.status = AgentStatus.MOVING
            else:
                pass
        else:
            # DEFER confirmed
            if simulation_engine.egl.fcm.is_agent_staged(agent.id):
                simulation_engine.egl.fcm.abort_staged(agent.id)
                agent.route = []
                from backend.agents.base_agent import AgentStatus
                agent.status = AgentStatus.IDLE
                agent.target_node = None
                agent.staged_dispatch_target = None
                agent.staging_node = None
                
    return {"status": "success", "resolution": result.resolution, "final_outcome": result.final_outcome}
