# Sentinel Command: Enterprise Autonomous Disaster Response Support Engine
=======================================================================================

Sentinel is a research-grade, production-calibrated Decision Support System (DSS) designed for autonomous search-and-rescue resource allocation and tactical pathfinding under corrupted, dynamic, and incomplete information baselines.

---

## 🗺️ System Documentation Handbook & Reading Order

The system design, mathematical foundations, safety governance, and verification suites are organized sequentially in the [`docs/`](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/README.md) handbook:

1. **[System Documentation Hub Index](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/README.md)** — Master index & role-based reading pathways.
2. **[01. System Architecture Overview](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/architecture_overview.md)** — Structural topology, directory map, SQLite data models.
3. **[02. System Flows & Sequence Diagrams](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/system_architecture.md)** — Data flows, simulation step cycles, EGL state diagrams.
4. **[03. Physical Disaster Simulation Models](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/physical_simulation.md)** — BSSA14 seismic shaking, Holland winds, Rothermel fire spread, TWI flood depth.
5. **[04. Decision Support System (DSS)](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/decision_support_system.md)** — Bayesian state estimation, risk Dijkstra, BPR traffic, GEVA allocations.
6. **[05. Execution Governance Layer (EGL)](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/execution_governance.md)** — DAP 5-dimension adequacy math, asymmetric regrets, Mission Policies, TBHO overrides.
7. **[06. Metrics & Telemetry Guide](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/metrics_guide.md)** — Mathematical formulations for operational, physics, DSS, and EGL telemetry.
8. **[07. Parameter Provenance Specification](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/parameter_provenance.md)** — Scientific literature citations (FEMA, FAA, NFPA, Cowley 1971) for parameters.
9. **[08. Systems Verification & Validation Manual](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/validation_manual.md)** — Unit, integration, and sensitivity test specifications.


---

## Quick Start Guide

To run the system:

```bash
# 1. Install dependencies
pip install fastapi uvicorn sqlalchemy networkx numpy scipy pydantic pytest

# 2. Launch ASGI API Server
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# 3. Launch UI Operator Dashboard
cd frontend
npm install
npm run dev
```

The operator dashboard will be accessible at `http://localhost:3000`.
