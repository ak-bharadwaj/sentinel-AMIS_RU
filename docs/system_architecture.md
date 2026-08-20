# System Architecture & Flow Guide

This document provides a Software Development Engineer (SDE) level specification of Sentinel's components, internal data flows, system cycles, and database relationships.

---

## 1. System Interaction Topology

The data pipeline operates as an asynchronous loop bridging a Next.js single-page application (SPA), an ASGI FastAPI web gateway, a persistent SQLite storage manager, a vector-graph matrix routing engine, and a modular Execution Governance Layer (EGL).

```mermaid
sequenceDiagram
    autonumber
    actor Commander as Tactical Operator
    participant UI as Next.js Dashboard
    participant API as FastAPI Gateway
    participant DB as SQLite Database
    participant Sim as Simulation Engine
    participant DSS as Decision Support System
    participant EGL as Execution Governance Layer

    Commander->>UI: Trigger Simulation Step / Dispatch
    UI->>API: POST /api/simulation/step
    API->>Sim: Acquire Lock & Invoke step()
    
    rect rgb(240, 240, 240)
        Note over Sim, EGL: Decision & Planning Cycle
        Sim->>DSS: Retrieve Bayesian Belief & Run Prediction Models
        DSS->>DSS: Recompile shortest paths (Dijkstra normalisation)
        DSS->>DSS: Match resource allocation portfolios (GEVA)
        DSS->>EGL: Evaluate assignments via evaluate()
        EGL->>EGL: Fleet Mutex Check & DEFER Decay Margin computation
        EGL->>EGL: DAP Regrets math & satisficing decision rule check
        alt Outcome is ESCALATE
            EGL->>API: Trigger TBHO override (SSE broadcast)
            API->>UI: Display Countdown Card (30/60/90s)
            Commander->>API: POST /api/egl/override/{id}
            API->>EGL: Inject commander decision
        end
        EGL->>EGL: Write Forensic Log to audit DB
    end

    Sim->>Sim: Update physical positions & decay survival probabilities
    Sim->>DB: Sync ground truth and belief states
    Sim->>UI: Broadcast Telemetry JSON (Websocket)
    UI->>Commander: Update Tactical Map canvas & Rationale lists
```

---

## 2. Core System Flows

### 2.1 The Simulation Step Loop
Each simulation step represents 1 minute of physical time. The step loop execution follows this sequence:

```mermaid
graph TD
    A[Start Step] --> B[Environmental Check: Update weather data]
    B --> C[Disaster Propagation: Update flood depths, wind gusts, fire boundaries]
    C --> D[Sensor Decay: Decay confidence of unobserved nodes]
    D --> E[Planning Cycle Check: Reroute stranded agents, find idle agents]
    E --> F[Run Coordinator: assign_scouts & assign_rescues]
    F --> G[EGL Gate check for each assignment]
    G --> H[Update Agent Movement: Progress along edge coordinates]
    H --> I[Observation Checks: Apply observations, check comms blackout zones]
    I --> J[Save Snapshot: Sync ground truth, belief and agent state to SQLite]
    J --> K[End Step: Broadcast telemetry payload to UI]
```

### 2.2 EGL Orchestrator Evaluation Loop
Every candidate dispatch proposal is evaluated by EGL before any route is assigned to an agent:

```mermaid
graph TD
    Start[Proposed Assignment] --> Mutex{Target locked by Mutex?}
    Mutex -- Yes --> Defer[Veto: DEFER]
    Mutex -- No --> Weights[Load Mission Policy Weights for Current Phase]
    Weights --> Margin[FCM: Compute Decayed Decision Margin]
    Margin --> Starve{Defer count >= 6?}
    Starve -- Yes --> Escalate[Force ESCALATE]
    Starve -- No --> DAP[Run DAP Evaluation Math]
    DAP --> Veto{Any hard veto triggered?}
    Veto -- Yes --> VetoAction[Apply Veto Outcome: DEFER/ESCALATE]
    Veto -- No --> Regret[Compute Regrets: R_act vs R_wait]
    Regret --> DecisionRules{Apply satisficing rules}
    DecisionRules -- R_wait > R_act + m --> Staged{I >= 0.70?}
    Staged -- Yes --> Stage[STAGED_EXECUTE: Truncate route to staging node]
    Staged -- No --> Exec[EXECUTE: Dispatch agent directly]
    DecisionRules -- R_act > R_wait + m --> DeferCount[DEFER: Increment target defer counter]
    DecisionRules -- Within margin --> Escal[ESCALATE: Fire TBHO command request]
    VetoAction --> Audit[Write record to SQLite audit log]
    Stage --> Audit
    Exec --> Audit
    DeferCount --> Audit
    Escal --> Audit
```

---

## 3. Database Relationship Diagram

The SQLite database (`sentinel.db`) is structured to optimize geospatial routing queries and ensure clean synchronization boundaries.

```
+--------------------+            +--------------------+            +--------------------+
|       nodes        | 1        N |       edges        | N        1 |    mission_state   |
+--------------------+------------+--------------------+------------+--------------------+
| id (VARCHAR, PK)   |            | id (VARCHAR, PK)   |            | id (VARCHAR, PK)   |
| node_type (VARCHAR)|            | source (VARCHAR,FK)|            | sim_time (REAL)    |
| lat (DOUBLE)       |            | target (VARCHAR,FK)|            | active_baseline    |
| lon (DOUBLE)       |            | distance (DOUBLE)  |            | total_rescues      |
| population (INT)   |            | confidence (DOUBLE)|            | agents_state (JSON)|
| triage_imm (INT)   |            | blocked (BOOLEAN)  |            +--------------------+
| triage_del (INT)   |            | speed_factor (DBL) |
| triage_min (INT)   |            | geometry (TEXT)    |
| p_danger (DOUBLE)  |            +--------------------+
| status (VARCHAR)   |
| last_obs (DATETIME)|
+--------------------+
```

### Forensic Audit Log (`egl_audit.db`)
Stored in a separate database file with restricted schema access and immutability triggers:
*   `record_id` (TEXT, PK): UUID4.
*   `timestamp_utc` (TEXT): ISO 8601 UTC timestamp.
*   `sim_time` (REAL): Simulation step timestamp.
*   `agent_id` (TEXT, FK): Dispatched agent.
*   `target_node` (TEXT): Ultimate target destination.
*   `outcome` (TEXT): Final action outcome (`EXECUTE`, `DEFER`, `STAGED_EXECUTE`, `ESCALATE`).
*   `epsilon`, `sigma`, `kappa`, `rho`, `delta`, `composite_score` (REAL): Adequacy variables.
*   `regret_act`, `regret_wait`, `effective_margin`, `irreversibility` (REAL): Regrets variables.
*   `authorized_by` (TEXT): Officer signature ID (required for overrides).
*   `human_override` (TEXT): Override outcome details.
*   `shadow` (INTEGER): $1$ if shadow run, $0$ if live.

---

## 4. Operational Parameter Reference

All operational thresholds, costs, and timeouts referenced in this architecture are cross-linked to their physical justifications and literature sources in the [Parameter Provenance Guide](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/parameter_provenance.md).
