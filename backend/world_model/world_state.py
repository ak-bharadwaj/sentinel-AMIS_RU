import networkx as nx
import threading
from datetime import datetime, timezone
from functools import wraps

db_lock = threading.RLock()

from typing import Any, Callable, Dict, List, Optional, TypeVar, cast

F = TypeVar('F', bound=Callable[..., Any])

def lock_db(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with db_lock:
            return func(*args, **kwargs)
    return cast(F, wrapper)
from backend.world_model.graph_builder import build_synthetic_graph, load_osm_xml
from backend.world_model.node import NodeModel
from backend.world_model.edge import EdgeModel
from backend.database import SessionLocal, Base, engine

class CoWGraph(nx.Graph):
    """
    A Copy-on-Write subclass of nx.Graph.
    It delays deep copying of the graph data until a write/mutation is attempted.
    """
    def __init__(self, base_graph: nx.Graph):
        super().__init__()
        self._base = base_graph
        self._mutated = False
        # Share references initially to avoid copying overhead
        self.graph = base_graph.graph
        self._node = base_graph._node
        self._adj = base_graph._adj

    def _trigger_cow(self):
        if not self._mutated:
            # Shallow copy the dictionaries to isolate structure and attribute dicts
            self._node = {node: data.copy() for node, data in self._base._node.items()}
            self._adj = {u: {v: data.copy() for v, data in nbrs.items()} for u, nbrs in self._base._adj.items()}
            self.graph = self._base.graph.copy()
            self._mutated = True

    def add_node(self, node_for_adding, **attr):
        self._trigger_cow()
        super().add_node(node_for_adding, **attr)

    def add_nodes_from(self, nodes_for_adding, **attr):
        self._trigger_cow()
        super().add_nodes_from(nodes_for_adding, **attr)

    def remove_node(self, n):
        self._trigger_cow()
        super().remove_node(n)

    def remove_nodes_from(self, nodes):
        self._trigger_cow()
        super().remove_nodes_from(nodes)

    def add_edge(self, u_of_edge, v_of_edge, **attr):
        self._trigger_cow()
        super().add_edge(u_of_edge, v_of_edge, **attr)

    def add_edges_from(self, ebunch_to_add, **attr):
        self._trigger_cow()
        super().add_edges_from(ebunch_to_add, **attr)

    def remove_edge(self, u, v):
        self._trigger_cow()
        super().remove_edge(u, v)

    def remove_edges_from(self, ebunch):
        self._trigger_cow()
        super().remove_edges_from(ebunch)

    def clear(self):
        self._trigger_cow()
        super().clear()

    @property
    def nodes(self):
        self._trigger_cow()
        return super().nodes

    @property
    def edges(self):
        self._trigger_cow()
        return super().edges

    @property
    def adj(self):
        self._trigger_cow()
        return super().adj

    def copy(self, as_view=False):
        if as_view:
            return super().copy(as_view=True)
        self._trigger_cow()
        return nx.Graph(self)

class WorldState:
    ground_truth: Any
    belief: Any
    nodes_dict: Dict[Any, Any]
    edges_dict: Dict[Any, Any]
    map_mode: Optional[str]

    def __init__(self) -> None:
        self.ground_truth = nx.Graph()
        self.belief = nx.Graph()
        self.nodes_dict = {}  # id -> NodeModel
        self.edges_dict = {}  # id -> EdgeModel
        self.map_mode = None  # Caches "REAL" or "SYNTHETIC" mode of current graph
        self._spatial_tree = None
        self._spatial_nodes = []
        self._node_names_cache = {}

    def get_belief_snapshot(self) -> nx.Graph:
        """Returns a Copy-on-Write snapshot of the current belief graph."""
        return CoWGraph(self.belief)

    @lock_db
    def initialize(self, osm_path: Optional[str] = None, center_lat: float = 37.7749, center_lon: float = -122.4194, corruption_level: float = 0.6, lat_span: Optional[float] = None, lon_span: Optional[float] = None, force_rebuild: bool = False) -> None:
        """Initializes both graphs. Synchronizes initial state to database."""
        requested_mode = "REAL" if osm_path else "SYNTHETIC"
        # Check if the correct graph is already loaded in memory to perform a fast reset
        import math
        if len(self.ground_truth.nodes) > 0 and self.map_mode == requested_mode and not force_rebuild:
            # Simple check if center is roughly the same to avoid reloading unless requested
            nodes_data = [data for _, data in self.ground_truth.nodes(data=True)]
            if nodes_data:
                avg_lat = sum(d.get('y', d.get('lat', 0)) for d in nodes_data) / len(nodes_data)
                avg_lon = sum(d.get('x', d.get('lon', 0)) for d in nodes_data) / len(nodes_data)
                # Tightened from 0.05 to 0.001 to ensure accurate location selector response
                from backend.config_params.parameters import params
                threshold = getattr(params, 'location_reset_threshold_deg', 0.001)
                
                # Check if dimensions also match to avoid cache collisions
                dim_match = True
                if lat_span is not None and lon_span is not None:
                    lat_max = max(d.get('lat', 0) for d in nodes_data)
                    lat_min = min(d.get('lat', 0) for d in nodes_data)
                    lon_max = max(d.get('lon', 0) for d in nodes_data)
                    lon_min = min(d.get('lon', 0) for d in nodes_data)
                    curr_lat_span = (lat_max - lat_min) / 2.0
                    curr_lon_span = (lon_max - lon_min) / 2.0
                    if abs(curr_lat_span - lat_span) > 0.005 or abs(curr_lon_span - lon_span) > 0.005:
                        dim_match = False

                if math.hypot(avg_lat - center_lat, avg_lon - center_lon) < threshold and dim_match:
                    print(f"Using cached World Model (mode={self.map_mode}).")
                    from backend.simulation.corruption import corrupt_belief_graph
                    self.belief = corrupt_belief_graph(self.ground_truth, corruption_level)
                    self.fast_sync_to_db()
                    return


        db = SessionLocal()
        try:
            from backend.config_params.parameters import params
            # Clear in-memory graphs and dictionaries
            self.ground_truth.clear()
            self.belief.clear()
            self.nodes_dict.clear()
            self.edges_dict.clear()
            self._spatial_tree = None
            self._spatial_nodes = []
            self._node_names_cache = {}

            # 1. Clear database tables cleanly instead of expensive dropping of metadata
            Base.metadata.create_all(bind=engine)
            from sqlalchemy import text
            db.execute(text("DELETE FROM edges"))
            db.execute(text("DELETE FROM nodes"))
            db.commit()
            
            self.map_mode = requested_mode


            # 2. Build graph nodes/edges lists
            import os
            if osm_path and os.path.exists(osm_path):
                nodes, edges = load_osm_xml(osm_path)
            else:
                nodes, edges = build_synthetic_graph(center_lat=center_lat, center_lon=center_lon, lat_span=lat_span, lon_span=lon_span)


            # 3. Save to memory dictionaries and NetworkX graphs
            for node in nodes:
                is_coastal = getattr(node, "is_coastal", False)
                is_bridge = getattr(node, "is_bridge", False)
                self.nodes_dict[node.id] = node
                self.ground_truth.add_node(
                    node.id, 
                    node_type=node.node_type,
                    lat=node.lat,
                    lon=node.lon,
                    population=node.population,
                    importance=node.importance,
                    p_danger=node.p_danger,
                    p_state_correct=node.p_state_correct,
                    status=node.status,
                    is_coastal=is_coastal,
                    is_bridge=is_bridge,
                    capacity=getattr(node, 'capacity', 8000 if node.node_type == 'SHELTER' else (4000 if node.node_type == 'HOSPITAL' else 0)),
                    is_staging=getattr(node, 'is_staging', node.node_type in ('SHELTER', 'HOSPITAL')),
                    triage_immediate=getattr(node, 'triage_immediate', 0),
                    triage_delayed=getattr(node, 'triage_delayed', 0),
                    triage_minor=getattr(node, 'triage_minor', 0),
                    dist_to_water=getattr(node, 'dist_to_water', getattr(params, 'infinite_distance_m', 999999.0)),
                    dist_to_coast=getattr(node, 'dist_to_coast', getattr(params, 'infinite_distance_m', 999999.0)),
                    is_tall_building_zone=bool(getattr(node, 'is_tall_building_zone', 0)),
                    last_observed=getattr(node, 'last_observed', datetime.now(timezone.utc))
                )
                self.belief.add_node(
                    node.id, 
                    node_type=node.node_type,
                    lat=node.lat,
                    lon=node.lon,
                    population=node.population,
                    importance=node.importance,
                    p_danger=node.p_danger,
                    p_state_correct=node.p_state_correct,
                    status=node.status,
                    is_coastal=is_coastal,
                    is_bridge=is_bridge,
                    capacity=getattr(node, 'capacity', 8000 if node.node_type == 'SHELTER' else (4000 if node.node_type == 'HOSPITAL' else 0)),
                    is_staging=getattr(node, 'is_staging', node.node_type in ('SHELTER', 'HOSPITAL')),
                    triage_immediate=getattr(node, 'triage_immediate', 0),
                    triage_delayed=getattr(node, 'triage_delayed', 0),
                    triage_minor=getattr(node, 'triage_minor', 0),
                    dist_to_water=getattr(node, 'dist_to_water', getattr(params, 'infinite_distance_m', 999999.0)),
                    dist_to_coast=getattr(node, 'dist_to_coast', getattr(params, 'infinite_distance_m', 999999.0)),
                    is_tall_building_zone=bool(getattr(node, 'is_tall_building_zone', 0)),
                    last_observed=getattr(node, 'last_observed', datetime.now(timezone.utc))
                )

            for edge in edges:
                is_coastal = getattr(edge, "is_coastal", False)
                is_bridge = getattr(edge, "is_bridge", False)
                geometry = getattr(edge, "geometry", None)
                name = getattr(edge, "name", "Unnamed Road")
                self.edges_dict[edge.id] = edge
                self.ground_truth.add_edge(
                    edge.source, edge.target,
                    id=edge.id,
                    edge_source=edge.source,
                    distance=edge.distance,
                    confidence=edge.confidence,
                    blocked=edge.blocked,
                    speed_factor=edge.speed_factor,
                    is_coastal=is_coastal,
                    is_bridge=is_bridge,
                    name=name,
                    geometry=geometry
                )
                self.belief.add_edge(
                    edge.source, edge.target,
                    id=edge.id,
                    edge_source=edge.source,
                    distance=edge.distance,
                    confidence=edge.confidence,
                    blocked=edge.blocked,
                    speed_factor=edge.speed_factor,
                    is_coastal=is_coastal,
                    is_bridge=is_bridge,
                    name=name,
                    geometry=geometry
                )

            # 4. Terrain Intelligence — enrich ground_truth with terrain properties.
            #    Runs ONCE per region. Uses persistent terrain_cache (survives restarts).
            #    Never called during simulation steps.
            try:
                from backend.world_model.terrain import TerrainProcessor
                _terrain_processor = TerrainProcessor(force_refresh=False)
                _terrain_processor.enrich(self.ground_truth, osm_tags_map=None)
                # Propagate terrain attributes to belief graph before corruption
                for n_id, data in self.ground_truth.nodes(data=True):
                    if n_id in self.belief.nodes:
                        for attr in ("terrain_elevation", "structural_offset", "effective_elevation",
                                     "elevation", "slope", "aspect", "twi", "terrain_class",
                                     "vs30_terrain", "accessibility_score", "bridge_amplification",
                                     "drainage_accumulation_rate"):
                            if attr in data:
                                self.belief.nodes[n_id][attr] = data[attr]
                for u, v, data in self.ground_truth.edges(data=True):
                    if self.belief.has_edge(u, v):
                        for attr in ("elevation_offset", "effective_elevation", "is_tunnel"):
                            if attr in data:
                                self.belief.edges[u, v][attr] = data[attr]
                print("[WorldState] Terrain Intelligence enrichment complete.")
            except Exception as _terrain_exc:
                print(f"[WorldState] TerrainProcessor warning (non-fatal): {_terrain_exc}")

            # 5. Corrupt coordinator's belief graph in memory prior to DB save
            from backend.simulation.corruption import corrupt_belief_graph
            self.belief = corrupt_belief_graph(self.belief, corruption_level)

            # 5. Save the final belief states to database using high-performance raw SQL
            conn = db.connection()
            from sqlalchemy import text
            
            node_dicts = [
                {
                    "id": n_id,
                    "node_type": data.get("node_type", "ROAD"),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                    "population": data.get("population", 0),
                    "importance": data.get("importance", 0.2),
                    "p_danger": data.get("p_danger", 0.0),
                    "p_state_correct": data.get("p_state_correct", 1.0),
                    "status": data.get("status", "SAFE"),
                    "triage_immediate": data.get("triage_immediate", 0),
                    "triage_delayed": data.get("triage_delayed", 0),
                    "triage_minor": data.get("triage_minor", 0),
                    "dist_to_water": data.get("dist_to_water", 999999.0),
                    "dist_to_coast": data.get("dist_to_coast", 999999.0),
                    "is_tall_building_zone": int(data.get("is_tall_building_zone", False)),
                    "last_observed": datetime.now(timezone.utc)
                }
                for n_id, data in self.belief.nodes(data=True)
            ]
            import json
            edge_dicts = [
                {
                    "id": data.get("id"),
                    "source": u,
                    "target": v,
                    "distance": data.get("distance", 0.0),
                    "confidence": data.get("confidence", 1.0),
                    "blocked": data.get("blocked", False),
                    "speed_factor": data.get("speed_factor", 1.0),
                    "last_observed": datetime.now(timezone.utc),
                    "name": data.get("name", "Unnamed Road"),
                    "geometry": json.dumps(data.get("geometry")) if data.get("geometry") else None
                }
                for u, v, data in self.belief.edges(data=True)
            ]
            
            conn.execute(
                text("INSERT INTO nodes (id, node_type, lat, lon, population, triage_immediate, triage_delayed, triage_minor, importance, p_danger, p_state_correct, status, dist_to_water, dist_to_coast, is_tall_building_zone, last_observed) VALUES (:id, :node_type, :lat, :lon, :population, :triage_immediate, :triage_delayed, :triage_minor, :importance, :p_danger, :p_state_correct, :status, :dist_to_water, :dist_to_coast, :is_tall_building_zone, :last_observed)"),
                node_dicts
            )
            conn.execute(
                text("INSERT INTO edges (id, source, target, distance, confidence, blocked, speed_factor, last_observed, name, geometry) VALUES (:id, :source, :target, :distance, :confidence, :blocked, :speed_factor, :last_observed, :name, :geometry)"),
                edge_dicts
            )
            db.commit()
            
        finally:
            db.close()

    @lock_db
    def sync_to_db(self) -> None:
        """Saves current BeliefGraph state to the database for API/UI use."""
        db = SessionLocal()
        try:
            # Sync in bulk to avoid O(N) database queries
            node_dbs = {node.id: node for node in db.query(NodeModel).all()}
            edge_dbs = {edge.id: edge for edge in db.query(EdgeModel).all()}

            # Sync nodes
            for n_id in self.belief.nodes:
                node_data = self.belief.nodes[n_id]
                node_db = node_dbs.get(n_id)
                if node_db:
                    node_db.node_type = node_data.get('node_type', 'ROAD')
                    node_db.p_danger = node_data.get('p_danger', 0.0)
                    node_db.p_state_correct = node_data.get('p_state_correct', 1.0)
                    node_db.status = node_data.get('status', 'SAFE')
                    node_db.population = node_data.get('population', 0)
                    node_db.triage_immediate = node_data.get('triage_immediate', 0)
                    node_db.triage_delayed = node_data.get('triage_delayed', 0)
                    node_db.triage_minor = node_data.get('triage_minor', 0)
                    node_db.dist_to_water = node_data.get('dist_to_water', 999999.0)
                    node_db.dist_to_coast = node_data.get('dist_to_coast', 999999.0)
                    node_db.is_tall_building_zone = int(node_data.get('is_tall_building_zone', False))
            
            # Sync edges
            for u, v in self.belief.edges:
                edge_data = self.belief.edges[u, v]
                e_id = edge_data.get('id')
                if e_id:
                    edge_db = edge_dbs.get(e_id)
                    if edge_db:
                        edge_db.confidence = edge_data['confidence']
                        edge_db.blocked = edge_data['blocked']
            
            db.commit()
        finally:
            db.close()

    @lock_db
    def sync_nodes_to_db(self, node_ids: List[str]) -> None:
        """Syncs only the specified nodes to the database."""
        if not node_ids:
            return
        db = SessionLocal()
        try:
            for n_id in node_ids:
                if n_id in self.belief.nodes:
                    node_data = self.belief.nodes[n_id]
                    db.query(NodeModel).filter(NodeModel.id == n_id).update({
                        "node_type": node_data.get('node_type', 'ROAD'),
                        "p_danger": node_data.get('p_danger', 0.0),
                        "p_state_correct": node_data.get('p_state_correct', 1.0),
                        "status": node_data.get('status', 'SAFE'),
                        "population": node_data.get('population', 0),
                        "triage_immediate": node_data.get('triage_immediate', 0),
                        "triage_delayed": node_data.get('triage_delayed', 0),
                        "triage_minor": node_data.get('triage_minor', 0),
                        "dist_to_water": node_data.get('dist_to_water', 999999.0),
                        "dist_to_coast": node_data.get('dist_to_coast', 999999.0),
                        "is_tall_building_zone": int(node_data.get('is_tall_building_zone', False))
                    })
            db.commit()
        finally:
            db.close()

    @lock_db
    def get_nodes(self) -> List[Dict[str, Any]]:
        # Only return critical nodes to keep payload tiny and avoid map clutter
        return [
            {
                "id": n_id,
                **self.belief.nodes[n_id]
            }
            for n_id in self.belief.nodes
            if self.belief.nodes[n_id].get("node_type") not in ("ROAD", "JUNCTION")
        ]

    @lock_db
    def get_all_coordinates(self) -> Dict[Any, List[float]]:
        # Returns [lat, lon] mapping for all nodes in the graph
        return {
            n_id: [data.get("y", data.get("lat")), data.get("x", data.get("lon"))]
            for n_id, data in self.belief.nodes(data=True)
            if data.get("y", data.get("lat")) is not None
        }


    @lock_db
    def get_edges(self) -> List[Dict[str, Any]]:
        res = []
        for u, v in self.belief.edges:
            edge_data = self.belief.edges[u, v]
            res.append({
                "source": u,
                "target": v,
                "blocked": edge_data.get("blocked", False),
                "confidence": edge_data.get("confidence", 1.0),
                "geometry": edge_data.get("geometry"),
                "cleared": edge_data.get("cleared", False),
                "hvt": edge_data.get("hvt", False),
                "hvt_priority": edge_data.get("hvt_priority", 0),
                "name": edge_data.get("name", "Unnamed Road"),
                "is_bridge": edge_data.get("is_bridge", False),
                "is_coastal": edge_data.get("is_coastal", False)
            })
        return res

    def get_node_human_name(self, node_id: str) -> str:
        """Generates a human-readable name for a node based on adjacent street names."""
        if hasattr(self, '_node_names_cache') and node_id in self._node_names_cache:
            return self._node_names_cache[node_id]

        if node_id not in self.belief.nodes:
            return f"Node {node_id}"

        ndata = self.belief.nodes[node_id]
        node_type = ndata.get("node_type", "ROAD")
        if node_type == "HOSPITAL":
            return "Hospital"
        elif node_type == "SHELTER":
            return "Shelter / Safe Haven"

        # Collect unique named streets adjacent to this node
        street_names: set = set()
        for neighbor in self.belief.neighbors(node_id):
            edge_data = self.belief.edges[node_id, neighbor]
            st_name = edge_data.get("name", "Unnamed Road")
            if st_name and st_name != "Unnamed Road":
                street_names.add(st_name)

        if not street_names:
            lat = ndata.get("lat")
            lon = ndata.get("lon")
            if lat is not None and lon is not None:
                res = f"Junction ({lat:.4f}, {lon:.4f})"
            else:
                res = f"Junction {node_id}"
        else:
            sorted_names = sorted(list(street_names))
            if len(sorted_names) >= 2:
                res = f"{sorted_names[0]} & {sorted_names[1]} Junction"
            else:
                res = f"{sorted_names[0]} (Midsection)"

        if not hasattr(self, '_node_names_cache'):
            self._node_names_cache = {}
        self._node_names_cache[node_id] = res
        return res


    @lock_db
    def fast_sync_to_db(self) -> None:
        """Syncs only the critical nodes and edges back to the database to keep it extremely fast."""
        db = SessionLocal()
        try:
            critical_node_ids = {
                n_id for n_id in self.belief.nodes
                if self.belief.nodes[n_id].get("node_type") not in ("ROAD", "JUNCTION")
            }
            
            # Sync critical nodes
            for n_id in critical_node_ids:
                node_data = self.belief.nodes[n_id]
                db.query(NodeModel).filter(NodeModel.id == n_id).update({
                    "p_danger": node_data.get('p_danger', 0.0),
                    "p_state_correct": node_data.get('p_state_correct', 1.0),
                    "status": node_data.get('status', 'SAFE'),
                    "population": node_data.get('population', 0),
                    "triage_immediate": node_data.get('triage_immediate', 0),
                    "triage_delayed": node_data.get('triage_delayed', 0),
                    "triage_minor": node_data.get('triage_minor', 0)
                })
            
            # Sync critical edges
            for u, v in self.belief.edges:
                edge_data = self.belief.edges[u, v]
                if edge_data.get("blocked") or edge_data.get("confidence", 1.0) < 0.95:
                    e_id = edge_data.get("id")
                    if e_id:
                        db.query(EdgeModel).filter(EdgeModel.id == e_id).update({
                            "confidence": edge_data['confidence'],
                            "blocked": edge_data['blocked']
                        })
            db.commit()
        finally:
            db.close()

    @lock_db
    def get_nearest_node(self, lat: float, lon: float) -> Optional[Any]:
        """Find nearest node using spatial KD-tree (O(log V)) when scipy is available.
        Falls back to linear scan O(V) otherwise.
        """        # Lazy build spatial tree structure to avoid costly O(V) queries or O(V) reconstructions on every step
        if not hasattr(self, '_spatial_tree') or self._spatial_tree is None:
            try:
                import numpy as np
                from scipy.spatial import cKDTree  # type: ignore
                nodes_data = [(n_id, d) for n_id, d in self.belief.nodes(data=True)
                              if d.get('lat') is not None or d.get('y') is not None]
                if nodes_data:
                    coords = np.array([
                        (d.get('lat', d.get('y', 0.0)), d.get('lon', d.get('x', 0.0)))
                        for _, d in nodes_data
                    ])
                    self._spatial_tree = cKDTree(coords)
                    self._spatial_nodes = nodes_data
                else:
                    self._spatial_tree = None
                    self._spatial_nodes = []
            except (ImportError, Exception):
                self._spatial_tree = None
                self._spatial_nodes = []
        
        if hasattr(self, '_spatial_tree') and self._spatial_tree is not None:
            try:
                _, idx = self._spatial_tree.query([lat, lon])
                return self._spatial_nodes[idx][0]
            except Exception as spatial_err:
                print(f"[WorldState] Spatial tree query fallback to haversine: {spatial_err}")
                
        from backend.world_model.graph_builder import haversine_distance
        nodes_data = [(n_id, d) for n_id, d in self.belief.nodes(data=True)
                      if d.get('lat') is not None or d.get('y') is not None]
        if not nodes_data:
            return None
            
        best_id = None
        best_dist = float('inf')
        for node_id, node_data in nodes_data:
            n_lat = node_data.get('lat', node_data.get('y', 0.0))
            n_lon = node_data.get('lon', node_data.get('x', 0.0))
            d = haversine_distance(n_lat, n_lon, lat, lon)
            if d < best_dist:
                best_dist = d
                best_id = node_id
        return best_id


world_state = WorldState()
