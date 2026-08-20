import threading
import numpy as np
import networkx as nx  # type: ignore
from scipy.sparse import csr_matrix as scipy_csr_matrix  # type: ignore
from scipy.sparse.csgraph import shortest_path as scipy_shortest_path  # type: ignore
from typing import Any, Dict, List, Set, Tuple, Optional

# Hardware-Level GPU Acceleration (CuPy / CUDA)
try:
    import cupy as cp  # type: ignore
    from cupyx.scipy.sparse import csr_matrix as cupy_csr_matrix  # type: ignore
    from cupyx.scipy.sparse.csgraph import shortest_path as cupy_shortest_path  # type: ignore
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False
    cp = np  # type: ignore

class GlobalMemoryMatrix:
    """
    A persistent, indestructible singleton memory structure.
    Consolidates the entire city infrastructure, demographics, weather, and mission logic
    so no data is lost or fragmented between modules.
    """
    _instance: Optional["GlobalMemoryMatrix"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "GlobalMemoryMatrix":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(GlobalMemoryMatrix, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self) -> None:
        # 1. Clearance Ledger (History of visited/cleared nodes)
        self.clearance_ledger: Set[str] = set()
        
        # 2. Demographics Matrix (Inbound capacities and Swarm tracking)
        self.inbound_capacity: Dict[str, int] = {}
        
        # 3. Priority Queue History (Historical danger probabilities)
        self.danger_history: Dict[str, float] = {}
        
        # 4. Weather Chronicle (API logs over time)
        self.weather_chronicle: List[Dict[str, Any]] = []

        # 5. Infrastructure Anomalies (e.g. dynamic blockages)
        self.infrastructure_anomalies: Set[str] = set()
        
        # 6. Vectorized Tensor Matrices
        self.adjacency_matrices: Dict[str, Any] = {}
        self.node_list: List[str] = []
        self.node_index_map: Dict[str, int] = {}

    def force_wake_gpu(self, belief_graph: Any) -> bool:
        """Physically pings the GPU driver to wake it up from sleep states, then recompiles the map to VRAM."""
        global GPU_AVAILABLE, cp, cupy_csr_matrix, cupy_shortest_path
        try:
            import cupy as cp  # type: ignore
            from cupyx.scipy.sparse import csr_matrix as cupy_csr_matrix  # type: ignore
            from cupyx.scipy.sparse.csgraph import shortest_path as cupy_shortest_path  # type: ignore
            
            # Mathematical ignition ping to force CUDA context initialization
            _ = cp.zeros(1)
            
            GPU_AVAILABLE = True
            
            # Recompile matrix immediately onto the VRAM
            if belief_graph and len(belief_graph.nodes) > 0:
                self.compile_graph_to_tensor(belief_graph)
                
            return True
        except Exception as e:
            print(f"GPU Ignition Failed: {e}")
            GPU_AVAILABLE = False
            return False

    def compile_graph_to_tensor(self, belief_graph: Any) -> None:
        """Converts the NetworkX graph into vectorized Sparse Adjacency Matrices for all vehicle types."""
        self.node_list = list(belief_graph.nodes())
        self.node_index_map = {n: i for i, n in enumerate(self.node_list)}
        
        # Build scipy sparse matrices for each vehicle type
        self.adjacency_matrices = {}
        for vehicle_type in ['STANDARD_CAR', 'ZODIAC_BOAT', 'HIGH_WATER_TRUCK', 'HELICOPTER', 'SCOUT_CAR']:
            weight_key: str = f'cost_{vehicle_type}'
            row: List[int] = []
            col: List[int] = []
            data: List[float] = []
            for u, v, d in belief_graph.edges(data=True):
                w: float = float(d.get(weight_key, 999999.0))
                u_idx: int = self.node_index_map[u]
                v_idx: int = self.node_index_map[v]
                row.extend([u_idx, v_idx])
                col.extend([v_idx, u_idx])
                data.extend([w, w])
            
            n: int = len(self.node_list)
            
            if GPU_AVAILABLE:
                # Push Matrix to GPU VRAM
                try:
                    self.adjacency_matrices[vehicle_type] = cupy_csr_matrix((cp.array(data), (cp.array(row), cp.array(col))), shape=(n, n))
                except Exception:
                    self.adjacency_matrices[vehicle_type] = scipy_csr_matrix((data, (row, col)), shape=(n, n))
            else:
                # Fallback to High-Speed CPU C-Arrays
                self.adjacency_matrices[vehicle_type] = scipy_csr_matrix((data, (row, col)), shape=(n, n))

    def calculate_distance_matrix(self, vehicle_type: str, source_node_ids: List[str]) -> Tuple[Optional[Any], Optional[Any]]:
        """Returns a dense 2D numpy/cupy array [sources_count, nodes_count] with shortest path distances"""
        if vehicle_type not in self.adjacency_matrices:
            return None, None
            
        source_indices: List[int] = [self.node_index_map[n] for n in source_node_ids if n in self.node_index_map]
        if not source_indices:
            return None, None
            
        if GPU_AVAILABLE and not isinstance(self.adjacency_matrices[vehicle_type], scipy_csr_matrix):
            # Execute on NVIDIA GPU Core
            dist_matrix: Any
            predecessors: Any
            dist_matrix, predecessors = cupy_shortest_path(
                csgraph=self.adjacency_matrices[vehicle_type], 
                directed=False, 
                indices=cp.array(source_indices), 
                return_predecessors=True
            )
            # Transfer tensor back from VRAM to standard RAM for logic operations
            return cp.asnumpy(dist_matrix), cp.asnumpy(predecessors)
        else:
            # Execute on standard CPU
            dist_matrix_cpu: Any
            predecessors_cpu: Any
            dist_matrix_cpu, predecessors_cpu = scipy_shortest_path(
                csgraph=self.adjacency_matrices[vehicle_type], 
                directed=False, 
                indices=source_indices, 
                return_predecessors=True
            )
            return dist_matrix_cpu, predecessors_cpu

    def log_clearance(self, node_id: str) -> None:
        with self._lock:
            self.clearance_ledger.add(node_id)

    def is_cleared(self, node_id: str) -> bool:
        with self._lock:
            return node_id in self.clearance_ledger

    def allocate_capacity(self, target_id: str, capacity: int) -> None:
        with self._lock:
            self.inbound_capacity[target_id] = self.inbound_capacity.get(target_id, 0) + capacity

    def get_remaining_demand(self, target_id: str, population: int) -> int:
        with self._lock:
            return max(0, population - self.inbound_capacity.get(target_id, 0))

    def free_capacity(self, target_id: str, capacity: int) -> None:
        with self._lock:
            if target_id in self.inbound_capacity:
                self.inbound_capacity[target_id] = max(0, self.inbound_capacity[target_id] - capacity)

    def log_weather(self, weather_data: Dict[str, Any]) -> None:
        if weather_data:
            with self._lock:
                self.weather_chronicle.append(weather_data)

    def reset_matrix(self) -> None:
        """Purges memory for a fresh map load"""
        with self._lock:
            self._initialize()

# Singleton instance
gmm: GlobalMemoryMatrix = GlobalMemoryMatrix()
