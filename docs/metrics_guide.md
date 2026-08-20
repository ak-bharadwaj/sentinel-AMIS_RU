# Metrics & Telemetry Guide

This guide details all simulation, disaster physics, DSS, and EGL telemetry variables, their mathematical formulations, and where they are stored or transmitted.

---

## 1. Tactical Operational Metrics

These metrics monitor mission-level performance and are collected dynamically at each step.

*   **Survivor Survival Count ($S_{\text{saved}}$)**:
    $$S_{\text{saved}} = \sum \text{rescued survivors at shelter nodes}$$
*   **Active Agent Utilization ($U_{\text{fleet}}$)**:
    $$U_{\text{fleet}} = \frac{N_{\text{active\_agents}}}{N_{\text{total\_fleet}}}$$
*   **Mission Time Elapsed ($T_{\text{elapsed}}$)**:
    Represents physical time elapsed in minutes, increments by $1.0$ per simulation tick.

---

## 2. Disaster Physics Metrics

Calculated using physical hazard models and mapped onto coordinates.

### Seismic Peak Ground Acceleration (PGA)
PGA values ($g$) determine road integrity damage:
*   $\text{PGA} < 0.10g$: Normal.
*   $\text{PGA} \ge 0.35g$: Ground ruptures, triggers a $40\%$ chance of roadway blockage.
*   $\text{PGA} \ge 0.60g$: Severe structural shaking, triggers $85\%$ blockage probability on tunnels and bridges.

### Meteorological Wind Velocity ($V_{\text{wind}}$)
Wind speed measured in km/h:
*   $V_{\text{wind}} < 50\text{ km/h}$: Normal operations.
*   $V_{\text{wind}} \ge 80\text{ km/h}$: Wind gust thresholds, triggers flight restrictions for helicopters and risk multipliers for standard vehicles.

### Rothermel Rate of Spread (ROS)
The fire propagation speed ($R$, in meters per minute):
$$R = \text{speed of fire boundary advance downwind}$$
Segments within the active boundary receive a hazard rating of $P_{\text{danger}} = 1.0$.

### Hydrological Depth Above Road ($d_{\text{water}}$)
Water depth measured in meters relative to road surface ($d_{\text{water}} = \max(0.0, h_{\text{node}} - \text{elevation}_{\text{node}})$):
*   $d_{\text{water}} \ge 0.15\text{m}$: Standard and scout cars caution speed penalty ($50\%$ velocity reduction).
*   $d_{\text{water}} \ge 0.30\text{m}$: Stalls standard and scout cars ($100\%$ blockage).
*   High-Water Trucks (`HIGH_WATER_TRUCK`): Traverse flood water up to $8.0\text{m}$ depth without physical blockage penalty.
*   Zodiac Boats (`ZODIAC_BOAT`): Water-native craft. Max clearance is unconstrained ($9999.0\text{m}$), preventing stalls in deep flood sinks while applying land speed penalties when $d_{\text{water}} < 2.0\text{m}$.
*   Helicopters (`HELICOPTER`): Airborne. Ignores all road surface blockages and flood depths.


---

## 3. Decision Support System (DSS) Metrics

Metrics computed by the Uncertainty, Routing, and GEVA engines.

### Bayesian Correctness Probability ($P_{\text{state\_correct}}$)
Represents the confidence index of observed node status $[0.0, 1.0]$. A value of $0.5$ represents maximum uncertainty:
*   Direct sensor sweeps set $P_{\text{state\_correct}}$ to $\eta$ (sensor accuracy).
*   Unobserved steps decay confidence towards $0.5$ at rate $\lambda$.

### Normalised Dijkstra Travel Cost ($C_e$)
Dimensionless routing cost calculated per edge:
$$C_e = \frac{T_{\text{travel}}}{360} + w_{\text{risk}} \cdot P_{\text{danger\_vehicle}} \cdot \mu_{\text{safe}} + w_{\text{uncertainty}} \cdot (1 - P_{\text{state\_correct}})$$

### BPR Traffic Congestion Factor ($T_{\text{congested}}$)
Time expansion factor scaling with edge occupancy:
$$\text{Multiplier} = 1.0 + 0.15 \cdot \left(\frac{N_{\text{agents}}}{C_{\text{road}}}\right)^4$$

### GEVA Expected Utility Portfolio Score ($EV$)
Measures expected value of matching active teams to targets:
$$EV = P_{\text{live}} \cdot V_{\text{target}} \cdot U_{\text{triage}} - C_{\text{transit}} - \text{Overlap\_Penalty}$$

---

## 4. Execution Governance (EGL) Metrics

Computed per dispatch request by EGL sub-modules.

### Five Adequacy Dimensions $[0.0, 1.0]$
*   **Epistemic Readiness ($\epsilon$)**: Information completeness.
*   **Crew Safety Index ($\sigma$)**: Route safety.
*   **Comms Reliability ($\kappa$)**: Signal coverage along paths.
*   **Resource Sufficiency ($\rho$)**: Fuel and capacity reserves.
*   **Source Diversity Index ($\delta$)**: Degree of observation overlap.

### Geometric Composite Score ($S_c$)
Calculated in `dap.py` to ensure backwards compatibility with legacy metrics:
$$S_c = \sqrt[4]{\epsilon \cdot \sigma \cdot \kappa \cdot \rho}$$

### Override and Veto Metrics
*   **Override Decision Rate ($R_{\text{override}}$)**:
    $$R_{\text{override}} = \frac{N_{\text{override\_approvals}}}{N_{\text{escalations}}}$$
    If $R_{\text{override}} \ge 0.40$ (over a 20-decision rolling window), EGL logs a warning to indicate potential operator cognitive fatigue.
*   **Mutex Veto Count**: Counter tracking the number of dispatches blocked due to target allocation conflicts.

---

## 5. Calibration References

All thresholds, limits, and capacity ratings described in this guide are cross-linked to their physical justifications and literature references in the [Parameter Provenance Guide](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/parameter_provenance.md).
