# Validation & Benchmarking Suite

Sentinel includes a suite of automated validation tests, Monte Carlo sensitivity parameter sweeps, and execution scalability benchmarks.

---

## 1. Automated Testing Framework

Automated tests are divided into core engine tests, routing tests, and execution governance tests.

Run the entire verification suite:
```bash
venv\Scripts\python -m pytest tests/ -v
```

### EGL Unit & Integration Tests (`tests/test_egl/`)
*   `test_dap.py`: Verifies dimension math, vetoes, and regrets calculation bounds.
*   `test_epm.py`: Validates ethical profile switching requirements and parameters.
*   `test_fcm.py`: Asserts fleet target locks (mutex), defer decays, and staged dispatches.
*   `test_am.py`: Tests SQLite immutability triggers (UPDATE/DELETE prevention), CSV logs export, and SHA-256 integrity check.
*   `test_hom.py`: Tests Time-Boxed Human Override (TBHO) timeout default logic.
*   `test_xe.py`: Verifies the accuracy of plain English rationale outputs.
*   `test_egl_integration.py`: Wires all sub-modules together to verify end-to-end evaluation pipeline logic.

---

## 2. Sensitivity Analysis (Decisions Stability)

To verify the robustness of Category B parameters, a Monte Carlo sensitivity analysis is executed:

```bash
venv\Scripts\python -m pytest tests/test_egl_sensitivity.py -v
```

### Methodology
1.  Loads 10 diverse disaster scenarios representing different levels of population density, structural risk, communications blackout proximity, and information uncertainty.
2.  Varies each Category B constant by $\pm 30\%$ while holding other parameters fixed.
3.  Sweeps:
    *   `C_route_closure` $\in [1.0, 2.5]$
    *   `C_golden_hour` $\in [1.5, 3.0]$
    *   `aem_slope` $\in [0.2, 0.5]$
    *   `base_margin` $\in [0.10, 0.20]$
4.  Calculates the proportion of decisions that flip.
5.  **Robustness Criterion**: A parameter variation is acceptable only if it flips less than $15\%$ of total decisions, indicating that the system's decisions do not fluctuate erratically under minor parameter adjustments. For the theoretical basis of the swept parameters, see [Parameter Provenance Guide](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/parameter_provenance.md).

---

## 3. Performance & Scalability Benchmarks

Sentinel measures execution times to ensure real-time performance on large-scale urban graphs:

### Run Situation Assessment Benchmarks
Runs comparative benchmarks measuring NumPy vectorization performance improvements over standard loops on a 2000-node urban network:
```bash
venv\Scripts\python backend/simulation/benchmarks/sa_benchmark.py
```

### Metrics Tracked
*   **Vectorized Situation Assessment Speedup**: Performance ratio of vectorized NumPy operations against standard Python attribute iteration (typically achieving 10x-50x speedups).
*   **Belijkstra Routing latency (ms)**: Measures shortest path search times across the grid graph.
*   **GEVA Allocation Latency (ms)**: Time to compute bipartite matching matrix across 200+ target zones.
*   **EGL Evaluation Overhead (ms)**: Computational time introduced by EGL orchestrator and DAP regret math. Must be $< 5\text{ms}$ per dispatch decision to prevent latency bottlenecks.
