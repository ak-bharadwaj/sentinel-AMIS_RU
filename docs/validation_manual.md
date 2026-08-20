# Systems Verification & Validation Manual

This manual details the Software Development Engineering (SDE) verification specifications, tests structures, validation loops, and integration testing frameworks for Sentinel's core engines.

---

## 1. Core DSS Validations (Scouting, Routing, & Utility)

Core DSS validations verify that the search-and-rescue engine makes correct planning decisions under simulated data baselines.

### 1.1 Bayesian Telemetry Updates & Decay
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_sentinel.py -k "bayesian_update or decay"
    ```
*   **Test Criteria**:
    1.  *Update Consistency*: An observation of `SAFE` (clear) on a node with a high prior of danger ($0.8$) must pull the updated probability down towards $0.1$. A sensor with higher accuracy ($\eta$) must pull the posterior closer to the observed state than a sensor with lower accuracy.
    2.  *Decay towards Maximum Entropy*: Unobserved nodes must decay towards $P_{\text{danger}} = 0.5$. The decay rate must match the configured disaster profile ($\lambda$).
    3.  *Provenanced Spatial Updates*: Adjacent confidence updates must decrease exponentially with distance from the sensor coordinate.

### 1.2 Routing Integrity (Belijkstra Core)
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_sentinel.py -k "confidence_routing"
    ```
*   **Test Criteria**:
    1.  *Risk Avoidance*: Routing algorithms must select a longer, hazard-free detour over a shorter, high-hazard route if $P_{\text{danger}} \cdot \mu_{\text{safe}}$ exceeds the detour cost.
    2.  *Bridge & Tunnel Penalties*: Routes traversing bridges or tunnels must receive slope and safety modifiers depending on Vs30 soils shaking ratings.

---

## 2. DSS Algorithm Integrations Validation

Validates the added planning algorithms, such as BPR road traffic congestion multipliers, safe-route caution thresholds, and evacuation order portfolios.

### 2.1 BPR Road Traffic Congestion & Dynamic Cost
*   **Verification Location**:
    Pre-computed dynamically during simulation steps inside the simulation loop (`engine.py`). Verified during full simulation ticks when multiple rescue teams target overlapping routes, confirming that alternative paths are calculated due to flow penalties.

### 2.2 Evacuation Portfolios & GEVA Utility
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_sentinel.py -k "geva_ev_calculation"
    ```
*   **Test Criteria**:
    1.  *Vulnerability Prioritization*: Expected Value ($EV$) must scale inversely with arrival times to reflect decay models. EV calculations must prioritize population centers with urgent triage requirements.

---

## 3. Physical Hazard Engine Validations

Validates that physical disasters modify edge traversability parameters correctly.

### 3.1 Seismic Attenuation (BSSA14 GMPE)
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_terrain_intelligence.py -k "earthquake"
    ```
*   **Test Criteria**:
    1.  *Vs30 Soil Properties Validation*: Shaking Vs30 must prioritize official geological properties (`vs30_geological`). Low-elevation nodes cap Vs30 to Class E ($\le 180\text{ m/s}$) to model loose alluvial amplification.

### 3.2 Meteorological Gusts & Storm Surge
*   **Verification Commands**:
    ```bash
    venv\Scripts\python -m pytest tests/test_historical_modes.py -k "cyclone"
    venv\Scripts\python -m pytest tests/test_terrain_intelligence.py -k "cyclone"
    venv\Scripts\python -m pytest tests/test_refactored_decisions.py -k "weather"
    ```
*   **Test Criteria**:
    1.  *Cyclone Preset loading*: NISARGA 2020 preset verifies $90\text{ km/h}$ wind speed and high tide cycles load correctly.
    2.  *Storm Surge Boundary*: A node elevated at $+12\text{m}$ effective elevation must not be inundated by a storm surge of $+3\text{m}$.
    3.  *Weather Grounding*: A wind speed of $60\text{ km/h}$ must ground scout launches, returning a `WAIT` decision.

### 3.3 Hydrological Accumulation (TWI) & Slopes
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_terrain_intelligence.py -k "TestSlope or TestDrainage or TestFlood"
    ```
*   **Test Criteria**:
    1.  *TWI Basin Accumulation*: Nodes classified as basins (high TWI) must accumulate water at a faster rate than sloped terrain nodes.
    2.  *Slope Access Multipliers*: Multipliers for standard vehicles must scale to $> 2.0$ on steep hills ($30^{\circ}$) and remain $1.0$ on flat slopes. Helicopters must ignore slope.
    3.  *Flood Inundation*: Coastal roads at $+1.5\text{m}$ must flood when water exceeds $+1.8\text{m}$ (exceeding clearance limits), whereas elevated motorway roads at $+12\text{m}$ must remain open.

---

## 4. Execution Governance (EGL) Validations

Validates EGL safety checks, ethics profiles, immutable logging, and TBHO overrides.

### 4.1 DAP Pure Math & Satisficing (`test_dap.py`)
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_egl/test_dap.py -v
    ```
*   **Test Criteria**:
    1.  *Veto Rule Check*: Triggering critical fuel or comms blackout must block dispatch, returning `DEFER` or `ESCALATE` regardless of utility.
    2.  *Satisficing Thresholds*: Returns `EXECUTE` only if $R_{\text{wait}} > R_{\text{act}} + m$.

### 4.2 Mission Policy Profiles (`test_epm.py`)
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_egl/test_epm.py -v
    ```
*   **Test Criteria**:
    1.  *Commander Signature requirement*: Attempts to switch profiles without a valid officer ID signature must fail.
    2.  *Value Ordering*: Enforces that the cost of crew life ($C_{\text{crew\_lost}}$) exceeds equipment loss ($C_{\text{resource\_waste}}$).

### 4.3 SQLite Immutability Triggers (`test_am.py`)
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_egl/test_am.py -v
    ```
*   **Test Criteria**:
    1.  *Audit Append-Only*: Direct `UPDATE` or `DELETE` SQL queries against the `egl_audit` table must fail with a `sqlite3.IntegrityError`.
    2.  *Forensic Export*: CSV logs export must include a matching SHA-256 validation checksum.

### 4.4 Human Override Timers (`test_hom.py`)
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_egl/test_hom.py -v
    ```
*   **Test Criteria**:
    1.  *Countdowns*: TBHO countdown windows must adjust based on the current disaster phase (Golden hour $= 30\text{s}$, Sustained $= 60\text{s}$, Recovery $= 90\text{s}$).
    2.  *Regret-Minimizing Fallback Action*: On timeout, low-irreversibility dispatches ($I < 0.50$) default to `EXECUTE`. For high-irreversibility dispatches ($I \ge 0.50$), if $R_{\text{wait}} > R_{\text{act}}$, the timeout defaults to `EXECUTE` (minimizing lives lost when waiting risk exceeds acting risk), otherwise defaulting to `DEFER`.


### 4.5 EGL Sensitivity Sweep (`test_egl_sensitivity.py`)
*   **Verification Command**:
    ```bash
    venv\Scripts\python -m pytest tests/test_egl_sensitivity.py -v
    ```
*   **Test Criteria**:
    1.  *Robustness*: Sweeping Category B parameters by $\pm 30\%$ must flip less than $15\%$ of total decisions, ensuring the EGL is stable under parameter changes.

---

## 5. Verification Constraints Calibration

All constants and limit thresholds used within these verification loops are detailed, justified, and cross-referenced in [Parameter Provenance Guide](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/parameter_provenance.md).
