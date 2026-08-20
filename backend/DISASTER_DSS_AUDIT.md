# Sentinel Decision Support System (DSS) Backend Code Audit

This document presents a rigorous scientific, mathematical, and software architecture audit of the Sentinel DSS backend codebase. The audit is structured into 12 distinct phases to assess the system's theoretical soundness, numerical stability, physical realism, operations research validity, and software robustness.

---

## Phase 1: Scientific Verification vs. Literature

### 1.1 Dijkstra Routing Cost Function
*   **Implementation Location:** `backend/routing/confidence_dijkstra.py`
*   **Formula Checked:**
    $$Cost = \frac{\text{TimeRaw}}{\text{RefTime}} + w_{\text{risk}} \cdot P_{\text{danger}} \cdot M_{\text{safe\_route}} + w_{\text{uncertainty}} \cdot (1 - P_{\text{state\_correct}}) + w_{\text{terrain}} \cdot (M_{\text{slope}} - 1) \cdot (1 - \min(acc_u, acc_v))$$
*   **Verification:** Dijkstra's original algorithm (Dijkstra, 1959) assumes scalarized, additive edge weights where $w(e) \geq 0$ is guaranteed to avoid negative cycles. While the Sentinel implementation enforces non-negativity (due to clipping and non-negative parameters), it exhibits a **heuristic scalarization mismatch**. 
*   **Scientific Gap:** Epistemic uncertainty ($1 - P_{\text{state\_correct}}$) and aleatoric risk ($P_{\text{danger}}$) are combined linearly. In decision theory, these represent orthogonal dimensions: information quality vs. physical hazard. A linear penalty can cause the router to avoid completely safe, unobserved roads (exploration starvation) or traverse highly risky roads with artificially high observation confidence. 

### 1.2 NSGA-II Multi-Objective Optimization
*   **Implementation Location:** `backend/decision_engine/decision_optimizer.py`
*   **Verification:** Compared against Deb et al. (2002). The non-dominated sorting and crowding distance calculations are theoretically correct.
*   **Scientific Gap (Population Collapse):** The genetic algorithm lacks a population replenishment step during repair and duplication filtering. When duplicates are pruned or repaired to `None` values, the population size decays monotonically across generations, causing premature convergence to a sub-optimal, low-diversity Pareto front.

### 1.3 Structural Causal Model (SCM)
*   **Implementation Location:** `backend/decision_engine/counterfactual.py`
*   **Verification:** Uses Pearl's Causal SCM framework (Pearl, 2009). The counterfactual engine simulates interventions ($do(X = x)$) to compute path hazard sensitivity.
*   **Scientific Gap:** The graph topology in `PearlCausalSCM` is assumed to be a static DAG representing causal influences from nodes to edges. However, physical disaster dynamics (e.g., flooding) feature feedback loops (water level at $u$ affects $v$, which in turn flows back to $u$ depending on elevation changes). A static DAG cannot model cyclic physical relationships, violating Pearl's acyclicity assumption.

### 1.4 Markov Random Field (MRF) Spatial Propagation
*   **Implementation Location:** `backend/decision_engine/uncertainty_engine.py`
*   **Verification:** The engine attempts a 2-iteration spatial belief propagation loop using `mrf_damping = 0.35`.
*   **Scientific Gap (Redundant Propagation):** The danger propagation is defined as:
    $$\text{propagated\_danger} = \min(0.95, P_{\text{danger}}(u) \cdot \text{factor})$$
    where $\text{factor} = 0.35 \times \{1.0, 1.5\} \leq 0.525$. Since the maximum propagated danger is $\leq 0.49875$, and a node must have $P_{\text{danger}} > 0.8$ to act as a danger source, no newly updated node can ever trigger propagation in the second iteration. The second iteration is mathematically dead code.

### 1.5 Expected Value of Information (EVI)
*   **Implementation Location:** `backend/uncertainty/information_value.py`
*   **Verification:** The code defines "Global IV" as:
    $$IV = 0.40 \cdot H_{\text{norm}} + 0.30 \cdot \text{Pop}_{\text{norm}} + 0.30 \cdot \text{Importance}$$
*   **Scientific Gap:** This is a subjective weighted linear combination, **not** the mathematical Expected Value of Information (EVI) from decision theory:
    $$EVI = E_{Y} [\max_{a \in A} E_{X|Y} [U(a, X)]] - \max_{a \in A} E_{X} [U(a, X)]$$
    It fails to ground the value of information in the utility of subsequent rescue actions, rendering search decisions sub-optimal.

---

## Phase 2: Mathematical Audit

### 2.1 Wildfire Propagation Wind-Vector Inversion (Critical)
*   **File:** `backend/disaster/wildfire.py` (Lines 81-83, 118-120)
*   **Mathematical Error:** 
    ```python
    wind_rad = math.radians(self.wind_direction_deg)
    wind_vector = (math.sin(wind_rad), math.cos(wind_rad))
    # ...
    dot_prod = dir_x * wind_vector[0] + dir_y * wind_vector[1]
    wind_bias = 1.0 + max(0.0, dot_prod) * 2.0
    ```
    Standard meteorology defines wind direction as the heading **from which** the wind blows. A west wind ($270^\circ$) blows **to** the east ($+x$ direction). Under this code, a west wind yields `wind_vector = (-1, 0)`. The dot product is maximized when the edge direction is west ($-x$), boosting wildfire propagation **upwind** (into the wind) instead of **downwind**. This completely inverts the physical fire front trajectory.

### 2.2 Hydrologic Gravity Spread Order-Dependence (Major)
*   **File:** `backend/decision_engine/prediction_engine.py` (Lines 57-73)
*   **Mathematical Error:** 
    ```python
    for u, flows in outflows.items():
        # ...
        for v, flow in flows:
            scaled_flow = flow * scale
            new_levels[u] -= scaled_flow
            new_levels[v] += scaled_flow
    ```
    The gravity spread simulation performs in-place state modification of `new_levels` during iteration. This violates Jacobi double-buffering. The resulting water distribution is highly dependent on the dictionary key ordering (arbitrary python hash order), introducing numerical asymmetry and non-determinism.

### 2.3 Flood Receding Threshold Mismatch (Major)
*   **File:** `backend/simulation/engine.py` (Lines 649-663)
*   **Mathematical Error:** The flood blockage checker blocks roads when $\text{water\_level} - \text{eff\_elev} > 0.30$ meters. However, the drainage recovery check clears blockages based on absolute water height:
    ```python
    if new_wl < 10.0 and data.get('status') == "FLOODED":
        data['status'] = "SAFE"
    ```
    If a road at elevation $2.0$m has its water level drop to $9.0$m, it is marked as "SAFE", even though there is still $7.0$m of standing water on the road ($9.0 - 2.0 = 7.0$m $\gg 0.30$m).

### 2.4 Earthquake Epicenter Distance Coordinate Distortion (Major)
*   **File:** `backend/disaster/earthquake.py` (Lines 140-153)
*   **Mathematical Error:** 
    ```python
    dist_to_epicenter = math.hypot(lat - self.epicenter_lat, lon - self.epicenter_lon)
    dist_km = dist_to_epicenter * 111.0
    ```
    Euclidean distance is computed in degrees, then multiplied by $111.0$. This is only valid at the equator. At higher latitudes, the longitude conversion factor must be scaled by $\cos(\text{latitude})$. This distorts the seismic attenuation radius (PGA) into an ellipse.

---

## Phase 3: Disaster Science Review

*   **Evacuation Modeling:** Autonomous evacuations in `engine.py` route civilians directly along open shortest paths. In reality, evacuation routes exhibit bottleneck congestion and behavioral delay. Incorporating a dynamic Lighthill-Whitham-Richards (LWR) kinematic wave model for road congestion is recommended.
*   **Cyclone Mod:** The Holland wind model uses a high spatial decay coefficient (`inland_decay = math.exp(-0.08 * dist_to_coast_km)`), losing 8% wind speed per km. Real cyclones retain hurricane-force winds up to 50–100 km inland. This model severely underestimates inland wind damage.

---

## Phase 4: Operations Research (OR) Review

*   **Resource Allocation:** Multi-objective allocation in `decision_optimizer.py` models vehicle-target assignment without time-window constraints (VRPTW). In real disasters, patients have survival windows (triage decay). The lack of mixed-integer linear programming (MILP) formulations with deadline constraints represents a gap for complex multi-depot routing.

---

## Phase 5: Digital Twin Review (ISO 23247 / Siemens)

*   **Siemens Comparison:** Siemens digital twins utilize real-time sensor streams synchronized via a high-speed telemetry bus (MQTT/Kafka) with sub-second latency. Sentinel relies on a discrete-event polling database (SQLite) executing at 1-minute steps, which limits real-time closed-loop control.
*   **ISO 23247:** Sentinel lacks formal entity relation mappings (Product, Process, Resource) required by the ISO 23247 standard for manufacturing and operational digital twins.

---

## Phase 6: AI Review

*   **Bayesian Priors:** `UncertaintyEngine` uses a Beta-Binomial conjugacy model with static priors (e.g., Beta(2.0, 0.5) for nodes). While mathematically elegant, these priors are uncalibrated to empirical regional statistics.
*   **Explainability:** Explanations generated in `explainability.py` are rule-based templates rather than true causal attribution values (e.g., SHAP or causal Shapley values).

---

## Phase 7: Software Architecture Review

*   **SQLite Concurrency:** SQLite WAL mode is activated. However, under high write loads from parallel WebSockets and background simulation loops, SQLite will throw `database is locked` errors due to single-writer constraints. Upgrading to PostgreSQL is recommended for production.
*   **Coupling:** High coupling between the physical simulation (`engine.py`) and agent routing logics. The simulation engine directly manipulates agent internal states (e.g., aborting paths during blackouts).

---

## Phase 8: Benchmark Review

*   **Friedman & Wilcoxon Tests:** The tests in `benchmark.py` are statistically valid, but the sample size of targets (often $< 10$) can violate the asymptotic assumptions of the chi-square distribution in the Friedman test, leading to inflated Type I errors. Exact permutation tests should be used for small sample sizes.

---

## Phase 9: Novelty Review

*   **Sentinel vs. IBM Intelligent Operations Center (IOC) & Sahana Eden:** Sentinel's primary innovation is the tight coupling of **dynamic physical hazard prediction (Holland/Rothermel/BSSA14)** with **epistemic uncertainty routing**. Traditional systems rely on static routing overlays.

---

## Phase 10: Publication Readiness Peer Reviews

*   **AI Reviewer:** "The causality engine is a static DAG; it must accommodate temporal cyclic feedback loops of physical hazards."
*   **OR Reviewer:** "The NSGA-II optimizer suffers from population collapse and lacks MILP benchmarks with time-windows."
*   **Disaster Science Reviewer:** "The wind direction vector inversion in the Rothermel model violates basic physics."

---

## Phase 11: Reproducibility Audit

*   **Random Seeds:** The wildfire simulator resets the random seed to the simulation step (`random.seed(step)`) at every step. This makes fire propagation identical across runs regardless of initial conditions, severely limiting stochastic testing.

---

## Phase 12: Final Gap Analysis & Corrective Actions

| ID | Module | Severity | Gap | Corrective Action |
|---|---|---|---|---|
| **01** | `disaster/wildfire.py` | **CRITICAL** | Wind-vector propagation inversion (fire spreads upwind). | Negate the wind vector components or redefine standard meteorological wind heading calculation: `wind_vector = (-math.sin(wind_rad), -math.cos(wind_rad))`. |
| **02** | `decision_engine/prediction_engine.py` | **MAJOR** | In-place gravity spread state updates (order-dependence). | Implement a double-buffered update: compute all outflows using `water_levels` snapshot, store delta in a temporary dict, then apply updates. |
| **03** | `simulation/engine.py` | **RESOLVED** | Flood receding threshold mismatch ($10.0$m absolute vs $0.3$m relative). | **FIXED**: Clearance check now evaluates depth-above-road: `if new_wl - eff_elev < params.flood_car_blocked_m`. |

| **04** | `disaster/earthquake.py` | **MAJOR** | Euclidean degree-to-km epicenter distance distortion. | Replace `math.hypot` with the imported `haversine_distance` function. |
| **05** | `decision_engine/decision_optimizer.py` | **MAJOR** | GA population collapse due to repair pruning. | Replenish population size to `POP_SIZE` by spawning new mutated/random individuals when size drops. |
