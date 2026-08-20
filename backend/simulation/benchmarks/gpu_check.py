import ctypes
import os

print("=== Sentinel Hardware & Tensor Architecture Analysis ===")

# 1. Check nvcuda.dll status
print("\n[1] Checking CUDA GPU Driver via ctypes...")
try:
    # On Windows, nvcuda.dll is in System32
    cuda = ctypes.windll.LoadLibrary("nvcuda.dll")
    print("  - Successfully loaded nvcuda.dll via ctypes!")
    
    # Initialize CUDA driver
    # cuInit(unsigned int Flags)
    result = cuda.cuInit(0)
    if result == 0:
        print("  - cuInit(0) returned SUCCESS (000). RTX GPU driver is AWAKE!")
        
        # Get count of devices
        # cuDeviceGetCount(int *count)
        count = ctypes.c_int(0)
        cuda.cuDeviceGetCount(ctypes.byref(count))
        print(f"  - Number of CUDA-enabled GPUs: {count.value}")
        
        for i in range(count.value):
            device = ctypes.c_int(0)
            cuda.cuDeviceGet(ctypes.byref(device), i)
            
            # Get device name
            name_buf = ctypes.create_string_buffer(256)
            cuda.cuDeviceGetName(name_buf, 256, device)
            print(f"    * GPU Device {i}: {name_buf.value.decode('utf-8')}")
    else:
        print(f"  - cuInit(0) returned error code: {result}")
except Exception as e:
    print(f"  - CUDA DLL Loading / Initialization failed: {e}")

# 2. Detailed Tensor vs CPU Operations list in current system
print("\n[2] Sentinel Calculation Pipeline: CPU vs Tensor Mapping")

mapping = {
    "Bayesian Belief propagation": {
        "Storage": "RAM (NetworkX Graph Structure)",
        "Computing Unit": "CPU (Single-threaded recursive updates in Python)",
        "Impact": "Dynamic probabilities update sequentially based on sensor reports."
    },
    "Dynamic Edge-State Tensor (DEST)": {
        "Storage": "RAM (Aligned NumPy Array memory layouts)",
        "Computing Unit": "CPU (Highly vectorized NumPy/C operations)",
        "Impact": "Edge variables (water level, speed multipliers, blockages) updated in batch."
    },
    "Global Adjacency CSR Matrix Compilation": {
        "Storage": "RAM (SciPy CSR matrix layout) -> GPU VRAM (when CuPy is loaded)",
        "Computing Unit": "CPU (SciPy C-Arrays fallback) / GPU (CuPy CUDA context)",
        "Impact": "Vectorizes entire city graph traversal costs per vehicle profile."
    },
    "Parallel Shortest-Path Solving": {
        "Storage": "Varies",
        "Computing Unit": "CPU (SciPy C-based csgraph library) / GPU (cupyx.scipy.sparse.csgraph)",
        "Impact": "Runs single-operation multi-source shortest-path matrices for all active agents."
    },
    "Multi-Objective Decision Optimization (NSGA-II)": {
        "Storage": "RAM",
        "Computing Unit": "CPU (Calculates Pareto fronts over utility portfolios)",
        "Impact": "Combines transit metrics, fuel rates, and triage weights to score EOC alternatives."
    }
}

for op, info in mapping.items():
    print(f"\n* {op}:")
    print(f"  - Storage Layout:  {info['Storage']}")
    print(f"  - Compute Engine:  {info['Computing Unit']}")
    print(f"  - Operational Role: {info['Impact']}")
