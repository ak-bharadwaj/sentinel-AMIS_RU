# Decision Support System (DSS)

The core Decision Support System (DSS) of Sentinel acts as the reasoning engine. It translates raw telemetry and uncertain belief states into optimized scout paths and tactical search-and-rescue portfolios.

---

## 1. Context-Aware Bayesian Telemetry

Sentinel updates its belief state dynamically as agents sweep the disaster zone and observe edge states (blocked or clear):

$$P(\text{danger} \mid \text{Obs}) = \frac{P(\text{Obs} \mid \text{danger}) \cdot P_{\text{prior}}}{P(\text{Obs} \mid \text{danger}) \cdot P_{\text{prior}} + P(\text{Obs} \mid \text{safe}) \cdot (1 - P_{\text{prior}})}$$

Where:
*   $P(\text{Obs} \mid \text{danger}) = \eta$ (sensor base accuracy) if the sensor reports `DANGER` (blocked), and $1 - \eta$ if it reports `SAFE` (clear).
*   Sensor base accuracies ($\eta$) are calibrated per vehicle in `sensor_config.json`:
    *   `DRONE_CAMERA`: $0.96$
    *   `HUMAN_VISUAL`: $0.92$
    *   `SATELLITE_OPTICAL`: $0.81$
    *   `CITIZEN_REPORT`: $0.55$

### Belief Age Decay
Unobserved nodes decay exponentially towards the maximum uncertainty state ($0.5$):

$$P_t = 0.5 + (P_{t-1} - 0.5) \cdot e^{-\lambda \cdot \Delta t}$$

Where decay rate $\lambda$ is disaster-specific: `FLOOD` $= 0.015$, `EARTHQUAKE` $= 0.06$, `CYCLONE` $= 0.03$.

---

## 2. Multi-Hazard Risk-Normalized Pathfinding

Sentinel computes traversal costs by normalizing transit times alongside risk metrics, preventing vehicles from driving blindly through hazards:

$$C_e = \frac{T_{\text{travel}}}{360} + w_{\text{risk}} \cdot P_{\text{danger\_vehicle}} \cdot \mu_{\text{safe}} + w_{\text{uncertainty}} \cdot (1 - P_{\text{state\_correct}})$$

Where:
*   $T_{\text{travel}}$ is the time in seconds to traverse the segment, calculated using road-class speed limits and vehicle capabilities.
*   $360\text{s}$ ($6\text{ minutes}$) is the normalization base (scaling travel time to match probability ranges).
*   $P_{\text{danger\_vehicle}}$ is the probability of the hazard exceeding the vehicle's safe limits.
*   $\mu_{\text{safe}}$ is the safe routing factor. Under safe routing mode, it acts as a penalty scaling danger costs to 5x.
*   $w_{\text{risk}}$ and $w_{\text{uncertainty}}$ are relative normalization weights (configured in `routing_weights.json`).

---

## 3. Dynamic BPR Congestion Feedback

To prevent search-and-rescue teams from clustering along the same routes and causing bottlenecks, edge weights scale dynamically with vehicle flows using the Bureau of Public Roads (BPR) congestion model:

$$T_{\text{congested}} = T_{\text{free}} \times \left(1 + \alpha \left(\frac{\text{Flow}}{\text{Capacity}}\right)^\beta\right)$$

Where:
*   $T_{\text{free}}$ is the free-flow transit time.
*   $\text{Flow}$ is the count of active vehicles currently heading towards or traversing the segment.
*   $\text{Capacity}$ is the maximum vehicle capacity of the road type.
*   $\alpha = 0.15$ and $\beta = 4.0$ are standard empirical congestion scaling factors.

---

## 4. Resource Allocation: GEVA

Sentinel matches idle rescue units to target population zones using the **General Expected Value of Allocation (GEVA)** framework.

### Portfolio Utility Formulation
For a set of assignments matching teams to target nodes, GEVA estimates the expected value ($EV$):

$$EV = p_{\text{state\_correct}} \cdot p_{\text{danger}} \cdot S_{\text{expected}} \cdot \text{Reachability} \cdot V_{\text{multiplier}} - \text{Overlap\_Penalty}$$

Where:
*   $S_{\text{expected}} = N_{\text{pop}} \cdot \exp(-\gamma \cdot p_{\text{danger}} \cdot t_{\text{arrival}})$, modeling survivor decay until vehicle arrival.
*   $V_{\text{multiplier}}$ is the **Demographic Vulnerability Multiplier**, computed via a weighted proportion across triage categories rather than a binary trigger:
    $$V_{\text{multiplier}} = \frac{3.0 \cdot N_{\text{immediate}} + 2.0 \cdot N_{\text{delayed}} + 1.2 \cdot N_{\text{minor}} + 1.0 \cdot (N_{\text{pop}} - N_{\text{total\_triage}})}{N_{\text{pop}}}$$
    *(Hospitals scale from $2.0$ base up to $+1.0$ based on actual patient volume; dense residential areas receive $2.5$)*.
*   **Proportional Triage Cleanup**: When pre-emptive or reactive civilian evacuations reduce population at a node, triage categories ($N_{\text{immediate}}$, $N_{\text{delayed}}$, $N_{\text{minor}}$) are proportionally decremented alongside raw population, preventing "ghost" patients from artificially inflating EV scores at already-evacuated zones.
*   $C_{\text{transit}}(t)$ is the risk-normalized travel cost to reach the target.
*   $\text{Overlap\_Penalty}$ penalizes assigning multiple rescue teams to overlapping paths ($0.5$ penalty per $1000\text{m}$ overlap), encouraging wider geographic coverage.


---

## 5. Calibration of Decision and Routing Constants

All operational weights, sensor trust accuracies ($\eta$), and Bureau of Public Roads (BPR) parameters ($\alpha, \beta$) are validated and cross-referenced with literature in the [Parameter Provenance Guide](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/parameter_provenance.md).
