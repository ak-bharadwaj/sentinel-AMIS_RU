from typing import Any, Dict, List, Optional, Tuple, Set, Union, cast
import networkx as nx
import math
import time
import json
from datetime import datetime
from backend.world_model.world_state import world_state
from backend.agents.scout import ScoutAgent
from backend.agents.rescue import RescueAgent
from backend.agents.base_agent import AgentStatus
from backend.agents.coordinator import Coordinator
from backend.execution_governance import ExecutionGovernanceLayer
from backend.world_model.global_memory import gmm
from backend.belief.bayesian_update import apply_scout_observation
from backend.belief.knowledge_decay import decay_confidence
from backend.simulation.corruption import corrupt_belief_graph
from backend.config import settings
from backend.routing.confidence_dijkstra import calculate_edge_cost
from backend.agents.fleet_config import get_effective_speed
from backend.routing.cost_config import BPR_ALPHA, BPR_BETA, ROAD_CAPACITIES

def is_in_blackout_zone(lat: Optional[float], lon: Optional[float], zones: List[Dict[str, float]]) -> bool:
    if lat is None or lon is None:
        return False
    for zone in zones:
        d_lat = (lat - zone['lat']) * 111000
        d_lon = (lon - zone['lon']) * 111000 * math.cos(math.radians(zone['lat']))
        dist = math.hypot(d_lat, d_lon)
        if dist <= zone['radius_m']:
            return True
    return False

class SimulationEngine:
    def __init__(self) -> None:
        self.simulation_time: int = 0
        self.max_time: int = 1440  # Maximum simulation steps (24 hours)
        self.agents: Dict[str, Any] = {}  # id -> Agent object
        self.coordinator: Optional[Coordinator] = None
        self.egl: ExecutionGovernanceLayer = ExecutionGovernanceLayer()
        self.forecasts_15_30_60: Dict[str, Any] = {}
        self.active_baseline: str = "AMIS-RU"  # "AMIS-RU", "SGA-RA", "PSA-RA"
        self.disaster_type: str = "FLOOD"
        self.tide_phase: str = "LOW TIDE"
        self.new_events: List[str] = []
        self.blackout_zones: List[Dict[str, float]] = []
        self.replanning_required: bool = False
        self.replanning_reason: Optional[str] = None
        self.last_telemetry: Dict[str, Any] = {
            "physics_ms": 0.0,
            "belief_ms": 0.0,
            "tensor_ms": 0.0,
            "decision_ms": 0.0,
            "allocation_ms": 0.0,
            "routing_ms": 0.0,
            "scout_missions": 0,
            "rescue_missions": 0,
            "completed_rescues": 0,
            "routes_replanned": 0,
            "avg_confidence": 0.0,
            "avg_danger": 0.0,
            "roads_closed": 0
        }
        
        # Metrics tracking
        self.total_survivors_saved: int = 0
        
        # Validation metrics — civilian evacuation breakdown
        self.civilian_evacuated_reactive:    int = 0  # saved via broadcast trigger
        self.civilian_evacuated_preemptive:  int = 0  # saved via prediction engine
        self.haven_overflow_events:          int = 0  # times civilian bounced from full haven
        self.route_failure_during_evac:      int = 0  # mid-evac route failures
        self.zones_unreachable_at_trigger:   int = 0  # zones p_danger>0.75 when broadcast fires
        self.broadcast_trigger_step:         int = -1 # step when broadcast first activated
        self.rescued_immediate: int = 0
        self.rescued_delayed: int = 0
        self.rescued_minor: int = 0
        self.triage_ev_accumulated: float = 0.0
        self.rescue_trips_completed: int = 0
        self.total_egl_evaluations: int = 0
        self.route_failures: int = 0
        self.route_failures_by_vehicle: Dict[str, int] = {}
        self.initial_total_population: int = 0
        self.enable_ui_telemetry: bool = False
        self.weather: Any = None
        self.world_version: int = 0
        self.history: List[Dict[str, Any]] = []  # time-series logs
        
        # Strategic and Civilian Evacuation settings (Phase 2)
        self.broadcast_mode: str = "SHELTER_IN_PLACE"
        self.paused_for_decision: bool = False
        self.active_decision: Optional[Dict[str, Any]] = None
        self.last_blocked_count: int = 0
        self.triggered_havens: set = set()
        self.safe_route_mode: bool = False
        self.scout_clear_mode: bool = False
        self.civilian_stuck_timers: Dict[str, int] = {}
        
        # Evacuation metrics tracking
        self.civilian_evacuated_reactive: int = 0
        self.civilian_evacuated_preemptive: int = 0
        self.haven_overflow_events: int = 0
        self.route_failure_during_evac: int = 0
        self.zones_unreachable_at_trigger: int = 0
        
        # Phase 4: Resource Pool
        from backend.simulation.resources import ResourcePool
        self.resource_pool = ResourcePool()

    def add_event(self, event: str) -> None:
        self.new_events.append(event)
        
    def add_xai_event(self, action: str, reason: Optional[str] = None, requires_approval: bool = False, confidence: float = 1.0, recommendation: Optional[str] = None) -> None:
        now_str = datetime.now().strftime("%H:%M:%S")
        evt = {
            "type": "xai",
            "time": now_str,
            "action": action,
            "reason": reason,
            "requires_approval": requires_approval,
            "confidence": confidence,
            "recommendation": recommendation
        }
        self.new_events.append(json.dumps(evt))

    def pop_new_events(self) -> List[str]:
        events = list(self.new_events)
        self.new_events = []
        return events

    def trigger_global_rtb(self):
        """Forces all agents to abort current missions and path to nearest safe zone."""
        safe_nodes = [
            n for n, data in world_state.belief.nodes(data=True) 
            if data.get('node_type') in ("SHELTER", "HOSPITAL")
        ]
        if not safe_nodes:
            self.add_event("[COMMAND] GLOBAL RTB ABORTED: No safe havens available!")
            return False
            
        count = 0
        for agent in self.agents.values():
            if agent.status == AgentStatus.IDLE:
                continue
                
            # Find closest safe node
            try:
                shortest_path = None
                shortest_len = float('inf')
                for safe_node in safe_nodes:
                    if nx.has_path(world_state.belief, agent.current_node, safe_node):
                        length = nx.shortest_path_length(world_state.belief, agent.current_node, safe_node, weight=f'cost_{agent.vehicle_type}')
                        if length < shortest_len:
                            shortest_len = length
                            shortest_path = nx.shortest_path(world_state.belief, agent.current_node, safe_node, weight=f'cost_{agent.vehicle_type}')
                
                if shortest_path:
                    agent.route = shortest_path[1:] # strip current node
                    agent.progress_on_edge = 0.0
                    agent.next_node = None
                    agent.full_planned_route = list(shortest_path)
                    
                    if agent.route:
                        agent.target_node = agent.route[-1]
                    else:
                        agent.target_node = agent.current_node

                    agent.status = AgentStatus.RETURNING
                    count += 1
            except nx.NetworkXNoPath:
                pass
                
        self.add_event(f"[COMMAND] 🚨 GLOBAL RTB TRIGGERED! {count} agents retreating to safe zones.")
        return True

    def setup_simulation(self, baseline_type: str = "AMIS-RU", corruption_level: float = 0.6, osm_path=None, center_lat=37.7749, center_lon=-122.4194, num_scouts: int = 3, num_rescues: int = 3, disaster_type: str = "FLOOD", num_zodiacs: int = 0, num_helicopters: int = 0, num_trucks: int = 0, num_cars: int = 0, lat_span: Optional[float] = None, lon_span: Optional[float] = None, env_mode: str = "LIVE", historical_preset: Optional[str] = None, seed: Optional[int] = None):
        """Resets the simulation, builds graphs, and creates scouts and rescue teams."""
        if seed is not None:
            import random
            import numpy as np
            random.seed(seed)
            np.random.seed(seed)

        self.simulation_time = 0
        self.total_survivors_saved = 0
        self.rescued_immediate = 0
        self.rescued_delayed = 0
        self.rescued_minor = 0
        self.route_failures = 0
        self.history = []
        if baseline_type in ("BASELINE-A", "SGA-RA"):
            self.active_baseline = "SGA-RA"
        elif baseline_type in ("BASELINE-B", "PSA-RA"):
            self.active_baseline = "PSA-RA"
        else:
            self.active_baseline = "AMIS-RU"
        self.disaster_type = disaster_type
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.env_mode = env_mode
        self.historical_preset = historical_preset
        
        # Reset Phase 2 Strategic variables
        self.broadcast_mode = "SHELTER_IN_PLACE"
        self.paused_for_decision = False
        self.active_decision = None
        self.last_blocked_count = 0
        self.triggered_havens = set()
        self.safe_route_mode = False
        self.scout_clear_mode = False
        self.civilian_stuck_timers = {}
        
        self.resource_pool.reset()
        gmm.reset_matrix()
        
        # Clear Prediction Engine cache for new simulation run
        from backend.decision_engine.prediction_engine import PredictionEngine
        PredictionEngine._forecast_cache.clear()
        
        # Initialize dynamic sensor measurement variables
        self.sensor_rainfall_rate = 0.0
        self.sensor_water_level_m = 0.0
        self.sensor_wind_speed_kmh = 0.0
        self.sensor_surge_depth_m = 0.0
        self.sensor_seismic_pga_g = 0.0
        
        # Default tide phase
        self.tide_phase = "LOW TIDE"
        self.wind_speed = 120.0
        self.magnitude_mw = 6.5
        
        if self.env_mode == "HISTORICAL" and self.historical_preset:
            from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
            preset = HISTORICAL_PRESETS.get(self.disaster_type.upper(), {}).get(self.historical_preset)
            if preset:
                t0 = preset.get("timeline", {}).get(0, {})
                self.tide_phase = t0.get("tide_phase", preset.get("tide_phase", "LOW TIDE"))
                self.wind_speed = t0.get("wind_speed_kmh", preset.get("windspeed", 120.0))
                self.magnitude_mw = t0.get("magnitude_mw", t0.get("magnitude", preset.get("magnitude", 6.5)))
                self.weather = self.get_interpolated_preset_state()
        
        # 2 radio blackout zones
        self.blackout_zones = [
            {"lat": center_lat + 0.006, "lon": center_lon - 0.006, "radius_m": 600},
            {"lat": center_lat - 0.007, "lon": center_lon + 0.007, "radius_m": 600}
        ]
        
        # 1. Reset world state and save initial belief in one fast transaction
        gmm.reset_matrix()
        world_state.initialize(osm_path, center_lat=center_lat, center_lon=center_lon, corruption_level=corruption_level, lat_span=lat_span, lon_span=lon_span, force_rebuild=True)
        
        # Initialize visited flags, default resource values, and occupants for all nodes
        for n_id in world_state.belief.nodes:
            world_state.belief.nodes[n_id]['visited_at_least_once'] = False
            world_state.belief.nodes[n_id]['occupants'] = 0
            world_state.ground_truth.nodes[n_id]['occupants'] = 0
            
            node_type = world_state.belief.nodes[n_id].get('node_type')
            if node_type in ("SHELTER", "HOSPITAL"):
                resources = {
                    "food": 100.0,
                    "water": 100.0,
                    "medicine": 100.0,
                    "fuel": 100.0
                }
                world_state.belief.nodes[n_id]['resources'] = resources.copy()
                world_state.ground_truth.nodes[n_id]['resources'] = resources.copy()
        
        # Apply historical preset population scaling
        if self.env_mode == "HISTORICAL" and self.historical_preset:
            from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
            preset = HISTORICAL_PRESETS.get(self.disaster_type.upper(), {}).get(self.historical_preset)
            if preset:
                pop_mult = preset.get("pop_multiplier", 1.0)
                if pop_mult != 1.0:
                    for n_id in world_state.ground_truth.nodes:
                        if world_state.ground_truth.nodes[n_id].get("node_type") == "POPULATION_ZONE":
                            val = world_state.ground_truth.nodes[n_id].get("population", 0)
                            world_state.ground_truth.nodes[n_id]["population"] = int(val * pop_mult)
                        if n_id in world_state.belief:
                            if world_state.belief.nodes[n_id].get("node_type") == "POPULATION_ZONE":
                                val = world_state.belief.nodes[n_id].get("population", 0)
                                world_state.belief.nodes[n_id]["population"] = int(val * pop_mult)

        # Calculate initial population
        self.initial_total_population = sum(
            data.get('population', 0) 
            for n, data in world_state.ground_truth.nodes(data=True)
        )

        # Generate hazard priors for belief and ground truth
        if self.disaster_type.upper() == "EARTHQUAKE":
            from backend.disaster.earthquake import EarthquakeModule
            mod = EarthquakeModule(magnitude_mw=getattr(self, "magnitude_mw", 6.5))
        elif self.disaster_type.upper() == "CYCLONE":
            from backend.disaster.cyclone import CycloneModule
            mod = CycloneModule()
        elif self.disaster_type.upper() == "WILDFIRE":
            from backend.disaster.wildfire import WildfireModule
            mod = WildfireModule()
        else:
            from backend.disaster.flood import FloodModule
            mod = FloodModule()
        self._disaster_module = mod
        mod.generate_prior(world_state.ground_truth)
        mod.generate_prior(world_state.belief)
        
        # Find a central node as base (prefer a HOSPITAL or SHELTER in the largest connected component)
        components = sorted(nx.connected_components(world_state.ground_truth), key=len, reverse=True)
        largest_comp = list(components[0]) if components else list(world_state.ground_truth.nodes)
        
        base_candidates = [
            n for n in largest_comp
            if world_state.ground_truth.nodes[n].get('node_type') in ("HOSPITAL", "SHELTER")
        ]
        if base_candidates:
            center_node = base_candidates[0]
        else:
            degrees = dict(world_state.ground_truth.degree(largest_comp))
            center_node = max(degrees, key=degrees.get) if degrees else largest_comp[0]
            
        self.egl.reset()
        if self.active_baseline == "AMIS-RU":
            self.coordinator = Coordinator(base_node=center_node, egl=self.egl)
        else:
            self.coordinator = Coordinator(base_node=center_node, egl=None)
        
        # ── Geographically distribute agent start positions across the full graph ──
        self.agents = {}
        # Auto-spawn multi-modal fleet of scouts and rescue units
        for i in range(num_scouts):
            s_id = f"Scout_{i+1}"
            self.agents[s_id] = ScoutAgent(s_id, start_node=center_node)

        if disaster_type.upper() in ("EARTHQUAKE", "WILDFIRE"):
            vehicle_types = ["HIGH_WATER_TRUCK", "STANDARD_CAR", "HELICOPTER", "HIGH_WATER_TRUCK"]
            capacities    = [50,                 20,             40,           50]
        else:
            vehicle_types = ["HIGH_WATER_TRUCK", "ZODIAC_BOAT", "HELICOPTER", "HIGH_WATER_TRUCK"]
            capacities    = [50,                 30,            40,           50]

        for i in range(num_rescues):
            r_id = f"Rescue_{i+1}"
            v_type = vehicle_types[i % len(vehicle_types)]
            capacity = capacities[i % len(capacities)]
            speed = settings.RESCUE_SPEED
            if v_type == "HELICOPTER":
                speed = getattr(settings, 'helicopter_speed_ms', 62.0)
            
            agent = RescueAgent(r_id, start_node=center_node, capacity=capacity, vehicle_type=v_type)
            agent.speed = speed
            self.agents[r_id] = agent

        # Distribute agents across the graph for better initial coverage
        all_nodes = list(world_state.ground_truth.nodes)
        agent_list = list(self.agents.values())
        n = len(agent_list)
        if n > 1 and len(all_nodes) >= n:
            step = len(all_nodes) // n
            for i, agt in enumerate(agent_list):
                spawn_node = all_nodes[min(i * step, len(all_nodes) - 1)]
                agt.current_node = spawn_node
                agt.start_node = spawn_node
                agt.full_planned_route = [spawn_node]

        # Precompute edge costs for initial routing
        from backend.routing.confidence_dijkstra import calculate_edge_cost
        for u, v, d in world_state.belief.edges(data=True):
            d['cost_STANDARD_CAR'] = calculate_edge_cost(world_state.belief, u, v, d, 'STANDARD_CAR', disaster_type=self.disaster_type)
            d['cost_ZODIAC_BOAT'] = calculate_edge_cost(world_state.belief, u, v, d, 'ZODIAC_BOAT', disaster_type=self.disaster_type)
            d['cost_HIGH_WATER_TRUCK'] = calculate_edge_cost(world_state.belief, u, v, d, 'HIGH_WATER_TRUCK', disaster_type=self.disaster_type)
            d['cost_HELICOPTER'] = calculate_edge_cost(world_state.belief, u, v, d, 'HELICOPTER', disaster_type=self.disaster_type)
            d['cost_SCOUT_CAR'] = calculate_edge_cost(world_state.belief, u, v, d, 'SCOUT_CAR', disaster_type=self.disaster_type)
            
        # Compile vector graph to matrix and sync tensors
        self.recompile_and_sync_tensors()

        # Run initial coordinator assignment for scouts and rescues so paths are visible at step 0
        idle_scouts = [a for a in self.agents.values() if a.agent_type == "SCOUT" and a.status == AgentStatus.IDLE and not getattr(a, 'is_manual_override', False)]
        idle_rescues = [a for a in self.agents.values() if a.agent_type == "RESCUE" and a.status == AgentStatus.IDLE and getattr(a, 'survivors_onboard', 0) == 0 and not getattr(a, 'is_manual_override', False)]

        total_fleet = len(self.agents)
        active_agents = sum(1 for a in self.agents.values() if a.status != AgentStatus.IDLE)
        total_scouts = sum(1 for a in self.agents.values() if a.agent_type == "SCOUT")
        active_scouts = sum(1 for a in self.agents.values() if a.agent_type == "SCOUT" and a.status != AgentStatus.IDLE)
        total_rescues = sum(1 for a in self.agents.values() if a.agent_type == "RESCUE")
        active_rescues = sum(1 for a in self.agents.values() if a.agent_type == "RESCUE" and a.status != AgentStatus.IDLE)
        fleet_state = {
            "active_agents": active_agents,
            "total_fleet": total_fleet,
            "total_scouts": total_scouts,
            "active_scouts": active_scouts,
            "total_rescues": total_rescues,
            "active_rescues": active_rescues,
            "active_rescues_outbound": sum(
                1 for a in self.agents.values()
                if a.agent_type == "RESCUE"
                and a.status == AgentStatus.MOVING
                and getattr(a, 'survivors_onboard', 0) == 0
            )
        }

        if self.active_baseline == "AMIS-RU" and idle_scouts:
            if self.weather and (self.weather.get('rain_intensity', 0) > 80 or self.weather.get('storm_category', 0) >= 3):
                self.add_event("[System] AI RATIONALE: Severe weather detected. Inflating priority for High Danger zones (p_danger > 75%).")
            node_count = len(world_state.belief.nodes)
            if node_count > 5000:
                self.add_event("[System] AI RATIONALE: Massive area size detected. Expanding Scout sweep radius to 4500m phase-1.")
            elif node_count < 1000:
                self.add_event("[System] AI RATIONALE: Minimal area size detected. Restricting Scout sweep radius to 1500m phase-1.")
                
            scout_assignments = self.coordinator.assign_scouts(
                belief_graph=world_state.belief, 
                idle_scouts=idle_scouts, 
                weather_state=self.weather,
                blackout_zones=self.blackout_zones,
                forecasts=self.forecasts_15_30_60,
                disaster_type=self.disaster_type,
                sim_time=float(self.simulation_time),
                fleet_state=fleet_state
            )
            for assign in scout_assignments:
                agent = self.agents[assign['scout_id']]
                agent.target_node = assign['target_node_id']
                agent.route = assign['path']
                agent.egl_locked_target = agent.staged_dispatch_target or assign['target_node_id']
                agent.full_planned_route = [agent.current_node] + list(assign.get('full_route', assign['path']))
                agent.status = AgentStatus.MOVING
                agent.progress_on_edge = 0.0
                agent.next_node = None

        if idle_rescues:
            rescue_assignments = self.coordinator.assign_rescues(
                belief_graph=world_state.belief, 
                idle_rescues=idle_rescues, 
                weather_state=self.weather,
                blackout_zones=self.blackout_zones,
                forecasts=self.forecasts_15_30_60,
                disaster_type=self.disaster_type,
                sim_time=float(self.simulation_time),
                fleet_state=fleet_state,
                baseline_type=self.active_baseline
            )
            for assign in rescue_assignments:
                agent = self.agents[assign['team_id']]
                agent.target_node = assign['target_node_id']
                agent.route = assign['path']
                agent.egl_locked_target = agent.staged_dispatch_target or assign['target_node_id']
                agent.full_planned_route = [agent.current_node] + list(assign.get('full_route', assign['path']))
                agent.status = AgentStatus.MOVING
                agent.progress_on_edge = 0.0
                agent.next_node = None

        # Log initial historical event
        if self.env_mode == "HISTORICAL" and self.historical_preset:
            from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
            preset = HISTORICAL_PRESETS.get(self.disaster_type.upper(), {}).get(self.historical_preset)
            if preset and "timeline" in preset and 0 in preset["timeline"]:
                self.add_event(f"[0m] 📢 HISTORICAL PRESENTS: {preset['timeline'][0]['event']}")

    def generate_phase_plan(self):
        """Calculates optimal routes for all idle agents and generates a human-readable rationale."""
        from backend.routing.confidence_dijkstra import calculate_edge_cost
        from backend.world_model.global_memory import gmm
        
        # Precompute edge costs
        for u, v, d in world_state.belief.edges(data=True):
            d['cost_STANDARD_CAR'] = calculate_edge_cost(world_state.belief, u, v, d, 'STANDARD_CAR', disaster_type=self.disaster_type)
            d['cost_ZODIAC_BOAT'] = calculate_edge_cost(world_state.belief, u, v, d, 'ZODIAC_BOAT', disaster_type=self.disaster_type)
            d['cost_HIGH_WATER_TRUCK'] = calculate_edge_cost(world_state.belief, u, v, d, 'HIGH_WATER_TRUCK', disaster_type=self.disaster_type)
            d['cost_HELICOPTER'] = calculate_edge_cost(world_state.belief, u, v, d, 'HELICOPTER', disaster_type=self.disaster_type)
            d['cost_SCOUT_CAR'] = calculate_edge_cost(world_state.belief, u, v, d, 'SCOUT_CAR', disaster_type=self.disaster_type)
            
        self.recompile_and_sync_tensors()

        idle_scouts = [a for a in self.agents.values() if a.agent_type == "SCOUT" and (a.status == AgentStatus.IDLE or not a.route)]
        idle_rescues = [a for a in self.agents.values() if a.agent_type == "RESCUE" and a.status == AgentStatus.IDLE and not getattr(a, 'is_manual_override', False) and getattr(a, 'survivors_onboard', 0) == 0]

        scout_targets = []
        rescue_targets = []

        total_fleet = len(self.agents)
        active_agents = sum(1 for a in self.agents.values() if a.status != AgentStatus.IDLE)
        fleet_state = {"active_agents": active_agents, "total_fleet": total_fleet}

        if idle_scouts:
            scout_assignments = self.coordinator.assign_scouts(
                belief_graph=world_state.belief, 
                idle_scouts=idle_scouts, 
                weather_state=self.weather,
                blackout_zones=self.blackout_zones,
                forecasts=self.forecasts_15_30_60,
                disaster_type=self.disaster_type,
                sim_time=float(self.simulation_time),
                fleet_state=fleet_state
            )
            for assign in scout_assignments:
                agent = self.agents[assign['scout_id']]
                if assign.get('path'):
                    agent.route = list(assign['path'])
                    agent.target_node = assign['target_node_id']
                    # Preserve original full planned route for staged re-evaluation lookup
                    if not getattr(agent, 'full_planned_route', None) or not agent.staged_dispatch_target:
                        agent.full_planned_route = [agent.current_node] + list(assign.get('full_route', assign['path']))
                    scout_targets.append(agent.target_node)

        if idle_rescues:
            rescue_assignments = self.coordinator.assign_rescues(
                belief_graph=world_state.belief, 
                idle_rescues=idle_rescues, 
                weather_state=self.weather,
                blackout_zones=self.blackout_zones,
                forecasts=self.forecasts_15_30_60,
                disaster_type=self.disaster_type,
                sim_time=float(self.simulation_time),
                fleet_state=fleet_state,
                baseline_type=self.active_baseline
            )
            for assign in rescue_assignments:
                agent = self.agents[assign['team_id']]
                if assign.get('path'):
                    agent.route = list(assign['path'])
                    agent.target_node = assign['target_node_id']
                    # Preserve original full planned route for staged re-evaluation lookup
                    if not getattr(agent, 'full_planned_route', None) or not agent.staged_dispatch_target:
                        agent.full_planned_route = [agent.current_node] + list(assign.get('full_route', assign['path']))
                    rescue_targets.append(agent.target_node)

        # Calculate stage predictions
        self.current_stage = getattr(self, 'current_stage', 0) + 1
        
        total_stranded = sum(
            d.get('population', 0) 
            for n, d in world_state.belief.nodes(data=True) 
            if d.get('node_type') == 'POPULATION_ZONE'
        )
        fleet_capacity = sum(a.capacity for a in self.agents.values() if getattr(a, 'capacity', 0) > 0)
        
        # A rough heuristic: if we need to pick up `total_stranded` people and can only hold `fleet_capacity` at a time,
        # it takes roughly total_stranded / fleet_capacity trips. Add 2 for scouting stages.
        self.estimated_total_stages = 2 + math.ceil(total_stranded / max(1, fleet_capacity))
        if self.current_stage > self.estimated_total_stages:
            self.estimated_total_stages = self.current_stage

        # Generate Rationale
        avg_danger = 0
        nodes_checked = 0
        for n, d in world_state.belief.nodes(data=True):
            if d.get("node_type") == "POPULATION_ZONE":
                avg_danger += d.get("p_danger", 0)
                nodes_checked += 1
        
        avg_danger = avg_danger / max(1, nodes_checked)
        risk_str = "High" if avg_danger > 0.6 else "Medium" if avg_danger > 0.3 else "Low"
        
        assigned_names = []
        if idle_scouts:
            assigned_names.append(f"{len(idle_scouts)} Scout(s)")
        if idle_rescues:
            assigned_names.append(f"{len(idle_rescues)} Rescue Team(s)")
            
        # NDMA EOC Operational Plan Format
        objectives = []
        obj_id = 1
        
        if scout_targets:
            objectives.append({
                "id": f"Objective {obj_id}",
                "description": f"Reconnaissance of {len(scout_targets)} high-risk nodes",
                "priority": "High",
                "assigned_units": [f"{a.id} (Drone)" for a in idle_scouts],
                "eta": f"{max(8, int(avg_danger * 20))} min"
            })
            obj_id += 1
            
        if rescue_targets:
            objectives.append({
                "id": f"Objective {obj_id}",
                "description": f"Evacuate {len(rescue_targets)} populated zones",
                "priority": "Critical",
                "assigned_units": [f"{a.id} (National Rescue)" for a in idle_rescues],
                "eta": f"{max(15, int(avg_danger * 40))} min"
            })
            
        self.latest_briefing = {
            "operation_name": f"Operation River Shield - Phase {self.current_stage}",
            "objectives": objectives,
            "risk": risk_str,
            "weather": self.weather.value if hasattr(self.weather, 'value') else (str(self.weather) if self.weather else "CLEAR"),
        }
        
    def recompile_and_sync_tensors(self):
        """Precomputes sparse graph matrices and syncs pre-allocated Edge and Node tensors."""
        from backend.world_model.global_memory import gmm
        from backend.world_model.world_state import world_state
        
        # Compile CSR adjacency graph in global memory
        gmm.compile_graph_to_tensor(world_state.belief)
        
        # Sync EdgeStateTensor
        if not hasattr(world_state, 'edge_state_tensor'):
            from backend.world_model.edge_state_tensor import EdgeStateTensor
            world_state.edge_state_tensor = EdgeStateTensor(len(world_state.belief.edges))
        world_state.edge_state_tensor.sync_from_graph(world_state.belief, self.simulation_time)
        
        # Sync NodeStateTensor
        if not hasattr(world_state, 'node_state_tensor'):
            from backend.world_model.node_state_tensor import NodeStateTensor
            world_state.node_state_tensor = NodeStateTensor(len(world_state.belief.nodes))
        world_state.node_state_tensor.sync_from_graph(world_state.belief)

    def execute_phase(self):
        """Advances the engine rapidly until agents hit targets or 30 ticks pass."""
        if self.paused_for_decision:
            print("SIMULATION PAUSED: Awaiting strategic decision resolution.")
            return
        ticks = 0
        # Set all agents with a route to MOVING
        for agent in self.agents.values():
            if agent.route:
                agent.status = AgentStatus.MOVING
                
        while ticks < 30:
            if self.paused_for_decision:
                break
            self.step()
            ticks += 1
            # Check if anyone is still moving with a route
            moving = [a for a in self.agents.values() if a.status == AgentStatus.MOVING and a.route]
            if not moving:
                break
        
        # After execution, clear the rationale
        self.latest_rationale = None


    def get_interpolated_preset_state(self) -> dict:
        """Calculates interpolated values of all environmental parameters at current time step."""
        if self.env_mode != "HISTORICAL" or not self.historical_preset:
            return {}
        from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
        preset = HISTORICAL_PRESETS.get(self.disaster_type.upper(), {}).get(self.historical_preset)
        if not preset or "timeline" not in preset:
            return {}
        
        timeline = preset["timeline"]
        keys = sorted(timeline.keys())
        if not keys:
            return {}
            
        current_time = self.simulation_time
        
        if current_time >= keys[-1]:
            return timeline[keys[-1]].copy()
        if current_time <= keys[0]:
            return timeline[keys[0]].copy()
            
        lower_key = max([k for k in keys if k <= current_time])
        upper_key = min([k for k in keys if k > current_time])
        
        lower_data = timeline[lower_key]
        upper_data = timeline[upper_key]
        
        span = upper_key - lower_key
        factor = (current_time - lower_key) / span if span > 0 else 0.0
        
        interpolated = {}
        for k in lower_data.keys():
            v_lower = lower_data[k]
            v_upper = upper_data.get(k, v_lower)
            
            if isinstance(v_lower, (int, float)) and isinstance(v_upper, (int, float)) and k not in ("wind_direction_deg", "weathercode"):
                interpolated[k] = v_lower + factor * (v_upper - v_lower)
            else:
                interpolated[k] = v_lower
                
        if "wind_direction_deg" in lower_data:
            lower_dir = lower_data["wind_direction_deg"]
            upper_dir = upper_data.get("wind_direction_deg", lower_dir)
            interpolated["wind_direction_deg"] = lower_dir + factor * (upper_dir - lower_dir)
            
        # Add alias fields for UI component requests
        interpolated["temperature"] = interpolated.get("temperature_c")
        interpolated["humidity"] = interpolated.get("humidity_pct")
        interpolated["pressure"] = interpolated.get("pressure_hpa")
        interpolated["windspeed"] = interpolated.get("wind_speed_kmh")
        interpolated["winddirection"] = interpolated.get("wind_direction_deg")
        interpolated["cloudcover"] = interpolated.get("cloud_cover_pct")
        interpolated["visibility"] = interpolated.get("visibility_m")
        interpolated["rainfall"] = interpolated.get("rainfall_mm_hr")
        interpolated["preset_name"] = preset.get("name")
        interpolated["simulated"] = True
        
        return interpolated

    def step(self):
        """Advances the simulation by one discrete time step (1 minute)."""
        if self.paused_for_decision:
            print("SIMULATION PAUSED: Awaiting strategic decision resolution.")
            return
        self.simulation_time += 1
        self.world_version += 1
        # print(f"DEBUG ENGINE STEP: {self.simulation_time} (World Version: {self.world_version})", flush=True)

        # Apply historical timeline event updates
        if self.env_mode == "HISTORICAL" and self.historical_preset:
            interpolated = self.get_interpolated_preset_state()
            if interpolated:
                self.weather = interpolated
                if "wind_speed_kmh" in interpolated:
                    self.wind_speed = interpolated["wind_speed_kmh"]
                if "tide_phase" in interpolated:
                    self.tide_phase = interpolated["tide_phase"]
                if "magnitude_mw" in interpolated:
                    self.magnitude_mw = interpolated["magnitude_mw"]
                elif "magnitude" in interpolated:
                    self.magnitude_mw = interpolated["magnitude"]
            
            # Check for discrete event announcements
            from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
            preset = HISTORICAL_PRESETS.get(self.disaster_type.upper(), {}).get(self.historical_preset)
            if preset and "timeline" in preset:
                timeline = preset["timeline"]
                if self.simulation_time in timeline and "event" in timeline[self.simulation_time]:
                    self.add_event(f"[{self.simulation_time}m] 📢 HISTORICAL PRESENTS: {timeline[self.simulation_time]['event']}")

        delta_t = settings.TIMESTEP_DURATION
        gamma = settings.SURVIVAL_DECAY_RATE
        
        # Cycle tide phase every 8 steps (e.g. 0-7 Low, 8-15 High) if not historical preset
        if self.env_mode != "HISTORICAL":
            is_high_tide = (self.simulation_time // 8) % 2 == 1
            new_tide = "HIGH TIDE" if is_high_tide else "LOW TIDE"
            if new_tide != getattr(self, 'tide_phase', "LOW TIDE"):
                self.tide_phase = new_tide
                gate_status = "CLOSED (Drainage Halted)" if is_high_tide else "OPEN (Drainage Active)"
                self.add_event(f"[{self.simulation_time}m] 🌊 TIDE UPDATE: Phase changed to {self.tide_phase}. Municipal outfall gates are now {gate_status}.")
                
                # Phase 10: Dynamic Replanning Trigger
                self.replanning_required = True
                self.replanning_reason = f"Tide shift to {new_tide}"
                self.add_xai_event(
                    action="Halting Operations - Environmental Shift",
                    reason=f"Tidal shift to {new_tide} alters traversal risks and water depths.",
                    requires_approval=True,
                    recommendation="Trigger Phase Re-planning to adapt to new flood models."
                )
        
        is_high_tide = getattr(self, 'tide_phase', "LOW TIDE") == "HIGH TIDE"
            
        t_physics_start = time.perf_counter()

        # Run Sentinel v2.0 Decision Cycle: Observe -> Assess -> Forecast -> Uncertainty -> Options -> Explain
        # Heavy forecasting, portfolio optimization, and sensitivity analysis run every 15 mins (or on step 1) for Sentinel
        is_decision_step = (int(self.simulation_time) % 15 == 1) or (self.simulation_time == 1)
        if is_decision_step and self.active_baseline in ("AMIS-RU", "SENTINEL"):
            try:
                if self.egl:
                    self.egl.on_new_planning_cycle(float(self.simulation_time))
                belief_snapshot = world_state.get_belief_snapshot()


                # 1. Uncertainty Engine (Enrich graph confidence values)
                from backend.decision_engine.uncertainty_engine import UncertaintyEngine
                UncertaintyEngine.enrich_belief_graph(world_state.belief)

                # 2. Situation Assessment Engine
                from backend.decision_engine.situation_assessment import SituationAssessmentEngine
                self.situation_assessment = SituationAssessmentEngine.assess_from_graph(belief_snapshot)

                # 3. Dynamic Forecasting Engine (T+15, 30, 60 minutes)
                from backend.decision_engine.prediction_engine import PredictionEngine
                # Obtain matching disaster module instance if existing
                disaster_instance = None
                dtype_upper = self.disaster_type.upper()
                if dtype_upper == "FLOOD":
                    from backend.disaster.flood import FloodModule
                    disaster_instance = FloodModule(rainfall=1.2 if is_high_tide else 0.55)
                elif dtype_upper == "EARTHQUAKE":
                    from backend.disaster.earthquake import EarthquakeModule
                    disaster_instance = EarthquakeModule(magnitude_mw=getattr(self, "magnitude_mw", 6.5))
                elif dtype_upper == "CYCLONE":
                    from backend.disaster.cyclone import CycloneModule
                    disaster_instance = CycloneModule()
                elif dtype_upper == "WILDFIRE":
                    from backend.disaster.wildfire import WildfireModule
                    disaster_instance = WildfireModule()
                
                self.forecasts_15_30_60 = PredictionEngine.get_forecasts(
                    belief_snapshot,
                    self.disaster_type,
                    disaster_instance,
                    time_since_start_minutes=float(self.simulation_time)
                )

                # PRE-EMPTIVE EVACUATION — Sentinel only
                # Uses T+30 forecast to evacuate zones before danger arrives
                # Grounded in: WHO Anticipatory Action Framework 2020
                # IFRC Forecast-based Financing Mechanism
                if (self.active_baseline in ("AMIS-RU", "SENTINEL")
                        and (self.simulation_time % 15 == 1 or self.simulation_time == 1)
                        and getattr(self, 'forecasts_15_30_60', None)):
                    forecast_t30 = self.forecasts_15_30_60.get(30, self.forecasts_15_30_60.get("t30", {}))
                    if forecast_t30:
                        pre_havens = [
                            n for n, d in world_state.ground_truth.nodes(data=True)
                            if d.get("node_type") in ("SHELTER", "HOSPITAL")
                            and not d.get("compromised", False)
                        ]
                        import random
                        for n_id, ndata in list(world_state.ground_truth.nodes(data=True)):
                            if ndata.get("node_type") != "POPULATION_ZONE":
                                continue
                            if ndata.get("population", 0) <= 0:
                                continue
                            current_danger  = ndata.get("p_danger", 0.0)
                            forecast_data   = forecast_t30.get(n_id, {})
                            forecast_wl     = forecast_data.get("mean", 0.0)
                            # Convert water level forecast to danger proxy
                            # 1.5m = full danger threshold (from flood.py)
                            forecast_danger = min(1.0, forecast_wl / 1.5)
                                
                            # Trigger: currently safe/moderately risky, predicted dangerous in 30 min
                            if current_danger < 0.60 and forecast_danger > 0.5:
                                pre_size = max(3, int(ndata["population"] * 0.05))
                                pre_size = min(pre_size, ndata["population"])
                                # Route through belief graph to nearest available haven
                                for h in sorted(pre_havens,
                                                key=lambda x: world_state.belief.nodes.get(x, {}).get("distance", float("inf"))):
                                    if nx.has_path(world_state.belief, n_id, h):
                                        try:
                                            path = nx.shortest_path(
                                                world_state.belief, n_id, h, weight="distance"
                                            )
                                            cap  = world_state.ground_truth.nodes[h].get("capacity", 8000)
                                            occ  = world_state.ground_truth.nodes[h].get("occupants", 0)
                                            act  = min(pre_size, cap - occ)
                                            if act <= 0:
                                                continue
                                            ndata["population"] -= act
                                            world_state.ground_truth.nodes[n_id]["population"] = ndata["population"]
                                            # Proportionally decrement triage counts to prevent ghost patients
                                            old_pop = ndata["population"] + act
                                            if old_pop > 0:
                                                ratio = act / old_pop
                                            # Pre-emptive self-evacuation is by ambulatory civilians; critical patients (immediate/delayed) still require vehicle rescue
                                            old_t = ndata.get("triage_minor", 0)
                                            if old_t > 0:
                                                dec = min(old_t, act)
                                                ndata["triage_minor"] = old_t - dec
                                                world_state.ground_truth.nodes[n_id]["triage_minor"] = ndata["triage_minor"]
                                                if n_id in world_state.belief.nodes:
                                                    world_state.belief.nodes[n_id]["triage_minor"] = ndata["triage_minor"]

                                            if n_id in world_state.belief.nodes:
                                                world_state.belief.nodes[n_id]["population"] = ndata["population"]
                                            world_state.ground_truth.nodes[h]["occupants"] = occ + act

                                            if h in world_state.belief.nodes:
                                                world_state.belief.nodes[h]["occupants"] = occ + act
                                            self.total_survivors_saved       += act
                                            self.civilian_evacuated_preemptive += act
                                            self.add_event(
                                                f"[{self.simulation_time}m] 🔮 PRE-EMPTIVE: "
                                                f"{act} civilians from "
                                                f"{world_state.get_node_human_name(n_id)} "
                                                f"(forecast_danger={forecast_danger:.2f} in 30m)"
                                            )
                                            break
                                        except Exception:
                                            continue

                # 4. Multi-Objective Decision Alternatives & Outcomes Utility Forecast
                from backend.decision_engine.decision_optimizer import DecisionOptimizer
                targets_list = [
                    n_id for n_id, data in belief_snapshot.nodes(data=True)
                    if data.get("node_type") in ("POPULATION_ZONE", "BRIDGE", "JUNCTION")
                    and ((data.get("triage_immediate") or 0) + (data.get("triage_delayed") or 0)) > 0
                ]
                vehicles_list = [
                    {"id": agent.id, "location": agent.current_node, "type": getattr(agent, 'vehicle_type', 'STANDARD_CAR')}
                    for agent in self.agents.values()
                ]
                
                self.ranked_portfolios = DecisionOptimizer.optimize_assignments(
                    belief_snapshot,
                    targets_list,
                    vehicles_list,
                    self.disaster_type
                )

                # Recalculate situation assessment with current portfolio to evaluate stability index
                self.situation_assessment = SituationAssessmentEngine.assess_from_graph(
                    belief_snapshot,
                    current_portfolio=self.ranked_portfolios
                )

                # 5. Counterfactual Sensitivity (What-If analysis on the active route)
                from backend.decision_engine.counterfactual import CounterfactualEngine
                self.whatif_sensitivity = {}
                for agent in self.agents.values():
                    if agent.route and len(agent.route) > 1:
                        base_path = [agent.current_node] + agent.route
                        self.whatif_sensitivity[agent.id] = CounterfactualEngine.run_whatif_sensitivity_analysis(
                            belief_snapshot,
                            agent.current_node,
                            agent.route[-1],
                            agent.vehicle_type,
                            base_path
                        )
                
                # Print decision cycle logic overview to command console
                print(f"[Decision Cycle v2.0] Situation Assessment completed. Severity Index: {self.situation_assessment['severity_index']:.2f}")


            except Exception as cycle_err:
                import traceback
                print(f"[Decision Cycle v2.0] Warning during cycle initialization: {cycle_err}")
                traceback.print_exc()
        
        # Haven staging reset — every 30 steps civilians move onward from staging areas
        # Models real shelter operations where people are processed and transported inland
        if self.simulation_time % 30 == 0 and self.simulation_time > 0:
            for n_id, data in world_state.ground_truth.nodes(data=True):
                if data.get("is_staging", False) or data.get("node_type") in ("SHELTER", "HOSPITAL"):
                    current_occ = data.get("occupants", 0)
                    # 60% of current occupants move onward each 30-step cycle
                    moved_on = int(current_occ * 0.60)
                    data["occupants"] = current_occ - moved_on
                    if n_id in world_state.belief.nodes:
                        world_state.belief.nodes[n_id]["occupants"] = data["occupants"]

        # Reset edge congestion factors at the start of each step
        for u, v, d in world_state.ground_truth.edges(data=True):
            d['congestion_factor'] = 1.0
            if u in world_state.belief.edges and v in world_state.belief.edges[u]:
                world_state.belief.edges[u, v]['congestion_factor'] = 1.0

        # BROADCAST TRIGGER — identical threshold for ALL baselines
        # Sentinel advantage comes from routing quality, NOT from earlier trigger
        if self.broadcast_mode == "SHELTER_IN_PLACE":
            severity = 0.0
            if hasattr(self, 'situation_assessment') and self.situation_assessment:
                severity = self.situation_assessment.get("severity_index", 0.0)
            else:
                # Dynamically compute situation assessment if not ran by decision cycle (baselines)
                from backend.decision_engine.situation_assessment import SituationAssessmentEngine
                snapshot = world_state.get_belief_snapshot()
                sa = SituationAssessmentEngine.assess_from_graph(snapshot)
                severity = sa.get("severity_index", 0.0)
                # Keep cached so we don't re-run every step
                self.situation_assessment = sa

            if severity > 40.0 and self.simulation_time >= 30:
                self.broadcast_mode = "DIRECTED_EVACUATION"
                self.broadcast_trigger_step = self.simulation_time
                # Count zones already too dangerous when broadcast fires
                # These are zones reactive systems CANNOT evacuate
                for _n, _d in world_state.ground_truth.nodes(data=True):
                    if (_d.get("node_type") == "POPULATION_ZONE"
                            and _d.get("population", 0) > 0
                            and _d.get("p_danger", 0.0) >= 0.75):
                        self.zones_unreachable_at_trigger += 1
                self.add_event(
                    f"[{self.simulation_time}m] 📢 EVACUATION ORDER ISSUED. "
                    f"Severity={severity:.1f}. "
                    f"Zones already unreachable: {self.zones_unreachable_at_trigger}"
                )

        # Civilian Evacuation — Three-tier routing by system capability
        if self.broadcast_mode == "DIRECTED_EVACUATION":
            havens = [
                n for n, d in world_state.ground_truth.nodes(data=True)
                if d.get("node_type") in ("SHELTER", "HOSPITAL")
                and not d.get("compromised", False)
            ]

            # Pre-compute connected components ONCE per step to avoid O(N²) BFS calls
            # Build routing graph for current baseline (fair belief routing for all)
            def _belief_edge_ok(u, v):
                ed = world_state.belief.edges.get((u, v)) or world_state.belief.edges.get((v, u))
                if not ed:
                    return False
                return (not ed.get("blocked", False)
                        and ed.get("confidence", 0.5) > 0.4)
            _evac_routing_graph = nx.subgraph_view(
                world_state.belief, filter_edge=_belief_edge_ok
            )

            # Build node→component_id mapping for O(1) connectivity checks
            _component_map = {}
            for comp_id, component in enumerate(nx.connected_components(_evac_routing_graph)):
                for node in component:
                    _component_map[node] = comp_id

            for n_id, ndata in list(world_state.ground_truth.nodes(data=True)):
                if ndata.get("node_type") != "POPULATION_ZONE":
                    continue
                if ndata.get("population", 0) <= 0:
                    continue
                if ndata.get("p_danger", 0.0) >= 0.75:
                    continue  # zone critically dangerous — no safe exit

                # Use pre-built routing graph (already selected above)
                routing_graph = _evac_routing_graph

                # ── Haven selection by system capability ───────────────────
                evac_rate  = 0.03  # identical for ALL systems
                evac_size  = max(5, int(ndata["population"] * evac_rate))
                evac_size  = min(evac_size, ndata["population"])
                saved_here = 0

                # O(1) connectivity check using pre-computed component map
                n_comp = _component_map.get(n_id)

                # Baseline: nearest available haven
                best_dist = float("inf")
                best_path = None
                best_haven = None
                for h in havens:
                    cap = world_state.ground_truth.nodes[h].get("capacity", 8000)
                    occ = world_state.ground_truth.nodes[h].get("occupants", 0)
                    if occ >= cap:
                        self.haven_overflow_events += 1
                        continue
                    if n_comp is None or _component_map.get(h) != n_comp:
                        continue
                    try:
                        path = nx.shortest_path(routing_graph, n_id, h, weight="distance")
                        dist = sum(routing_graph.edges[path[i], path[i+1]].get("distance", 1.0)
                                   for i in range(len(path) - 1))
                        if dist < best_dist:
                            best_dist  = dist
                            best_path  = path
                            best_haven = h
                    except Exception:
                        self.route_failure_during_evac += 1
                        continue

                if best_path:
                    cap    = world_state.ground_truth.nodes[best_haven].get("capacity", 8000)
                    occ    = world_state.ground_truth.nodes[best_haven].get("occupants", 0)
                    actual = min(evac_size, cap - occ)
                    ndata["population"] -= actual
                    # Proportionally decrement triage counts to prevent ghost patients
                    old_pop = ndata["population"] + actual
                    if old_pop > 0:
                        ratio = actual / old_pop
                        for triage_key in ("triage_immediate", "triage_delayed", "triage_minor"):
                            old_t = ndata.get(triage_key, 0)
                            if old_t > 0:
                                dec = max(1, int(old_t * ratio))
                                ndata[triage_key] = max(0, old_t - dec)
                                world_state.ground_truth.nodes[n_id][triage_key] = ndata[triage_key]
                                if n_id in world_state.belief.nodes:
                                    world_state.belief.nodes[n_id][triage_key] = ndata[triage_key]
                    if n_id in world_state.belief.nodes:
                        world_state.belief.nodes[n_id]["population"] = ndata["population"]
                    world_state.ground_truth.nodes[best_haven]["occupants"] = occ + actual

                    if best_haven in world_state.belief.nodes:
                        world_state.belief.nodes[best_haven]["occupants"] = occ + actual
                    saved_here += actual
                    for i in range(len(best_path) - 1):
                        u, v = best_path[i], best_path[i+1]
                        world_state.ground_truth.edges[u, v]["congestion_factor"] = (
                            world_state.ground_truth.edges[u, v].get("congestion_factor", 1.0) + 0.3
                        )
                else:
                    self.route_failure_during_evac += 1

                # Record saves
                if saved_here > 0:
                    self.total_survivors_saved     += saved_here
                    self.civilian_evacuated_reactive += saved_here
                    if n_id not in self.civilian_stuck_timers:
                        self.civilian_stuck_timers[n_id] = 0
                    self.civilian_stuck_timers[n_id] = 0
                else:
                    # Stuck civilian SMS logic — unchanged from original
                    stuck_count = self.civilian_stuck_timers.get(n_id, 0) + 1
                    self.civilian_stuck_timers[n_id] = stuck_count
                    if stuck_count >= 3:
                        for neighbor in world_state.ground_truth.neighbors(n_id):
                            gt_edge     = world_state.ground_truth.edges[n_id, neighbor]
                            belief_edge = (world_state.belief.edges.get((n_id, neighbor))
                                           or world_state.belief.edges.get((neighbor, n_id)))
                            if gt_edge.get("blocked", False) and belief_edge and not belief_edge.get("blocked", False):
                                belief_edge["blocked"]     = True
                                belief_edge["confidence"]  = 1.0
                                self.add_event(
                                    f"[{self.simulation_time}m] 📡 SMS ALERT: "
                                    f"Stuck civilians at {world_state.get_node_human_name(n_id)}. "
                                    f"Road marked BLOCKED."
                                )
                                break
                        self.civilian_stuck_timers[n_id] = 0

            # ── VEHICLE-ASSISTED MASS EVACUATION FOR STRANDED ZONES ──
            # Idle rescue vehicles (boats, helicopters, high-water trucks) actively dispatch
            # to evacuate civilian population zones that are isolated on foot.
            idle_water_air_agents = [
                agent for agent in self.agents.values()
                if agent.agent_type == "RESCUE"
                and agent.status == AgentStatus.IDLE
                and getattr(agent, 'survivors_onboard', 0) == 0
                and getattr(agent, 'vehicle_type', 'STANDARD_CAR') in ("ZODIAC_BOAT", "HELICOPTER", "HIGH_WATER_TRUCK")
                and not getattr(agent, 'is_manual_override', False)
            ]

            if idle_water_air_agents:
                stranded_zones = []
                for n_id, ndata in world_state.ground_truth.nodes(data=True):
                    if ndata.get("node_type") != "POPULATION_ZONE":
                        continue
                    pop = ndata.get("population", 0)
                    if pop <= 0:
                        continue
                    
                    # A zone is stranded if it cannot reach any open safe haven on foot
                    n_comp = _component_map.get(n_id)
                    can_reach_haven = False
                    for h in havens:
                        if n_comp is not None and _component_map.get(h) == n_comp:
                            can_reach_haven = True
                            break
                    if not can_reach_haven:
                        stranded_zones.append((n_id, pop, ndata))

                # Dispatch idle agents to stranded zones
                for agent in idle_water_air_agents:
                    if not stranded_zones:
                        break
                    v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR')
                    cost_key = f'cost_{v_type}'
                    routing_graph = world_state.belief
                    
                    best_zone = None
                    best_path = None
                    best_dist = float('inf')
                    
                    for zone_id, pop, zdata in stranded_zones:
                        if nx.has_path(routing_graph, agent.current_node, zone_id):
                            try:
                                active_view = nx.subgraph_view(routing_graph, filter_edge=lambda u, v: routing_graph.edges[u, v].get(cost_key, 1e9) < 1e9)
                                if nx.has_path(active_view, agent.current_node, zone_id):
                                    path = nx.shortest_path(active_view, agent.current_node, zone_id, weight=cost_key)
                                    is_passable = True
                                    for i in range(len(path) - 1):
                                        cost = routing_graph.edges[path[i], path[i+1]].get(cost_key, 0.0)
                                        if cost >= 1e9:
                                            is_passable = False
                                            break
                                    if not is_passable:
                                        continue
                                        
                                    dist = sum(routing_graph.edges[path[i], path[i+1]].get("distance", 1.0) for i in range(len(path)-1))
                                    if dist < best_dist:
                                        best_dist = dist
                                        best_zone = zone_id
                                        best_path = path
                            except Exception:
                                continue
                    
                    if best_zone and best_path:
                        agent.route = best_path[1:]
                        agent.full_planned_route = list(best_path)
                        agent.target_node = best_zone
                        agent.status = AgentStatus.MOVING
                        agent.next_node = None
                        agent.progress_on_edge = 0.0
                        
                        from backend.agents.fleet_config import FLEET_SPECIFICATIONS
                        spec = FLEET_SPECIFICATIONS.get(v_type, {})
                        vehicle_cap = spec.get("capacity", 50)
                        gmm.allocate_capacity(best_zone, vehicle_cap)
                        agent.egl_locked_target = best_zone
                        
                        self.add_xai_event(
                            action=f"Adaptive Evacuation: Dispatched {agent.id} ({v_type}) to stranded zone {world_state.get_node_human_name(best_zone)}",
                            reason=f"Zone is isolated by floodwaters on foot. Population: {world_state.belief.nodes[best_zone].get('population', 0)}",
                            confidence=world_state.belief.nodes[best_zone].get('p_state_correct', 1.0)
                        )
                        stranded_zones = [(zid, p, zd) for zid, p, zd in stranded_zones if zid != best_zone]



        # Adjust survival decay rate (gamma) and triage exposure scaling per disaster scenario
        from backend.config_params.parameters import params
        disaster_upper = self.disaster_type.upper()
        if disaster_upper == "EARTHQUAKE":
            gamma = getattr(params, 'gamma_earthquake', 0.008)
            imm_multiplier = 1.8
            del_multiplier = 1.0
        elif disaster_upper == "CYCLONE":
            gamma = getattr(params, 'gamma_cyclone', 0.005)
            imm_multiplier = 1.3
            del_multiplier = 1.2
        elif disaster_upper == "WILDFIRE":
            gamma = getattr(params, 'gamma_wildfire', 0.020)
            imm_multiplier = 2.0
            del_multiplier = 1.5
        else:                            # FLOOD or default
            gamma = getattr(params, 'gamma_flood', 0.005)
            imm_multiplier = 0.5
            del_multiplier = 0.8
        
        # --- 1. POPULATION DECAY & TRIAGE CLASSIFICATION (Ground Truth) ---
        for n_id, data in world_state.ground_truth.nodes(data=True):
            pop = data.get('population', 0)
            p_danger = data.get('p_danger', 0.0)
            if pop > 0:
                if p_danger > 0.5:
                    # Scale gamma (decay per minute) by delta_t in minutes
                    delta_t = float(settings.TIMESTEP_DURATION)
                    decay_factor = gamma * (delta_t / 60.0) * p_danger
                    new_pop = int(pop * max(0.0, 1.0 - decay_factor))
                    pop = new_pop
                    world_state.ground_truth.nodes[n_id]['population'] = pop
                    
                # Update triage buckets based on hazard exposure (p_danger)
                imm_ratio = min(0.5, p_danger * imm_multiplier)
                del_ratio = min(0.4, p_danger * del_multiplier)
                
                t_imm = int(pop * imm_ratio)
                t_del = int(pop * del_ratio)
                t_min = pop - t_imm - t_del
                
                world_state.ground_truth.nodes[n_id]['triage_immediate'] = t_imm
                world_state.ground_truth.nodes[n_id]['triage_delayed'] = t_del
                world_state.ground_truth.nodes[n_id]['triage_minor'] = t_min

        # --- DYNAMIC FLOOD PROGRESSION ---
        if self.disaster_type == "FLOOD":
            from backend.disaster.flood import FloodModule
            # High tide scales rainfall accumulation significantly (outfall gates closed)
            rain_rate = 1.2 if is_high_tide else 0.55
            if self.env_mode == "HISTORICAL" and self.historical_preset:
                from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
                preset = HISTORICAL_PRESETS.get("FLOOD", {}).get(self.historical_preset, {})
                if preset and "timeline" in preset:
                    timeline = preset["timeline"]
                    active_step = max([k for k in timeline.keys() if k <= self.simulation_time], default=None)
                    if active_step is not None and "rainfall" in timeline[active_step]:
                        rain_rate = timeline[active_step]["rainfall"]
                        if not is_high_tide:
                            rain_rate = rain_rate * 0.5
            
            # Update telemetry sensors frequently to represent real world
            import random
            self.sensor_rainfall_rate = max(0.0, rain_rate * 25.0 + random.uniform(-2.5, 2.5))
            self.sensor_wind_speed_kmh = max(0.0, (self.wind_speed if hasattr(self, "wind_speed") else 15.0) + random.uniform(-3.0, 3.0))
            self.sensor_surge_depth_m = max(0.0, (1.8 if is_high_tide else 0.4) + random.uniform(-0.1, 0.1))
            self.sensor_seismic_pga_g = 0.0
            
            flood_mod = FloodModule(rainfall=rain_rate)
            newly_blocked = flood_mod.update_simulation_step(world_state.ground_truth, self.simulation_time)
            for u, v in newly_blocked:
                # Sync blockages to belief
                world_state.belief.edges[u, v]['blocked'] = True
                world_state.belief.edges[u, v]['confidence'] = 1.0
                self.add_event(f"[{self.simulation_time}m] 🚨 ROAD CLOSED: {u} ↔ {v} is submerged under floodwaters!")
                
            # Compute average water level across flooded nodes
            flooded_nodes = [d.get("water_level", 0.0) for n, d in world_state.ground_truth.nodes(data=True) if d.get("status") == "FLOODED"]
            self.sensor_water_level_m = sum(flooded_nodes) / len(flooded_nodes) if flooded_nodes else 0.0
                
            # If Low tide, apply natural drainage (water levels slowly recede)
            if not is_high_tide:
                for n_id, data in world_state.ground_truth.nodes(data=True):
                    wl = data.get('water_level', 0.0)
                    if wl > 0.0:
                        new_wl = max(0.0, wl - 3.2)
                        data['water_level'] = new_wl
                        eff_elev = data.get("effective_elevation", data.get("elevation", 10.0))
                        if (new_wl - eff_elev) < params.flood_car_blocked_m and data.get('status') == "FLOODED":
                            data['status'] = "SAFE"
                            data['p_danger'] = max(0.05, data.get('p_danger', 0.0) - 0.5)
                            # Sync back to belief
                            if n_id in world_state.belief:
                                world_state.belief.nodes[n_id]['status'] = "SAFE"
                                world_state.belief.nodes[n_id]['p_danger'] = data['p_danger']
                                world_state.belief.nodes[n_id]['water_level'] = new_wl
                                
                            # Clean edge blockages if both endpoints are SAFE!
                            for neighbor in list(world_state.ground_truth.neighbors(n_id)):
                                if not world_state.ground_truth.has_edge(n_id, neighbor):
                                    continue
                                neighbor_status = world_state.ground_truth.nodes[neighbor].get('status', 'SAFE')
                                if neighbor_status == "SAFE":
                                    world_state.ground_truth.edges[n_id, neighbor]['blocked'] = False
                                    if world_state.belief.has_edge(n_id, neighbor):
                                        world_state.belief.edges[n_id, neighbor]['blocked'] = False
                                        world_state.belief.edges[n_id, neighbor]['confidence'] = 1.0
                                
        elif self.disaster_type.upper() == "EARTHQUAKE":
            from backend.disaster.earthquake import EarthquakeModule
            
            # Update telemetry sensors frequently to represent real world
            import random
            decay = math.exp(-self.simulation_time / 10.0)
            pga_val = getattr(self, "magnitude_mw", 6.5) * 0.12
            if self.env_mode == "HISTORICAL" and self.historical_preset:
                from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
                preset = HISTORICAL_PRESETS.get("EARTHQUAKE", {}).get(self.historical_preset, {})
                if preset and "timeline" in preset:
                    timeline = preset["timeline"]
                    active_step = max([k for k in timeline.keys() if k <= self.simulation_time], default=None)
                    if active_step is not None and "pga" in timeline[active_step]:
                        pga_val = timeline[active_step]["pga"]
            self.sensor_seismic_pga_g = max(0.001, pga_val * decay + random.uniform(-0.02, 0.02))
            self.sensor_wind_speed_kmh = max(0.0, 10.0 + random.uniform(-2.0, 2.0))
            self.sensor_rainfall_rate = max(0.0, 0.0 + random.uniform(0.0, 1.0))
            self.sensor_water_level_m = 0.0
            self.sensor_surge_depth_m = 0.0
            
            eq_mod = getattr(self, '_disaster_module', None)
            if eq_mod is None or not hasattr(eq_mod, 'update_simulation_step'):
                from backend.disaster.earthquake import EarthquakeModule
                eq_mod = EarthquakeModule(magnitude_mw=getattr(self, "magnitude_mw", 6.5))
            newly_blocked = eq_mod.update_simulation_step(world_state.ground_truth, self.simulation_time)
            for u, v in newly_blocked:
                # Sync blockages to belief
                world_state.belief.edges[u, v]['blocked'] = True
                world_state.belief.edges[u, v]['confidence'] = 1.0
                self.add_event(f"[{self.simulation_time}m] 🚨 STRUCTURAL FAILURE: road {u} ↔ {v} collapsed due to seismic aftershocks!")
        elif self.disaster_type.upper() == "CYCLONE":
            from backend.disaster.cyclone import CycloneModule
            
            # Update telemetry sensors frequently to represent real world
            import random
            base_wind = getattr(self, "wind_speed", 120.0)
            surge_depth = 1.5 + (1.0 if is_high_tide else 0.0)
            rain_rate = 1.0
            if self.env_mode == "HISTORICAL" and self.historical_preset:
                from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
                preset = HISTORICAL_PRESETS.get("CYCLONE", {}).get(self.historical_preset, {})
                if preset and "timeline" in preset:
                    timeline = preset["timeline"]
                    active_step = max([k for k in timeline.keys() if k <= self.simulation_time], default=None)
                    if active_step is not None:
                        t_data = timeline[active_step]
                        if "windspeed" in t_data:
                            base_wind = t_data["windspeed"]
                        if "surge_depth_m" in t_data:
                            surge_depth = t_data["surge_depth_m"]
                        if "rainfall" in t_data:
                            rain_rate = t_data["rainfall"]
            self.sensor_wind_speed_kmh = max(0.0, base_wind + random.uniform(-10.0, 10.0))
            self.sensor_surge_depth_m = max(0.0, surge_depth + random.uniform(-0.2, 0.2))
            self.sensor_rainfall_rate = max(0.0, rain_rate * 45.0 + random.uniform(-5.0, 5.0))
            self.sensor_water_level_m = self.sensor_surge_depth_m * 0.85
            self.sensor_seismic_pga_g = 0.0
            
            cyc_mod = CycloneModule(wind_speed=base_wind)
            newly_blocked = cyc_mod.update_simulation_step(world_state.ground_truth, self.simulation_time)
            for u, v in newly_blocked:
                world_state.belief.edges[u, v]['blocked'] = True
                world_state.belief.edges[u, v]['confidence'] = 1.0
                self.add_event(f"[{self.simulation_time}m] 🚨 ROAD CLOSED: road {u} ↔ {v} is blocked by storm winds/debris!")
        elif self.disaster_type.upper() == "WILDFIRE":
            from backend.disaster.wildfire import WildfireModule
            
            import random
            base_wind = getattr(self, "wind_speed", 25.0)
            if self.env_mode == "HISTORICAL" and self.historical_preset:
                from backend.simulation.benchmarks.historical_presets import HISTORICAL_PRESETS
                preset = HISTORICAL_PRESETS.get("WILDFIRE", {}).get(self.historical_preset, {})
                if preset and "timeline" in preset:
                    timeline = preset["timeline"]
                    active_step = max([k for k in timeline.keys() if k <= self.simulation_time], default=None)
                    if active_step is not None and "windspeed" in timeline[active_step]:
                        base_wind = timeline[active_step]["windspeed"]
            self.sensor_wind_speed_kmh = max(0.0, base_wind + random.uniform(-4.0, 4.0))
            self.sensor_rainfall_rate = 0.0
            self.sensor_water_level_m = 0.0
            self.sensor_surge_depth_m = 0.0
            self.sensor_seismic_pga_g = 0.0
            
            wind_ms = base_wind / 3.6
            wind_dir = 225.0
            if self.weather and 'current_weather' in self.weather:
                cw = self.weather['current_weather']
                wind_dir = cw.get('winddirection', 225.0)
            wf_mod = WildfireModule(wind_speed_ms=wind_ms, wind_direction_deg=wind_dir)
            newly_blocked = wf_mod.update_simulation_step(world_state.ground_truth, self.simulation_time)
            for u, v in newly_blocked:
                # Sync blockages to belief
                world_state.belief.edges[u, v]['blocked'] = True
                world_state.belief.edges[u, v]['confidence'] = 1.0
                self.add_event(f"[{self.simulation_time}m] 🚨 ROAD CLOSED: road {u} ↔ {v} is blocked by active wildfire front!")

        # Sync ground truth hazard state to belief graph ONLY for nodes where agents are physically present or visited nodes
        agent_nodes = {agent.current_node for agent in self.agents.values() if agent.current_node}
        for n_id, gt_data in world_state.ground_truth.nodes(data=True):
            if n_id in world_state.belief:
                b_data = world_state.belief.nodes[n_id]
                if b_data.get('visited_at_least_once', False) or n_id in agent_nodes:
                    if 'water_level' in gt_data:
                        b_data['water_level'] = gt_data['water_level']
                    b_data['p_danger'] = gt_data.get('p_danger', b_data.get('p_danger', 0.0))
                    b_data['status'] = gt_data.get('status', b_data.get('status', 'SAFE'))

        # --- HAVEN RESOURCE DECAY ---
        for n_id, data in world_state.ground_truth.nodes(data=True):
            if data.get('node_type') in ("SHELTER", "HOSPITAL"):
                occupants = data.get('occupants', 0)
                resources = data.get('resources', {"food": 100.0, "water": 100.0, "medicine": 100.0, "fuel": 100.0})
                
                # Decay rates proportional to occupants scaled per minute
                decay_rate = (0.02 + 0.05 * occupants) / 60.0
                resources['food'] = max(0.0, resources['food'] - decay_rate)
                resources['water'] = max(0.0, resources['water'] - decay_rate - (0.01 / 60.0))
                
                med_decay = (0.01 + 0.03 * data.get('p_danger', 0.0) * occupants) / 60.0
                resources['medicine'] = max(0.0, resources['medicine'] - med_decay)
                resources['fuel'] = max(0.0, resources['fuel'] - (0.1 / 60.0))
                
                data['resources'] = resources
                if n_id in world_state.belief:
                    world_state.belief.nodes[n_id]['resources'] = resources.copy()
                    world_state.belief.nodes[n_id]['occupants'] = occupants

                # Warnings
                if resources['food'] < 20.0 and not data.get('warned_food', False):
                    data['warned_food'] = True
                    self.add_event(f"[{self.simulation_time}m] ⚠️ SUPPLY ALERT: Haven {n_id} is running critically low on Food!")
                if resources['water'] < 20.0 and not data.get('warned_water', False):
                    data['warned_water'] = True
                    self.add_event(f"[{self.simulation_time}m] ⚠️ SUPPLY ALERT: Haven {n_id} is running critically low on Water!")

        # --- CHECK COMMS BLACKOUTS FOR AGENTS ---
        for agent in self.agents.values():
            lat = world_state.ground_truth.nodes[agent.current_node].get('y', world_state.ground_truth.nodes[agent.current_node].get('lat'))
            lon = world_state.ground_truth.nodes[agent.current_node].get('x', world_state.ground_truth.nodes[agent.current_node].get('lon'))
            base_node = self.coordinator.base_node if self.coordinator else None
            in_blackout = is_in_blackout_zone(lat, lon, self.blackout_zones) if agent.current_node != base_node else False
            
            if in_blackout and not agent.comms_blackout:
                agent.comms_blackout = True
                self.add_event(f"[{self.simulation_time}m] 🚫 COMMS LOST: {agent.id} entered a communication blackout zone. Presumed compromised.")
                
                # Failsafe Protocol: Purge downed agent from Ledger and dispatch reinforcements
                if agent.target_node:
                    self.add_event(f"[System] AI RATIONALE: CASUALTY / BLACKOUT DETECTED. Stripping {agent.id}'s target from Ledger and preparing immediate reinforcement dispatch.")
                    
                    if agent.agent_type == "SCOUT":
                        # Remove from cleared nodes so it gets swept again
                        if gmm.is_cleared(agent.target_node):
                            gmm.clearance_ledger.remove(agent.target_node)
                            
                    # Abort their mission
                    self._release_egl_lock(agent)
                    agent.target_node = None
                    agent.route = []
                    agent.status = AgentStatus.IDLE
                    
            elif not in_blackout and agent.comms_blackout:
                agent.comms_blackout = False
                self.add_event(f"[{self.simulation_time}m] 📶 COMMS RESTORED: {agent.id} exited blackout zone.")
                # Flush pending observations
                if agent.pending_observations:
                    for obs in agent.pending_observations:
                        sensor = "DRONE_CAMERA" if getattr(agent, 'vehicle_type', 'STANDARD_CAR') == "HELICOPTER" else "HUMAN_VISUAL"
                        apply_scout_observation(
                            world_state.belief, 
                            world_state.ground_truth, 
                            obs,
                            sensor_type=sensor,
                            wind_speed_kmh=self.weather.get('windspeed', 0.0) if self.weather else 0.0,
                            smoke_present=self.weather.get('smoke', False) if self.weather else False
                        )
                    self.add_xai_event(
                        action=f"Scout {agent.id} flushed {len(agent.pending_observations)} telemetry records to EOC.",
                        reason="Re-established connection to secure comms network."
                    )
                    agent.pending_observations = []

        # --- BLIND RECONNECT PROTOCOL FOR BLACKED OUT IDLE AGENTS ---
        for agent in self.agents.values():
            if agent.comms_blackout and agent.status == AgentStatus.IDLE:
                base_node = self.coordinator.base_node if self.coordinator else None
                if base_node and agent.current_node != base_node:
                    try:
                        v_type = getattr(agent, "vehicle_type", "STANDARD_CAR")
                        w_key = f'cost_{v_type}'
                        path = nx.shortest_path(world_state.belief, agent.current_node, base_node, weight=w_key)
                        if path and len(path) > 1:
                            agent.route = path[1:]
                            agent.full_planned_route = list(path)
                            agent.target_node = base_node
                            agent.status = AgentStatus.MOVING
                            agent.progress_on_edge = 0.0
                            agent.next_node = None
                            self.add_event(f"[{self.simulation_time}m] 📶 BLIND RECONNECT: {agent.id} initiated return-to-base protocol to restore communications.")
                    except Exception as reconnect_err:
                        print(f"[Comms] Warning: Blind reconnect routing failed for agent {agent.id}: {reconnect_err}")

        t_physics_end = time.perf_counter()
        self.last_telemetry["physics_ms"] = (t_physics_end - t_physics_start) * 1000

        t_belief_start = time.perf_counter()
        # --- 2. DECAY INFORMATION (Belief) ---
        # Equalized information environment: ALL baselines receive identical knowledge decay
        if int(self.simulation_time) % 5 == 0:
            decay_confidence(world_state.belief, 5 * settings.KNOWLEDGE_DECAY_RATE)


        # Precompute edge costs for fast routing with dynamic congestion multiplier (BPR function)
        
        # Calculate active vehicle flow count per edge
        edge_flows = {}
        for agent in self.agents.values():
            if agent.status == AgentStatus.MOVING and agent.current_node and agent.next_node:
                edge_key = tuple(sorted((agent.current_node, agent.next_node)))
                edge_flows[edge_key] = edge_flows.get(edge_key, 0) + 1

        for u, v, d in world_state.belief.edges(data=True):
            edge_key = tuple(sorted((u, v)))
            flow = edge_flows.get(edge_key, 0)
            wl = d.get('water_level', 0.0)
            blk = d.get('blocked', False)

            # Only recalculate if edge water level, blocked status, or active traffic flow changed
            if 'cost_STANDARD_CAR' not in d or d.get('_last_wl') != wl or d.get('_last_blk') != blk or flow > 0 or d.get('_last_flow', 0) > 0:
                road_type = d.get('highway', 'residential')
                capacity = ROAD_CAPACITIES.get(road_type, 400)
                congestion_multiplier = 1.0 + BPR_ALPHA * ((flow / capacity) ** BPR_BETA) if flow > 0 else 1.0

                d['cost_STANDARD_CAR'] = calculate_edge_cost(world_state.belief, u, v, d, 'STANDARD_CAR', disaster_type=self.disaster_type) * congestion_multiplier
                d['cost_ZODIAC_BOAT'] = calculate_edge_cost(world_state.belief, u, v, d, 'ZODIAC_BOAT', disaster_type=self.disaster_type) * congestion_multiplier
                d['cost_HIGH_WATER_TRUCK'] = calculate_edge_cost(world_state.belief, u, v, d, 'HIGH_WATER_TRUCK', disaster_type=self.disaster_type) * congestion_multiplier
                d['cost_HELICOPTER'] = calculate_edge_cost(world_state.belief, u, v, d, 'HELICOPTER', disaster_type=self.disaster_type) * congestion_multiplier
                d['cost_SCOUT_CAR'] = calculate_edge_cost(world_state.belief, u, v, d, 'SCOUT_CAR', disaster_type=self.disaster_type) * congestion_multiplier
                
                d['_last_wl'] = wl
                d['_last_blk'] = blk
                d['_last_flow'] = flow
            
        # Reset and compute High-Value Targets (HVTs) using counter-factual routing (UI telemetry only)
        if self.enable_ui_telemetry and int(self.simulation_time) % 10 == 0:
            for u, v, d in world_state.belief.edges(data=True):
                d['hvt'] = False
                d['hvt_priority'] = 0
            for u, v, d in world_state.ground_truth.edges(data=True):
                d['hvt'] = False
                d['hvt_priority'] = 0

            try:
                if self.coordinator is not None:
                    active_view = nx.subgraph_view(world_state.belief, filter_edge=lambda u, v: not world_state.belief.edges[u, v].get('blocked', False))
                    base_node = self.coordinator.base_node
                    
                    try:
                        d_actual, p_actual_dict = nx.single_source_dijkstra(active_view, base_node, weight='distance')
                    except Exception:
                        d_actual, p_actual_dict = {}, {}
                        
                    try:
                        d_optimal, p_optimal_dict = nx.single_source_dijkstra(world_state.belief, base_node, weight='distance')
                    except Exception:
                        d_optimal, p_optimal_dict = {}, {}
                        
                    for n_id, ndata in world_state.belief.nodes(data=True):
                        if ndata.get('population', 0) > 0 and n_id != base_node:
                            if n_id in d_actual and n_id in d_optimal:
                                dist_actual = d_actual[n_id]
                                dist_optimal = d_optimal[n_id]
                                
                                if dist_actual >= 1.4 * dist_optimal:
                                    p_optimal = p_optimal_dict[n_id]
                                    for i in range(len(p_optimal)-1):
                                        uu, vv = p_optimal[i], p_optimal[i+1]
                                        if world_state.belief.edges[uu, vv].get('blocked', False):
                                            detour_saved = max(1.0, dist_actual - dist_optimal)
                                            pop = ndata.get('population', 0)
                                            val = max(1, int(detour_saved * pop))
                                            
                                            world_state.belief.edges[uu, vv]['hvt'] = True
                                            prev_belief_prio = world_state.belief.edges[uu, vv].get('hvt_priority', 0)
                                            world_state.belief.edges[uu, vv]['hvt_priority'] = prev_belief_prio + val
                                            
                                            world_state.ground_truth.edges[uu, vv]['hvt'] = True
                                            prev_gt_prio = world_state.ground_truth.edges[uu, vv].get('hvt_priority', 0)
                                            world_state.ground_truth.edges[uu, vv]['hvt_priority'] = prev_gt_prio + val
            except Exception as ex:
                print(f"[HVT] Error running counter-factual analysis: {ex}")

        # Dynamically Recompile Vector Graph Matrix and DEST/DNST state tensors
        t_tensor_start = time.perf_counter()
        self.recompile_and_sync_tensors()
        t_tensor_end = time.perf_counter()
        self.last_telemetry["tensor_ms"] = (t_tensor_end - t_tensor_start) * 1000

        t_belief_end = time.perf_counter()
        self.last_telemetry["belief_ms"] = (t_belief_end - t_belief_start) * 1000

        t_alloc_start = time.perf_counter()
        # --- 3. COORDINATOR ALLOCATION ---
        # Decrement stall cooldowns
        for a in self.agents.values():
            if getattr(a, 'stall_cooldown', 0) > 0:
                a.stall_cooldown -= 1

        # Separate idle agents
        idle_scouts = [a for a in self.agents.values() if a.agent_type == "SCOUT" and a.status == AgentStatus.IDLE and not getattr(a, 'is_manual_override', False) and getattr(a, 'stall_cooldown', 0) <= 0]
        idle_rescues = [a for a in self.agents.values() if a.agent_type == "RESCUE" and a.status == AgentStatus.IDLE and not getattr(a, 'is_manual_override', False) and getattr(a, 'survivors_onboard', 0) == 0 and getattr(a, 'stall_cooldown', 0) <= 0]
        
        # Reroute stranded idle rescue agents that have survivors onboard
        stranded_rescues = [a for a in self.agents.values() if a.agent_type == "RESCUE" and a.status == AgentStatus.IDLE and getattr(a, 'survivors_onboard', 0) > 0]
        for agent in stranded_rescues:
            haven_path = self.coordinator.find_nearest_safe_haven(
                world_state.belief, 
                agent.current_node, 
                needs_medical=getattr(agent, 'survivors_immediate', 0) > 0, 
                vehicle_type=getattr(agent, 'vehicle_type', 'STANDARD_CAR')
            )
            if haven_path:
                if haven_path[0] == agent.current_node:
                    haven_path.pop(0)
                if haven_path:
                    agent.route = haven_path
                    agent.full_planned_route = [agent.current_node] + haven_path
                    agent.target_node = haven_path[-1]
                    agent.status = AgentStatus.MOVING
                    agent.next_node = None
                    agent.progress_on_edge = 0.0
                    agent.stranded_ticks = 0
                else:
                    agent.status = AgentStatus.IDLE
                    agent.target_node = None
            else:
                agent.stranded_ticks = getattr(agent, 'stranded_ticks', 0) + 1
                if agent.stranded_ticks >= 3:
                    # Emergency offload survivors at current node to prevent permanent stall
                    curr = agent.current_node
                    offloaded = agent.survivors_onboard
                    world_state.ground_truth.nodes[curr]['population'] = world_state.ground_truth.nodes[curr].get('population', 0) + offloaded
                    if curr in world_state.belief.nodes:
                        world_state.belief.nodes[curr]['population'] = world_state.belief.nodes[curr].get('population', 0) + offloaded
                    self.add_event(f"[{self.simulation_time}m] 🚨 EMERGENCY OFFLOAD: {agent.id} stranded with no route to haven; returned {offloaded} survivors to local node {world_state.get_node_human_name(curr)}.")
                    agent.survivors_onboard = 0
                    agent.survivors_immediate = 0
                    agent.survivors_delayed = 0
                    agent.survivors_minor = 0
                    agent.stranded_ticks = 0
                agent.status = AgentStatus.IDLE
                agent.target_node = None

        total_fleet = len(self.agents)
        active_agents = sum(1 for a in self.agents.values() if a.status != AgentStatus.IDLE)
        total_scouts = sum(1 for a in self.agents.values() if a.agent_type == "SCOUT")
        active_scouts = sum(1 for a in self.agents.values() if a.agent_type == "SCOUT" and a.status != AgentStatus.IDLE)
        total_rescues = sum(1 for a in self.agents.values() if a.agent_type == "RESCUE")
        active_rescues = sum(1 for a in self.agents.values() if a.agent_type == "RESCUE" and a.status != AgentStatus.IDLE)
        fleet_state = {
            "active_agents": active_agents,
            "total_fleet": total_fleet,
            "total_scouts": total_scouts,
            "active_scouts": active_scouts,
            "total_rescues": total_rescues,
            "active_rescues": active_rescues,
            "active_rescues_outbound": sum(
                1 for a in self.agents.values()
                if a.agent_type == "RESCUE"
                and a.status == AgentStatus.MOVING
                and getattr(a, 'survivors_onboard', 0) == 0
            )
        }

        # Scouting allocation (Active for both SGA-RA and AMIS-RU)
        if self.active_baseline in ("AMIS-RU", "SGA-RA", "BASELINE-A") and idle_scouts:
            if self.weather and (self.weather.get('rain_intensity', 0) > 80 or self.weather.get('storm_category', 0) >= 3):
                self.add_event("[System] AI RATIONALE: Severe weather detected. Routing Rescue teams immediately to high priority targets.")
            scout_assignments = self.coordinator.assign_scouts(
                belief_graph=world_state.belief, 
                idle_scouts=idle_scouts, 
                weather_state=self.weather,
                blackout_zones=self.blackout_zones,
                forecasts=self.forecasts_15_30_60,
                disaster_type=self.disaster_type,
                sim_time=float(self.simulation_time),
                fleet_state=fleet_state
            )
            for assign in scout_assignments:
                agent = self.agents[assign['scout_id']]
                agent.target_node = assign['target_node_id']
                agent.route = assign['path']
                if self.active_baseline == "AMIS-RU":
                    agent.egl_locked_target = agent.staged_dispatch_target or assign['target_node_id']
                # Preserve original full planned route for staged re-evaluation lookup
                if not getattr(agent, 'full_planned_route', None) or not agent.staged_dispatch_target:
                    agent.full_planned_route = [agent.current_node] + list(assign.get('full_route', assign['path']))  # store full corridor
                agent.status = AgentStatus.MOVING
                agent.progress_on_edge = 0.0
                agent.next_node = None
                
        elif self.active_baseline == "PSA-RA" and idle_scouts:
            # Baseline B: Scouts only run in the first 15 steps
            if self.simulation_time <= 15:
                scout_assignments = self.coordinator.assign_scouts(
                    belief_graph=world_state.belief, 
                    idle_scouts=idle_scouts, 
                    weather_state=self.weather,
                    blackout_zones=self.blackout_zones,
                    forecasts=self.forecasts_15_30_60,
                    disaster_type=self.disaster_type,
                    sim_time=float(self.simulation_time),
                    fleet_state=fleet_state
                )
                for assign in scout_assignments:
                    agent = self.agents[assign['scout_id']]
                    agent.target_node = assign['target_node_id']
                    agent.route = assign['path']
                    agent.egl_locked_target = agent.staged_dispatch_target or assign['target_node_id']
                    # Preserve original full planned route for staged re-evaluation lookup
                    if not getattr(agent, 'full_planned_route', None) or not agent.staged_dispatch_target:
                        agent.full_planned_route = [agent.current_node] + list(assign.get('full_route', assign['path']))
                    agent.status = AgentStatus.MOVING
                    agent.progress_on_edge = 0.0
                    agent.next_node = None
 
        # Rescue allocation
        allow_rescue = True
        if self.active_baseline == "PSA-RA":
            # Baseline B: Rescue teams only run after step 15
            if self.simulation_time <= 15:
                allow_rescue = False
                
        if allow_rescue and idle_rescues:
            rescue_assignments = self.coordinator.assign_rescues(
                belief_graph=world_state.belief, 
                idle_rescues=idle_rescues, 
                weather_state=self.weather,
                blackout_zones=self.blackout_zones,
                forecasts=self.forecasts_15_30_60,
                disaster_type=self.disaster_type,
                sim_time=float(self.simulation_time),
                fleet_state=fleet_state,
                baseline_type=self.active_baseline
            )
            for assign in rescue_assignments:
                agent = self.agents[assign['team_id']]
                agent.target_node = assign['target_node_id']
                agent.route = assign['path']
                agent.egl_locked_target = agent.staged_dispatch_target or assign['target_node_id']
                # Preserve original full planned route for staged re-evaluation lookup
                if not getattr(agent, 'full_planned_route', None) or not agent.staged_dispatch_target:
                    agent.full_planned_route = [agent.current_node] + list(assign.get('full_route', assign['path']))
                agent.status = AgentStatus.MOVING
                agent.progress_on_edge = 0.0
                agent.next_node = None
                
                # Fetch UWEV explainability attributes to feed Explain AI Panel
                ev = assign.get('ev', 0.0)
                agent_speed = getattr(agent, 'speed', settings.RESCUE_SPEED)
                t_arrival = (assign.get('distance', 0.0) / max(0.1, agent_speed)) / 60.0  # travel time in minutes
                self.add_xai_event(
                    action=f"Rescue team {agent.id} dispatched to zone {world_state.get_node_human_name(agent.target_node)}",
                    reason=f"Mission expected utility is {ev:.2f}. Est travel time: {t_arrival:.1f} min. souls: {world_state.belief.nodes[agent.target_node].get('population', 0)}",
                    confidence=world_state.belief.nodes[agent.target_node].get('p_state_correct', 1.0)
                )

        t_alloc_end = time.perf_counter()
        self.last_telemetry["allocation_ms"] = (t_alloc_end - t_alloc_start) * 1000

        t_sim_start = time.perf_counter()
        # --- 4. EXECUTE AGENT ACTIONS & MOVEMENT ---
        for agent_id, agent in self.agents.items():
            if agent.status == AgentStatus.MOVING:
                leftover_time = float(delta_t)
                reroute_attempts = 0  # Guard against infinite reroute loops
                while leftover_time > 0.0 and agent.status == AgentStatus.MOVING:
                    if agent.next_node is None:
                        if agent.route:
                            next_node = agent.route.pop(0)
                            while next_node == agent.current_node and agent.route:
                                next_node = agent.route.pop(0)
                            if next_node == agent.current_node:
                                if agent.current_node == agent.target_node:
                                    self._reached_target(agent)
                                else:
                                    self._release_egl_lock(agent)
                                    agent.status = AgentStatus.IDLE
                                    agent.target_node = None
                                break
                            agent.next_node = next_node
                            agent.progress_on_edge = 0.0
                        else:
                            # Route is empty, check if we reached target
                            if agent.current_node == agent.target_node:
                                self._reached_target(agent)
                            else:
                                self._release_egl_lock(agent)
                                agent.status = AgentStatus.IDLE
                            break
                    
                    # Check segment properties
                    u, v = agent.current_node, agent.next_node
                    if not world_state.ground_truth.has_edge(u, v):
                        self._release_egl_lock(agent)
                        agent.next_node = None
                        agent.progress_on_edge = 0.0
                        agent.route = []
                        agent.status = AgentStatus.IDLE
                        break
                        
                    edge_data = world_state.ground_truth.edges[u, v]
                    distance = edge_data.get('distance', 100.0)
                    
                    # Fetch water depth above road surface (matching confidence_dijkstra.py)
                    wl_u = world_state.ground_truth.nodes[u].get('water_level', 0.0)
                    wl_v = world_state.ground_truth.nodes[v].get('water_level', 0.0)
                    elev_u = world_state.ground_truth.nodes[u].get('effective_elevation', world_state.ground_truth.nodes[u].get('elevation', 10.0))
                    elev_v = world_state.ground_truth.nodes[v].get('effective_elevation', world_state.ground_truth.nodes[v].get('elevation', 10.0))
                    water_level = max(max(0.0, wl_u - elev_u), max(0.0, wl_v - elev_v))

                    is_blocked = edge_data.get('blocked', False)
                    is_cleared = edge_data.get('rubble_cleared', False)
                    
                    v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR')
                    if is_blocked and v_type in ("HIGH_WATER_TRUCK", "HELICOPTER"):
                        # Heavy vehicles clear a navigable corridor through rubble/debris
                        edge_data['rubble_cleared'] = True
                        if world_state.belief.has_edge(u, v):
                            world_state.belief.edges[u, v]['rubble_cleared'] = True
                        is_cleared = True

                    p_danger_edge = (world_state.ground_truth.nodes[u].get('p_danger', 0.0) + world_state.ground_truth.nodes[v].get('p_danger', 0.0)) / 2.0
                    from backend.agents.fleet_config import get_effective_speed
                    eff_speed = get_effective_speed(v_type, agent.speed, water_level, is_blocked, disaster_type=self.disaster_type, p_danger=p_danger_edge, is_cleared=is_cleared)

                    
                    if eff_speed <= 0.0:
                        # Agent is blocked on the edge!
                        v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR')
                        cost_key = f'cost_{v_type}'
                        if v_type != "HELICOPTER" and not getattr(agent, 'comms_blackout', False):
                            if world_state.belief.has_edge(u, v):
                                world_state.belief.edges[u, v]['blocked'] = True
                                world_state.belief.edges[u, v]['confidence'] = 1.0
                                world_state.belief.edges[u, v][cost_key] = 1e9
                        
                        # Guard: max 3 reroute attempts per step per agent
                        reroute_attempts += 1
                        if reroute_attempts > 3:
                            target_n = agent.target_node
                            self._release_egl_lock(agent)
                            if target_n:
                                if self.egl:
                                    self.egl.on_agent_mission_complete(agent.id, target_n)
                                if agent.agent_type == "SCOUT" and gmm.is_cleared(target_n):
                                    gmm.clearance_ledger.discard(target_n)
                            agent.next_node = None
                            agent.progress_on_edge = 0.0
                            agent.route = []
                            agent.status = AgentStatus.IDLE
                            if not getattr(agent, '_logged_route_failure', False):
                                agent._logged_route_failure = True
                                self.route_failures += 1
                                self.route_failures_by_vehicle[v_type] = self.route_failures_by_vehicle.get(v_type, 0) + 1
                            break


                        # Try to reroute around blocked edge using active_view
                        rerouted = False
                        if getattr(agent, 'no_path_cooldown', 0) > 0:
                            agent.no_path_cooldown -= 1
                        elif agent.target_node and agent.target_node != agent.current_node and getattr(agent, '_reroute_attempts', 0) < 3:
                            agent._reroute_attempts = getattr(agent, '_reroute_attempts', 0) + 1
                            try:
                                active_view = nx.subgraph_view(world_state.belief, filter_edge=lambda x, y: world_state.belief.edges[x, y].get(cost_key, 1e9) < 1e9)
                                alt_path = nx.shortest_path(active_view, agent.current_node, agent.target_node, weight=cost_key)
                                if alt_path and len(alt_path) > 1:
                                    agent.route = alt_path[1:]
                                    agent.next_node = None
                                    agent.progress_on_edge = 0.0
                                    rerouted = True
                            except Exception as reroute_err:
                                agent.no_path_cooldown = 60  # Cooldown for 60 steps on path failure

                        if rerouted:
                            continue

                        if not rerouted:
                            target_n = agent.target_node
                            self._release_egl_lock(agent)
                            if target_n:
                                if self.egl:
                                    self.egl.on_agent_mission_complete(agent.id, target_n)
                                if agent.agent_type == "SCOUT" and gmm.is_cleared(target_n):
                                    gmm.clearance_ledger.discard(target_n)
                            agent.next_node = None
                            agent.progress_on_edge = 0.0
                            agent.route = []
                            agent.status = AgentStatus.IDLE
                            agent._reroute_attempts = 0
                            agent.stall_cooldown = 12
                            self.route_failures += 1
                            self.route_failures_by_vehicle[v_type] = self.route_failures_by_vehicle.get(v_type, 0) + 1
                            break
                    
                    # Traverse segment taking road class speed limits and fleet speed multiplier into account
                    road_factor = edge_data.get('speed_factor', 1.0)
                    congestion = edge_data.get('congestion_factor', 1.0)
                    effective_speed = eff_speed * road_factor
                    
                    # Apply traffic congestion penalty for land vehicles
                    if getattr(agent, 'vehicle_type', 'STANDARD_CAR') != "HELICOPTER":
                        effective_speed = effective_speed / max(1.0, congestion)
                        
                    if distance <= 0.0:
                        time_to_cross = 0.0
                    else:
                        time_to_cross = (distance * (1.0 - agent.progress_on_edge)) / max(1e-3, effective_speed)
                        
                    if leftover_time >= time_to_cross:
                        leftover_time -= time_to_cross
                        agent.current_node = agent.next_node
                        world_state.belief.nodes[agent.current_node]['visited_at_least_once'] = True
                        if not hasattr(agent, 'history_route'):
                            agent.history_route = []
                        agent.history_route.append(agent.current_node)
                        agent.next_node = None
                        agent.progress_on_edge = 0.0
                        
                        # Update BeliefGraph to reflect this road is clear
                        if not getattr(agent, 'comms_blackout', False):
                            world_state.belief.edges[u, v]['blocked'] = False
                            world_state.belief.edges[u, v]['confidence'] = 1.0
                            world_state.belief.edges[u, v]['cleared'] = True
                        
                        if agent.current_node == agent.target_node:
                            self._reached_target(agent)
                    else:
                        agent.progress_on_edge = min(1.0, agent.progress_on_edge + (effective_speed * leftover_time) / distance)
                        leftover_time = 0.0
                        
            elif agent.status == AgentStatus.OBSERVING:
                agent.action_timer -= 1
                if agent.action_timer <= 0:
                    # Complete observation
                    if agent.comms_blackout:
                        agent.pending_observations.append(agent.current_node)
                        self.add_event(f"[{self.simulation_time}m] 📡 {agent.id} completed scan of {agent.current_node} but telemetry transmission failed (No Comms).")
                    else:
                        sensor = "DRONE_CAMERA" if getattr(agent, 'vehicle_type', 'STANDARD_CAR') == "HELICOPTER" else "HUMAN_VISUAL"
                        apply_scout_observation(
                            world_state.belief, 
                            world_state.ground_truth, 
                            agent.current_node,
                            sensor_type=sensor,
                            wind_speed_kmh=self.weather.get('windspeed', 0.0) if self.weather else 0.0,
                            smoke_present=self.weather.get('smoke', False) if self.weather else False
                        )
                        world_state.belief.nodes[agent.current_node]['visited_at_least_once'] = True
                    
                    target_node = agent.target_node
                    self._release_egl_lock(agent)
                    agent.status = AgentStatus.IDLE
                    agent.target_node = None
                    agent.is_manual_override = False
                    from backend.agents.fleet_config import FLEET_SPECIFICATIONS
                    v_type = getattr(agent, "vehicle_type", "STANDARD_CAR")
                    cap = FLEET_SPECIFICATIONS.get(v_type, {}).get("capacity", 50)
                    if self.egl:
                        self.egl.on_agent_mission_complete(agent.id, target_node, cap)

                    
            elif agent.status == AgentStatus.RESCUING:
                agent.action_timer -= 1
                if agent.action_timer <= 0:
                    # Complete rescue operation with triage priority
                    gt_node = world_state.ground_truth.nodes[agent.current_node]
                    gt_pop = gt_node.get('population', 0)
                    rescued = min(agent.capacity, gt_pop)
                    
                    # Prioritize loading (Immediate > Delayed > Minor)
                    imm = gt_node.get('triage_immediate', 0) or 0
                    del_ = gt_node.get('triage_delayed', 0) or 0
                    min_ = gt_node.get('triage_minor', 0) or 0
                    
                    rescued_imm = min(rescued, imm)
                    rescued_del = min(rescued - rescued_imm, del_)
                    rescued_min = min(rescued - rescued_imm - rescued_del, min_)
                    
                    # Ensure sum matches total rescued
                    rem = rescued - (rescued_imm + rescued_del + rescued_min)
                    if rem > 0:
                        rescued_min += rem
                        
                    gt_node['triage_immediate'] = max(0, imm - rescued_imm)
                    gt_node['triage_delayed'] = max(0, del_ - rescued_del)
                    gt_node['triage_minor'] = max(0, min_ - rescued_min)
                    gt_node['population'] = gt_pop - rescued
                    
                    world_state.belief.nodes[agent.current_node]['population'] = gt_node['population']
                    world_state.belief.nodes[agent.current_node]['triage_immediate'] = gt_node['triage_immediate']
                    world_state.belief.nodes[agent.current_node]['triage_delayed'] = gt_node['triage_delayed']
                    world_state.belief.nodes[agent.current_node]['triage_minor'] = gt_node['triage_minor']
                    
                    agent.survivors_onboard = rescued
                    agent.survivors_immediate = rescued_imm
                    agent.survivors_delayed = rescued_del
                    agent.survivors_minor = rescued_min
                    agent.status = AgentStatus.RETURNING
                    
                    needs_medical = rescued_imm > 0
                    
                    # Coordinate return to nearest safe haven (prioritize hospitals if medical help is needed)
                    haven_path = self.coordinator.find_nearest_safe_haven(
                        world_state.belief, 
                        agent.current_node, 
                        needs_medical=needs_medical, 
                        vehicle_type=getattr(agent, 'vehicle_type', 'STANDARD_CAR')
                    )
                    if haven_path:
                        # Pop the first element since it's the current node
                        if haven_path[0] == agent.current_node:
                            haven_path.pop(0)
                        if haven_path:
                            agent.route = haven_path
                            agent.full_planned_route = [agent.current_node] + haven_path  # evacuation corridor
                            agent.target_node = haven_path[-1]
                            agent.status = AgentStatus.MOVING
                            agent.next_node = None
                            agent.progress_on_edge = 0.0
                        else:
                            # Already at haven
                            self._release_egl_lock(agent)
                            agent.status = AgentStatus.IDLE
                            agent.target_node = None
                    else:
                        # Stalled due to no path
                        self._release_egl_lock(agent)
                        agent.status = AgentStatus.IDLE
                        agent.target_node = None

        # --- OPPORTUNISTIC PASSIVE VERIFICATION (50m Sensor Sweep) ---
        try:
            for agent in self.agents.values():
                curr_node = agent.current_node
                if not curr_node or curr_node not in world_state.ground_truth:
                    continue
                node_data = world_state.ground_truth.nodes[curr_node]
                agent_lat = node_data.get('lat')
                agent_lon = node_data.get('lon')
                if agent_lat is None or agent_lon is None:
                    continue
                
                # Check adjacent and neighboring edges within range (avoiding full O(E) graph scan)
                checked_edges = set()
                candidate_edges = []
                for node in [curr_node] + list(world_state.ground_truth.neighbors(curr_node)):
                    for neighbor in world_state.ground_truth.neighbors(node):
                        edge_key = tuple(sorted([node, neighbor]))
                        if edge_key not in checked_edges:
                            checked_edges.add(edge_key)
                            d = world_state.ground_truth.edges[node, neighbor]
                            candidate_edges.append((node, neighbor, d))
                            
                for u, v, d in candidate_edges:
                    u_node = world_state.ground_truth.nodes[u]
                    v_node = world_state.ground_truth.nodes[v]
                    
                    edge_lat = (u_node.get('lat', 0.0) + v_node.get('lat', 0.0)) / 2.0
                    edge_lon = (u_node.get('lon', 0.0) + v_node.get('lon', 0.0)) / 2.0
                    
                    lat_diff = edge_lat - agent_lat
                    lon_diff = edge_lon - agent_lon
                    dist_deg = math.hypot(lat_diff, lon_diff)
                    
                    if dist_deg <= 0.0006:
                        gt_blocked = d.get('blocked', False)
                        if not getattr(agent, 'comms_blackout', False):
                            if world_state.belief.edges[u, v]['blocked'] != gt_blocked:
                                world_state.belief.edges[u, v]['blocked'] = gt_blocked
                                world_state.belief.edges[u, v]['confidence'] = 1.0
                                status_str = "CLOSED/BLOCKED" if gt_blocked else "OPEN/CLEAR"
                                self.add_event(f"[{self.simulation_time}m] 👁️ {agent.id} verified adjacent segment {u} ↔ {v} is {status_str}.")
        except Exception as ex:
            print(f"[Sensor Sweep] Error during passive sweep: {ex}")

        t_sim_end = time.perf_counter()
        self.last_telemetry["routing_ms"] = (t_sim_end - t_sim_start) * 1000

        # Capture metrics history
        self._record_metrics()

        # Phase 2: Check strategic decision triggers
        current_blocked_count = sum(1 for uu, vv, d in world_state.ground_truth.edges(data=True) if d.get('blocked', False))
        blockage_surge = (self.simulation_time > 1) and (current_blocked_count - self.last_blocked_count > 3)
        self.last_blocked_count = current_blocked_count
        
        low_supply_haven = None
        for n, data in world_state.ground_truth.nodes(data=True):
            if data.get('node_type') in ("SHELTER", "HOSPITAL") and n not in self.triggered_havens:
                res = data.get('resources', {})
                if res.get('food', 100) < 20 or res.get('water', 100) < 20:
                    low_supply_haven = n
                    self.triggered_havens.add(n)
                    break
        
        if (self.simulation_time == 5) or low_supply_haven or blockage_surge:
            if self.env_mode not in ("BENCHMARK", "HISTORICAL") and not getattr(self, "auto_resolve_overrides", False):
                self.paused_for_decision = True
            
            trigger_reason = ""
            if self.simulation_time == 5:
                trigger_reason = f"Environmental intensity surge at {self.simulation_time}m."
            elif low_supply_haven:
                haven_name = world_state.get_node_human_name(low_supply_haven)
                trigger_reason = f"Haven '{haven_name}' running critically low on supplies."
            elif blockage_surge:
                trigger_reason = f"Sudden cascade blockage event detected on the network."
                
            self.active_decision = {
                "step": self.simulation_time,
                "reason": trigger_reason,
                "options": [
                    {
                        "id": "A",
                        "title": "Establish Safe Routing Corridors",
                        "description": "Increase route safety factors, directing rescue vehicles to bypass high-danger zones even if detours are longer."
                    },
                    {
                        "id": "B",
                        "title": "Air Bridge Cargo Deployment",
                        "description": "Coordinate immediate emergency drone/helicopter supply drops to replenish low havens."
                    },
                    {
                        "id": "C",
                        "title": "Tactical Scout & Clear Protocol",
                        "description": "Equip and direct ground crews to perform aggressive clearing, reducing movement penalties on blocked roads by 50%."
                    }
                ]
            }
            self.add_event(f"[{self.simulation_time}m] 🚨 STRATEGIC TRIGGER: {trigger_reason} Simulation paused for Command decision.")

    def _reached_target(self, agent):
        staging_node = getattr(agent, 'staging_node', None)
        if staging_node and agent.current_node == staging_node:
            # Reached intermediate EGL staging node.
            # Transition to IDLE so the coordinator can re-evaluate and assign continuation route.
            agent.status = AgentStatus.IDLE
            agent.target_node = None
            return

        if agent.agent_type == "SCOUT":
            agent.status = AgentStatus.OBSERVING
            agent.action_timer = 1  # 1 step (1 minute) observing
        elif agent.agent_type == "RESCUE":
            haven_id = agent.current_node
            base_node = self.coordinator.base_node if self.coordinator else None
            is_safe_haven = world_state.ground_truth.nodes[haven_id].get('node_type') in ("SHELTER", "HOSPITAL") or (haven_id == base_node)
            
            if is_safe_haven and agent.target_node == haven_id:
                # Reached base/haven - offload survivors
                
                if 'occupants' not in world_state.ground_truth.nodes[haven_id]:
                    world_state.ground_truth.nodes[haven_id]['occupants'] = 0
                if 'occupants' not in world_state.belief.nodes[haven_id]:
                    world_state.belief.nodes[haven_id]['occupants'] = 0
                    
                world_state.ground_truth.nodes[haven_id]['occupants'] += agent.survivors_onboard
                world_state.belief.nodes[haven_id]['occupants'] += agent.survivors_onboard
                
                self.total_survivors_saved += agent.survivors_onboard
                self.rescued_immediate += getattr(agent, 'survivors_immediate', 0)
                self.rescued_delayed += getattr(agent, 'survivors_delayed', 0)
                self.rescued_minor += getattr(agent, 'survivors_minor', 0)
                self.triage_ev_accumulated += (
                    getattr(agent, 'survivors_immediate', 0) * 3.0 +
                    getattr(agent, 'survivors_delayed', 0) * 2.0 +
                    getattr(agent, 'survivors_minor', 0) * 1.2
                )
                self.rescue_trips_completed += 1
                p_zone = world_state.ground_truth.nodes[haven_id].get('p_danger', 0.0)
                triage_msg = ""
                if agent.survivors_immediate > 0:
                    triage_msg = " (Critical condition)" if p_zone > 0.8 else ""
                self.add_xai_event(
                    action=f"{agent.id} delivered {agent.survivors_onboard} survivors to haven {haven_id}.",
                    reason=f"Risk level was High. Triage successful." if p_zone > 0.8 else f"Grid sweep evacuation standard procedure."
                )
                
                target_node = agent.target_node
                self._release_egl_lock(agent)
                agent.survivors_onboard = 0
                agent.survivors_immediate = 0
                agent.survivors_delayed = 0
                agent.survivors_minor = 0
                agent.status = AgentStatus.IDLE
                agent.target_node = None
                agent.is_manual_override = False
                if self.egl:
                    self.egl.on_agent_mission_complete(agent.id, target_node)

            else:
                # Reached target population zone
                agent.status = AgentStatus.RESCUING
                agent.staging_node = None
                agent.staged_dispatch_target = None
                v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR')

                if v_type == "HELICOPTER":
                    agent.action_timer = 8   # 8 min loading for helicopter (balanced)
                elif v_type == "ZODIAC_BOAT":
                    agent.action_timer = 8   # 8 min loading for boat
                elif v_type == "HIGH_WATER_TRUCK":
                    agent.action_timer = 10  # 10 min loading for truck
                else:
                    agent.action_timer = 5   # 5 min for standard car

    def _release_egl_lock(self, agent) -> None:
        locked_target = getattr(agent, 'egl_locked_target', None)
        if locked_target:
            if self.active_baseline == "AMIS-RU" and self.egl:
                self.egl.fcm.release_target(locked_target)

            
            if agent.agent_type == "RESCUE":
                v_type = getattr(agent, 'vehicle_type', 'STANDARD_CAR')
                from backend.agents.fleet_config import FLEET_SPECIFICATIONS
                spec = FLEET_SPECIFICATIONS.get(v_type, {})
                vehicle_cap = spec.get("capacity", 50)
                gmm.free_capacity(locked_target, vehicle_cap)
                
            agent.egl_locked_target = None

    def _record_metrics(self):
        # Calculate coverage (verified nodes fraction) based on actually visited nodes
        num_nodes = len(world_state.belief.nodes)
        verified_nodes = sum(
            1 for n, d in world_state.belief.nodes(data=True)
            if d.get('visited_at_least_once', False)
        )
        coverage = verified_nodes / num_nodes if num_nodes > 0 else 0.0
        
        # Calculate map confidence (average confidence)
        total_conf = sum(
            d.get('p_state_correct', 1.0)
            for n, d in world_state.belief.nodes(data=True)
        )
        map_confidence = total_conf / num_nodes if num_nodes > 0 else 1.0
        
        self.history.append({
            "step": self.simulation_time,
            "survivors_saved": self.total_survivors_saved,
            "civilian_evacuated_reactive":    self.civilian_evacuated_reactive,
            "civilian_evacuated_preemptive":  self.civilian_evacuated_preemptive,
            "haven_overflow_events":          self.haven_overflow_events,
            "route_failure_during_evac":      self.route_failure_during_evac,
            "zones_unreachable_at_trigger":   self.zones_unreachable_at_trigger,
            "broadcast_trigger_step":         self.broadcast_trigger_step,
            "rescue_vehicle_saves":           self.total_survivors_saved - self.civilian_evacuated_reactive - self.civilian_evacuated_preemptive,
            "coverage": coverage,
            "map_confidence": map_confidence,
            "initial_population": self.initial_total_population
        })

    def replenish_supplies(self, node_id: str, amount: float = 50.0):
        if not world_state.ground_truth.nodes:
            return False
            
        gt_node = world_state.ground_truth.nodes.get(node_id)
        belief_node = world_state.belief.nodes.get(node_id)
        
        if not gt_node or not belief_node:
            return False
            
        node_type = gt_node.get('node_type', '')
        if node_type not in ["HOSPITAL", "SHELTER"]:
            return False
            
        # Add resources up to a max of 200%
        if 'resources' in gt_node:
            gt_node['resources']['food'] = min(200.0, gt_node['resources']['food'] + amount)
            gt_node['resources']['water'] = min(200.0, gt_node['resources']['water'] + amount)
            gt_node['warned_food'] = False
            
        if 'resources' in belief_node:
            belief_node['resources']['food'] = min(200.0, belief_node['resources']['food'] + amount)
            belief_node['resources']['water'] = min(200.0, belief_node['resources']['water'] + amount)
            belief_node['warned_food'] = False
            
        self.add_event(f"[{self.simulation_time}m] 🛩️ Emergency Supply Drop (+{amount}) delivered to {node_id}.")
        return True

simulation_engine = SimulationEngine()
