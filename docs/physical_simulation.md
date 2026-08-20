# Physics & Disaster Simulation Models

Sentinel utilizes a physics-grounded, mathematical hazard propagation engine. It models the behavior of four distinct types of natural disasters and maps their physical impacts directly onto the traversal networks of the environment.

---

## 1. Seismic Hazards: Peak Ground Acceleration (PGA)

Seismic disruptions are calculated using the **Boore-Stewart-Seyhan-Atkinson 2014 (BSSA14)** Ground Motion Prediction Equation (GMPE). It estimates seismic shaking intensity at each node based on the epicenter distance and the geological Vs30 soil properties:

$$\ln(\text{PGA}) = f_S(M, R_{jb}, \theta) + f_D(V_{s30}, \text{PGA}_{\text{ref}})$$

Where:
*   $f_S$ is the source-to-site distance attenuation function.
*   $M$ represents earthquake magnitude ($M_w$).
*   $R_{jb}$ is the Joyner-Boore distance (closest horizontal distance to the fault projection, measured in km).
*   $f_D$ is the soil amplification factor, determined by geological $V_{s30}$ profiles. Low-elevation coastal nodes receive Vs30 corrections to model loose alluvial soils, amplifying Peak Ground Acceleration.

### Road Damage Calibration
If PGA values exceed $0.35g$ at any coordinate point, the segment's probability of structural blockage is modeled as:

$$P(\text{blocked}) = 1 - e^{-\alpha \cdot \text{PGA}}$$

---

## 2. Meteorological Hazards: Holland B Wind Profile

Gradient surface wind fields are modeled using the **Holland (1980)** tropical cyclone wind model:

$$V_g = \left[ \frac{A \cdot B \cdot (p_n - p_c) \cdot \exp(-A / r^B)}{\rho_a \cdot r^B} \right]^{0.5}$$

Where:
*   $p_n - p_c$ is the pressure deficit (ambient pressure minus the core pressure, in hPa).
*   $r$ is the radial distance to the eyewall center in meters.
*   $\rho_a$ is the density of ambient air ($1.15\text{ kg/m}^3$).
*   $B$ is the Holland shape parameter, dynamically calculated as:
    $$B = 1.5 + \frac{980 - p_c}{120}$$
*   $A$ is scaling parameter $A = R_{\text{max}}^B$, where $R_{\text{max}}$ is the radius of maximum wind speed.

### Wind Impact
Wind velocities attenuate with landfall distance. High wind gusts above $80\text{ km/h}$ create structural obstructions (downed powerlines, flying debris) on standard roadways.

---

## 3. Wildfires: Rothermel Rate of Spread (ROS)

Fire boundary propagation rates are calculated using the **Rothermel (1972)** fuel bed model:

$$R = \frac{I_r \cdot \xi \cdot (1 + \Phi_w + \Phi_s)}{\rho_b \cdot \epsilon_f \cdot Q_{ig}}$$

Where:
*   $I_r$ is the reaction intensity of fuel types (calibrated to USDA fuel models).
*   $\xi$ is the propagating flux ratio.
*   $\Phi_w$ is the wind multiplier scaling with wind speed: $\Phi_w = C \cdot U^B \cdot (\beta / \beta_{op})^{-E}$.
*   $\Phi_s$ is the slope multiplier, modeling vertical convection biases: $\Phi_s = 5.275 \cdot \beta^{2} \cdot \tan(\phi)^2$.
*   $\rho_b$ is the fuel bulk density, and $Q_{ig}$ is the heat of pre-ignition.

Road blockages occur when active fire fronts intersect graph segments, increasing danger levels and blocking routes for non-aerial vehicles.

---

## 4. Hydrological Hazards: Flood Water Depth

Flood water levels at each node accumulate based on the Topographic Wetness Index (TWI) and the watershed's drainage efficiency:

$$h_t = h_{t-1} + \left( P_{\text{rain}} \cdot \text{TWI} - D_{\text{drain}} \right) \cdot \Delta t$$

### Vehicle Traversability & Depth-Above-Road Evaluation
Water accumulation affects vehicle speeds based on **water depth above road surface** ($h_{\text{above\_road}} = \max(0.0, h_{\text{node}} - \text{elevation}_{\text{node}})$), which is unified across routing, engine movement, allocation, and safety governance:

*   **Standard Cars (`STANDARD_CAR`)**: Caution speed factor kicks in at $0.15\text{m}$. Blocked/stalled when $h_{\text{above\_road}} > 0.30\text{m}$.
*   **Scout Cars (`SCOUT_CAR`)**: Fast reconnaissance unit. Caution at $0.15\text{m}$, blocked when $h_{\text{above\_road}} > 0.30\text{m}$.
*   **High-Water Trucks (`HIGH_WATER_TRUCK`)**: Designed for deep water navigation up to $8.0\text{m}$ clearance in flood/cyclone scenarios without physical blockage penalty.
*   **Zodiac Boats (`ZODIAC_BOAT`)**: Water-native craft. Max water depth clearance is unconstrained ($9999.0\text{m}$), ensuring boats never stall in deep flood sinks while facing speed penalties on dry segments ($< 2.0\text{m}$).
*   **Helicopters (`HELICOPTER`)**: Airborne. Ignores all road surface blockages and flood depths.


---

## 5. Physical Constants and Parameters Calibration

All environmental constants, failure thresholds (such as the $0.35g$ PGA ground-cracking boundary and the $80\text{ km/h}$ wind gust grounding limits), and vehicle clearances are mapped and justified with geotechnical and aviation literature in [Parameter Provenance Guide](file:///c:/Users/dorni/OneDrive/Desktop/project/docs/parameter_provenance.md).
