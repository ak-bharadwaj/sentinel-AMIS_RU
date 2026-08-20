from enum import Enum
from typing import Optional, List, Dict, Any

class AgentStatus(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    OBSERVING = "OBSERVING"
    RESCUING = "RESCUING"
    RETURNING = "RETURNING"

class BaseAgent:
    def __init__(self, agent_id: str, agent_type: str, speed: float, start_node: str, crew: int = 2) -> None:
        self.id: str = agent_id
        self.agent_type: str = agent_type  # "SCOUT" or "RESCUE"
        self.status: AgentStatus = AgentStatus.IDLE
        self.current_node: str = start_node
        self.next_node: Optional[str] = None  # Node we are currently heading towards
        self.target_node: Optional[str] = None  # Ultimate destination node
        self.route: List[str] = []  # Remaining nodes to traverse
        self.full_planned_route: List[str] = []  # Full original planned path (for frontend visualization - not consumed)
        self.history_route: List[str] = [start_node]  # Nodes the agent has successfully traversed (coverage memory)
        self.progress_on_edge: float = 0.0  # Fraction [0.0 - 1.0]
        self.speed: float = speed  # m/s
        self.action_timer: int = 0  # Steps remaining for dynamic action (observing/rescuing)
        self.zone_assignment: Optional[str] = None  # District/zone label for display
        self.is_manual_override: bool = False
        self.pending_observations: List[Dict[str, Any]] = []
        self.comms_blackout: bool = False
        
        # EOC Resource Metrics
        self.fuel: float = 100.0  # percentage
        self.crew: int = crew
        self.operational_status: str = "Available" # Available, Busy, Maintenance
        
        # EGL (Execution Governance Layer) fields
        # P2P provenance: source agent IDs for observations received via
        # peer-to-peer sync in comms blackout zones. Used by DAP's δ
        # (Source Diversity Index) to weight correlated vs. independent evidence.
        self.pending_observations_from: List[str] = []
        # Staged dispatch state: when DAP returns STAGED_EXECUTE (high-I actions),
        # the agent moves to staging_node and pauses for re-evaluation.
        self.staged_dispatch_target: Optional[str] = None
        self.staging_node: Optional[str] = None
        # Vehicle type: used by DAP σ (crew safety) to look up survivability.
        # Set by subclass __init__ (ScoutAgent, RescueAgent).
        self.vehicle_type: str = "STANDARD_CAR"
        
        # Original EGL target locked in FCM, separate from target_node
        self.egl_locked_target: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_type": self.agent_type,
            "status": self.status.value,
            "current_node": self.current_node,
            "next_node": self.next_node,
            "target_node": self.target_node,
            "route": self.route,
            "full_planned_route": self.full_planned_route,
            "history_route": self.history_route,
            "progress_on_edge": self.progress_on_edge,
            "speed": self.speed,
            "action_timer": self.action_timer,
            "zone_assignment": self.zone_assignment,
            "is_manual_override": self.is_manual_override,
            "pending_observations": self.pending_observations,
            "comms_blackout": self.comms_blackout,
            "fuel": self.fuel,
            "crew": self.crew,
            "operational_status": self.operational_status,
            "pending_observations_from": self.pending_observations_from,
            "staged_dispatch_target": self.staged_dispatch_target,
            "staging_node": self.staging_node,
            "vehicle_type": self.vehicle_type,
            "egl_locked_target": self.egl_locked_target
        }
