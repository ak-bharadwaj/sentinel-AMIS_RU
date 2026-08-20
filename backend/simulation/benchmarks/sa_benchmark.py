import time
import numpy as np
import networkx as nx

# 1. Setup a mock NetworkX graph representing 2000 nodes and 6000 edges
print("Generating mock urban network for Situation Assessment...")
num_nodes = 2000
num_edges = 6000

g = nx.Graph()
for i in range(num_nodes):
    node_type = "ROAD"
    if i % 20 == 0: node_type = "HOSPITAL"
    elif i % 15 == 0: node_type = "SHELTER"
    elif i % 10 == 0: node_type = "DEPOT"
    elif i % 2 == 0: node_type = "POPULATION_ZONE"
    
    g.add_node(
        f"node_{i}",
        node_type=node_type,
        status="SAFE" if i % 7 != 0 else "COMPROMISED",
        population=100 if node_type == "POPULATION_ZONE" else 0,
        p_danger=0.1 + (i % 5) * 0.15,
        triage_immediate=1 if i % 13 == 0 else 0,
        triage_delayed=2 if i % 17 == 0 else 0,
        triage_minor=3 if i % 19 == 0 else 0,
        confidence=0.85,
        comm_coverage=0.9
    )

for i in range(num_edges):
    u = f"node_{i % num_nodes}"
    v = f"node_{(i * 3 + 1) % num_nodes}"
    g.add_edge(u, v, blocked=(i % 11 == 0), confidence=0.9)

# 2. Original Loop-based Implementation
def original_assessment(graph):
    total_nodes = len(graph.nodes)
    total_edges = len(graph.edges)
    
    blocked_edges = 0
    for u, v, data in graph.edges(data=True):
        if data.get("blocked", False):
            blocked_edges += 1
            
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

    for n_id, data in graph.nodes(data=True):
        node_type = data.get("node_type", "ROAD")
        status = data.get("status", "SAFE")
        pop = data.get("population", 0) or 0
        p_danger = data.get("p_danger", 0.0) or 0.0

        danger_sum += p_danger
        total_population += pop
        if status in ("DANGER", "COMPROMISED", "FLOODED") or p_danger > 0.5:
            affected_population += pop

        total_immediate += data.get("triage_immediate", 0) or 0
        total_delayed += data.get("triage_delayed", 0) or 0
        total_minor += data.get("triage_minor", 0) or 0

        if node_type == "HOSPITAL":
            total_hospitals += 1
            if status == "COMPROMISED":
                compromised_hospitals += 1
        elif node_type == "SHELTER":
            total_shelters += 1
            if status in ("COMPROMISED", "FLOODED"):
                compromised_shelters += 1
                
    return {
        "severity": (danger_sum / total_nodes) + (blocked_edges / total_edges),
        "medical": total_immediate * 2 + total_delayed
    }

# 3. Vectorized NumPy Implementation
def vectorized_assessment(graph):
    total_nodes = len(graph.nodes)
    total_edges = len(graph.edges)
    
    # Vectorized edge checks
    blocked_edges = sum(1 for _, _, d in graph.edges(data=True) if d.get("blocked", False)) # Fast list comp/generator
    
    # Pre-extract properties into NumPy arrays
    nodes_data = list(graph.nodes(data=True))
    
    # Direct fast attributes extraction
    pops = np.fromiter((d.get("population", 0) or 0 for _, d in nodes_data), dtype=np.int32)
    dangers = np.fromiter((d.get("p_danger", 0.0) or 0.0 for _, d in nodes_data), dtype=np.float32)
    t_imm = np.fromiter((d.get("triage_immediate", 0) or 0 for _, d in nodes_data), dtype=np.int32)
    t_del = np.fromiter((d.get("triage_delayed", 0) or 0 for _, d in nodes_data), dtype=np.int32)
    
    # Compile status boolean masks
    statuses = [d.get("status", "SAFE") for _, d in nodes_data]
    status_mask = np.array([s in ("DANGER", "COMPROMISED", "FLOODED") for s in statuses], dtype=bool)
    danger_mask = dangers > 0.5
    affected_mask = status_mask | danger_mask
    
    affected_population = np.sum(pops[affected_mask])
    total_population = np.sum(pops)
    danger_sum = np.sum(dangers)
    total_immediate = np.sum(t_imm)
    total_delayed = np.sum(t_del)
    
    return {
        "severity": (danger_sum / total_nodes) + (blocked_edges / total_edges),
        "medical": total_immediate * 2 + total_delayed
    }

# Run Benchmark
print("\nRunning benchmarks (100 iterations)...")
t_start = time.perf_counter()
for _ in range(100):
    res_orig = original_assessment(g)
t_end = time.perf_counter()
orig_time_ms = (t_end - t_start) * 1000.0

t_start = time.perf_counter()
for _ in range(100):
    res_vec = vectorized_assessment(g)
t_end = time.perf_counter()
vec_time_ms = (t_end - t_start) * 1000.0

print(f"Original Loop Time (100 runs): {orig_time_ms:.2f} ms (Avg: {orig_time_ms/100:.3f} ms/run)")
print(f"Vectorized NumPy Time (100 runs): {vec_time_ms:.2f} ms (Avg: {vec_time_ms/100:.3f} ms/run)")
print(f"Speedup Factor: {orig_time_ms / vec_time_ms:.2f}x")
