import numpy as np
import hashlib
import networkx as nx

NODE_TYPE_MAP = {
    "ROAD": 0,
    "BRIDGE": 1,
    "HOSPITAL": 2,
    "SHELTER": 3,
    "POPULATION_ZONE": 4,
    "JUNCTION": 5,
    "DEPOT": 6
}

STATUS_MAP = {
    "SAFE": 0,
    "DANGER": 1,
    "COMPROMISED": 2,
    "FLOODED": 3
}

class NodeStateTensor:
    """Dynamic Node-State Tensor (DNST) for high-performance vectorized operations.
    Keeps track of node properties in aligned NumPy memory layouts.
    """
    def __init__(self, num_nodes: int):
        self.num_nodes = num_nodes
        
        # Aligned memory layouts
        self.node_ids = np.zeros(num_nodes, dtype=np.int32)
        self.lat = np.zeros(num_nodes, dtype=np.float32)
        self.lon = np.zeros(num_nodes, dtype=np.float32)
        self.population = np.zeros(num_nodes, dtype=np.int32)
        
        # triage shape: (num_nodes, 3) -> col 0: immediate, col 1: delayed, col 2: minor
        self.triage = np.zeros((num_nodes, 3), dtype=np.int32)
        self.p_danger = np.zeros(num_nodes, dtype=np.float32)
        self.p_state_correct = np.ones(num_nodes, dtype=np.float32)
        
        self.node_type_mask = np.zeros(num_nodes, dtype=np.uint8)
        self.status_mask = np.zeros(num_nodes, dtype=np.uint8)
        self.comm_coverage = np.ones(num_nodes, dtype=np.float32)
        self.observation_age = np.zeros(num_nodes, dtype=np.float32)
        
        # Dynamic flow index lookup mappings
        self.node_index_map = {}
        
    def sync_from_graph(self, graph: nx.Graph) -> None:
        """Populate the tensors from NetworkX graph properties."""
        self.node_index_map.clear()
        
        num_graph_nodes = len(graph.nodes)
        if num_graph_nodes > self.num_nodes:
            # Dynamically resize arrays if graph exceeds capacity
            new_capacity = max(self.num_nodes * 2, num_graph_nodes + 100)
            self._resize(new_capacity)
            
        for idx, (n_id, data) in enumerate(graph.nodes(data=True)):
            self.node_index_map[n_id] = idx
            
            stable_hash = int(hashlib.md5(str(n_id).encode('utf-8')).hexdigest()[:8], 16)
            self.node_ids[idx] = stable_hash % 200000000
            
            self.lat[idx] = data.get('lat', data.get('y', 0.0))
            self.lon[idx] = data.get('lon', data.get('x', 0.0))
            self.population[idx] = data.get('population', 0) or 0
            
            self.triage[idx, 0] = data.get('triage_immediate', 0) or 0
            self.triage[idx, 1] = data.get('triage_delayed', 0) or 0
            self.triage[idx, 2] = data.get('triage_minor', 0) or 0
            
            self.p_danger[idx] = data.get('p_danger', 0.0) or 0.0
            self.p_state_correct[idx] = data.get('p_state_correct', 1.0)
            
            nt_str = data.get('node_type', 'ROAD')
            self.node_type_mask[idx] = NODE_TYPE_MAP.get(nt_str, 0)
            
            st_str = data.get('status', 'SAFE')
            self.status_mask[idx] = STATUS_MAP.get(st_str, 0)
            
            self.comm_coverage[idx] = data.get('comm_coverage', data.get('connectivity', 1.0))
            self.observation_age[idx] = data.get('observation_age', 0.0)

    def update_node(
        self,
        node_id: str,
        status: str,
        p_danger: float,
        triage_immediate: int = 0,
        triage_delayed: int = 0,
        triage_minor: int = 0,
        p_state_correct: float = 1.0
    ) -> None:
        idx = self.node_index_map.get(node_id)
        if idx is not None:
            self.status_mask[idx] = STATUS_MAP.get(status, 0)
            self.p_danger[idx] = p_danger
            self.triage[idx, 0] = triage_immediate
            self.triage[idx, 1] = triage_delayed
            self.triage[idx, 2] = triage_minor
            self.p_state_correct[idx] = p_state_correct

    def _resize(self, new_capacity: int) -> None:
        """Resizes the tensor arrays to support larger networks."""
        self.num_nodes = new_capacity
        self.node_ids = np.resize(self.node_ids, new_capacity)
        self.lat = np.resize(self.lat, new_capacity)
        self.lon = np.resize(self.lon, new_capacity)
        self.population = np.resize(self.population, new_capacity)
        
        old_triage = self.triage
        self.triage = np.zeros((new_capacity, 3), dtype=np.int32)
        self.triage[:len(old_triage)] = old_triage
        
        self.p_danger = np.resize(self.p_danger, new_capacity)
        self.p_state_correct = np.resize(self.p_state_correct, new_capacity)
        self.node_type_mask = np.resize(self.node_type_mask, new_capacity)
        self.status_mask = np.resize(self.status_mask, new_capacity)
        self.comm_coverage = np.resize(self.comm_coverage, new_capacity)
        self.observation_age = np.resize(self.observation_age, new_capacity)
