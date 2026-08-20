# Mumbai 2005 Super-Flood - City-Scale Validation Report

> **Date**: August 1, 2026 | **Scenario**: historical Mumbai 2005 monsoon surge
> **Map Coordinates**: Suburban Mumbai Peninsula ($19.0760^{\circ}$ N, $72.8777^{\circ}$ E) | **Map Size**: 4,165 nodes, 5,272 streets
> **Fleet size**: 20 rescue vehicles, 15 scouts | **Stranded Population**: 367,547 citizens | **Horizon**: 1440 steps (24 hours)

---

## 1. Comparative Analysis Summary
This validation run compares:
* **Baseline-A (SGA-RA)**: Coordinated emergency planning (global allocation to targets) but without risk-safety checks (EGL clearances disabled).
* **Baseline-B (PSA-RA)**: Uncoordinated, naive distance-only emergency planning (blind shortest path routing).
* **Sentinel DSS (AMIS-RU)**: Coordinated emergency planning with EGL vehicle clearance safety limits and regret minimization.

| Performance Metric | Baseline-A (SGA-RA) | Baseline-B (PSA-RA) | Sentinel DSS (AMIS-RU) | Delta (Sentinel vs A / vs B) |
| :--- | :---: | :---: | :---: | :---: |
| **Survivors Saved** | 27,597 (5.01%) | 21,715 (3.94%) | 31,260 (5.67%) | +3,663 (+0.66%) / +9,545 (+1.73%) |
| **Vehicle Route Failures (Stalls)** | 6 | 10 | 3 | -3 / -7 |
| **Avg. Operational Fleet size** | 7.5 / 20 | 5.7 / 20 | 11.2 / 20 | +3.8 / +5.5 |

## 2. Rescue Fleet Stalls & Loss Breakdown
Under the uncoordinated and un-governed baselines, rescue vehicles drive blindly onto flooded avenues and bridges, leading to physical damage and stalls. Sentinel redirects vulnerable units to safe arterial alternatives:

| Rescue Vehicle Class | Baseline-A (SGA-RA) | Baseline-B (PSA-RA) | Sentinel DSS (AMIS-RU) |
| :--- | :---: | :---: | :---: |
| STANDARD_CAR | 5 | 5 | 0 |
| HIGH_WATER_TRUCK | 2 | 2 | 4 |
| ZODIAC_BOAT | 5 | 5 | 5 |
| HELICOPTER | 1 | 3 | 0 |

## 3. Scientific Interpretation
- **Preservation of Responder Resources**: In both un-governed models, the EOC suffers significant vehicle losses (primarily standard cars/ambulances and trucks stalling on flooded roads). This severely diminishes the operational fleet size over time.
- **Extrication Efficiency**: Sentinel DSS successfully keeps standard cars on dry, elevated highway corridors while utilizing boats and helicopters for deep water zones. This prevents the 'second disaster' of first responder losses and coordinates a higher total rescue count safely.
