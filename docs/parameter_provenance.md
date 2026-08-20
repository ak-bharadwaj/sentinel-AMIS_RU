# Sentinel Parameter Provenance and Physical Units Specification

This document provides the scientific basis, literature citations, physical units, and calibration ranges for all model parameters configured within the Sentinel Decision Support System (DSS).

---

## 1. Physical Units Specification

The internal physics engines and calculations enforce the following standard SI units:

| Dimension | Physical Unit | Symbol | Usage |
|---|---|---|---|
| **Distance / Length** | Meters | $m$ | Coordinates, edge lengths, water depths, sensor ranges |
| **Time** | Seconds | $s$ | Travel time, computation metrics, steps |
| **Speed** | Meters per second | $m/s$ | Agent speeds, water flow velocities |
| **Acceleration** | g-units | $g$ | Peak Ground Acceleration (PGA) seismic force |
| **Pressure** | Hectopascals | $hPa$ | Cyclone barometric pressure (eyewall/deficit) |
| **Mass Density** | Kilograms per cubic meter | $kg/m^3$ | Surface air density ($\rho \approx 1.15$ baseline) |

---

## 2. Parameter Justifications and Citation Trail

### 2.1 Environmental and Hazard Thresholds

#### Seismic Damage Thresholds
*   **PGA $\ge 0.35g$**: Trigger for roadway blockage probability scaling.
    *   *Justification*: Ground acceleration of $0.35g$ corresponds to Modified Mercalli Intensity (MMI) VII to VIII (Wald et al., 1999; Worden et al., 2012). At this intensity, structural damage to masonry and significant road cracking/slumping occur.
    *   *Citation*: Wald, D. J., Quitoriano, V., Heissler, T. H., & Dewey, J. W. (1999). Relationships between peak ground acceleration, peak ground velocity, and Modified Mercalli intensity in California. *Earthquake Spectra*, 15(3), 557-583.
*   **PGA $\ge 0.60g$**: Severe shaking trigger for bridge and tunnel vulnerabilities.
    *   *Justification*: Ground acceleration of $0.60g$ corresponds to MMI IX+ where landslides occur and bridges experience structural shear failure.
    *   *Citation*: Federal Emergency Management Agency (FEMA). (2020). *Hazus Earthquake Model Technical Manual*. Washington, D.C.

#### Meteorological Wind Gust Thresholds
*   **Wind Speed $\ge 80\text{ km/h}$ ($22.2\text{ m/s}$)**: Trigger for aerial asset grounding and ground safety multipliers.
    *   *Justification*: Corresponds to Beaufort Scale 9 (Strong Gale). Standard commercial and tactical rotary-wing assets have operational limits of $40$ to $45$ knots ($74$ to $83\text{ km/h}$) due to tail rotor control limits and aerodynamic stability constraints.
    *   *Citation*: Federal Aviation Administration (FAA). (2012). *Helicopter Flying Handbook (FAA-H-8083-21A)*. U.S. Department of Transportation.

#### Hydrological Water Level Clearances
All hydrological water level clearances are evaluated as **depth-above-road** ($h_{\text{above\_road}} = \max(0.0, h_{\text{node}} - \text{elevation}_{\text{node}})$):
*   **Water Depth Above Road $= 0.15\text{m}$**: Caution speed threshold ($50\%$ velocity reduction) for standard and scout cars.
*   **Water Depth Above Road $= 0.30\text{m}$**: Stall/blockage clearance for standard and scout cars ($100\%$ blockage).
*   **Water Depth Above Road $= 8.00\text{m}$**: Maximum fording/navigation depth for high-water response trucks (`HIGH_WATER_TRUCK`) in flood/cyclone scenarios without physical blockage penalty.
*   **Water Depth Clearance = Unconstrained ($9999.0\text{m}$)**: Max depth clearance for water-native Zodiac boats (`ZODIAC_BOAT`), ensuring boats never stall in deep flood sinks while facing land speed penalties on dry segments ($< 2.0\text{m}$).
    *   *Citation*: Department of the Army. (2010). *Tactical Land Vehicle Operations (FM 21-305)*; FEMA. (2011). *FIA-30 Depth-Damage Curves*.


---

## 3. Decision Support System (DSS) Parameters

### 3.1 Bayesian Telemetry Model
*   **`sensor_base_accuracy` ($\eta$)**:
    *   *DRONE_CAMERA $= 0.96$*, *HUMAN_VISUAL $= 0.92$*, *SATELLITE_OPTICAL $= 0.81$*, *CITIZEN_REPORT $= 0.55$*.
    *   *Justification*: Ground truth correlation rates. Citizen reports have high false-alarm rates (approaching maximum uncertainty $0.50$), whereas drone camera feeds verify states with low error.
    *   *Citation*: Goodchild, M. F. (2007). Citizens as sensors: the world of volunteered geographic information. *GeoJournal*, 69(4), 211-221.

### 3.2 Dynamic Traffic Congestion Model
*   **BPR Parameters ($\alpha = 0.15, \beta = 4.0$)**:
    *   *Justification*: Standard parameters calibrated by the Bureau of Public Roads (BPR) to represent the velocity degradation of traffic networks as volume approaches capacity.
    *   *Citation*: Bureau of Public Roads. (1964). *Traffic Assignment Manual*. U.S. Department of Commerce.

---

## 4. Execution Governance Layer (EGL) Parameters

### 4.1 Epistemic Readiness ($\epsilon$) Parameter Weights
*   **Weights Configuration**: $w_\delta = 0.15$ (source diversity). Remaining weight $0.85$ is distributed proportional to the existing UncertaintyEngine weight assumptions (40/35/25 split):
    - $w_c = 0.85 \times 0.40 = 0.34$ (observation confidence)
    - $w_a = 0.85 \times 0.35 = 0.2975$ (temporal age)
    - $w_s = 0.85 \times 0.25 = 0.2125$ (spatial consistency)
*   **Derivation & Boundary Calibration**:
    The readiness index represents a convex combination of information sources. The weights reflect the relative entropy contribution of each channel.
    
    If $w_\delta$ (source diversity) is set to $0.20$, the remaining baseline channels shrink to $0.80$. During initial deployment phases, where only a single source type (e.g., aerial reconnaissance) is active, $\delta$ is $0.0$. In this scenario, the maximum possible epistemic readiness is capped at:
    
    $$\epsilon_{\text{max}} = 0.80$$
    
    This artificial ceiling pushes the decision rule into `DEFER` or `ESCALATE` for all dispatches, causing resource starvation. 
    
    Conversely, if $w_\delta$ is configured below $0.10$, the system fails to penalize redundant observations, leaving it vulnerable to confirmation bias (e.g., three separate drone feeds of the same damaged road segment). 
    
    A weight of $w_\delta = 0.15$ is the analytical saddle point that penalizes correlated evidence without inducing resource starvation.

### 4.2 Regret Cost Multipliers
*   **`C_golden_hour = 2.0`**:
    *   *Justification*: Based on clinical trauma data showing that survival probability halves if definitive care is delayed beyond $60$ minutes. The cost of delay is weighted twice as high as information errors (`C_info_wrong = 1.0`).
    *   *Citation*: Cowley, R. A., Hudson, F., & Gill, W. (1971). An economical and proved methodology for the management of thoracic and abdominal trauma. *Journal of Trauma*, 11(11), 903-910.
*   **`C_route_closure = 1.5`**:
    *   *Justification*: Represents the hazard-progression risk cost of a route becoming impassable during transit, requiring rerouting. Weighted at $1.5$ times the cost of bad information to account for fuel and time losses.
    *   *Citation*: Incident Command System (ICS) Operational Guidelines, FEMA Document P-1035.

### 4.3 Time-Boxed Human Override (TBHO) Countdowns & Regret-Minimizing Fallbacks
*   **Timeouts**: $30\text{s}$ (Golden Hour), $60\text{s}$ (Sustained), $90\text{s}$ (Recovery).
    *   *Justification*: Emergency response cognitive load limits. Tactical decisions during active life-saving phases require tight loops ($30\text{s}$) to match survival probability drop-offs, scaling up during sustained ops to prevent decision-maker fatigue.
    *   *Citation*: National Fire Protection Association. (2020). *NFPA 1561: Standard on Emergency Services Incident Management System*.
*   **Timeout Regret-Minimizing Fallbacks**: On timeout without commander response, low-irreversibility actions ($I < 0.50$) default to `EXECUTE`. High-irreversibility actions ($I \ge 0.50$) evaluate competitive regrets: defaulting to `EXECUTE` if $R_{\text{wait}} > R_{\text{act}}$ (minimizing lives lost when delay risk exceeds acting risk), and `DEFER` otherwise.

