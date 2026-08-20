# Per-Scenario Validation Comparison Table (Seeds 0–9, N=10 per Scenario x System)

> **Methodological & Metric Unification Note**: In the simulation engine, Vehicle Stall Events and Route Failures represent the exact same single underlying physical metric (`engine.route_failures`). 'Vehicle Stall Events' is used as the single canonical safety metric across all evaluations.

| Disaster Scenario | System Model | Survivor Saved % (Mean ± SD) | 95% Confidence Interval (Student-t, df=9) | Vehicle Stall Events (Mean ± SD) | Time to First Rescue (min) | Rescue Trips Completed | Fleet Distance (km) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| Mumbai 2005 Flood | **Sentinel (AMIS-RU)** | 27.26% ± 3.42% | [24.81%, 29.71%] | 0.6 ± 0.0 | 3.0 m | 1867.4 | 2143.7 km |
| Mumbai 2005 Flood | Baseline-A (SGA-RA) | 28.38% ± 3.96% | [25.55%, 31.21%] | 4.2 ± 0.0 | 2.4 m | 1834.8 | 1948.0 km |
| Mumbai 2005 Flood | Baseline-B (PSA-RA) | 23.34% ± 6.64% | [18.59%, 28.09%] | 108.4 ± 330.1 | 1.5 m | 2890.1 | 1379.8 km |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bhuj 2001 Earthquake | **Sentinel (AMIS-RU)** | 35.24% ± 1.47% | [34.18%, 36.29%] | 122.4 ± 0.0 | 2.7 m | 2080.0 | 2270.3 km |
| Bhuj 2001 Earthquake | Baseline-A (SGA-RA) | 35.24% ± 1.71% | [34.02%, 36.47%] | 668.6 ± 0.0 | 2.7 m | 2059.6 | 1895.8 km |
| Bhuj 2001 Earthquake | Baseline-B (PSA-RA) | 31.37% ± 0.29% | [31.17%, 31.58%] | 1515.6 ± 0.0 | 1.9 m | 2011.6 | 1168.5 km |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Nisarga 2020 Cyclone | **Sentinel (AMIS-RU)** | 46.98% ± 1.22% | [46.11%, 47.85%] | 0.0 ± 0.0 | 2.5 m | 2412.8 | 5790.3 km |
| Nisarga 2020 Cyclone | Baseline-A (SGA-RA) | 44.17% ± 3.72% | [41.51%, 46.82%] | 0.0 ± 0.0 | 2.2 m | 2428.4 | 6255.1 km |
| Nisarga 2020 Cyclone | Baseline-B (PSA-RA) | 38.64% ± 0.54% | [38.25%, 39.02%] | 0.0 ± 0.0 | 1.3 m | 2568.0 | 2170.4 km |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Aarey 2018 Wildfire | **Sentinel (AMIS-RU)** | 56.10% ± 4.42% | [52.93%, 59.26%] | 0.0 ± 0.0 | 1.5 m | 2875.6 | 5531.2 km |
| Aarey 2018 Wildfire | Baseline-A (SGA-RA) | 55.12% ± 3.11% | [52.90%, 57.34%] | 0.0 ± 0.0 | 1.4 m | 2893.4 | 4193.4 km |
| Aarey 2018 Wildfire | Baseline-B (PSA-RA) | 49.56% ± 7.79% | [43.99%, 55.14%] | 0.0 ± 0.0 | 1.1 m | 2952.8 | 2569.5 km |
| --- | --- | --- | --- | --- | --- | --- | --- |

### 📌 Empirical Callout: Mumbai Baseline-B Seed 5 Stochastic Anomaly
- **Full 10-Seed Benchmark (Mumbai Baseline-B)**: Mean = $23.34\% \pm 6.64\%$ survivor rate, **$108.4 \pm 330.1$ stalls/run** ($1,084$ total stalls across 10 runs).
- **Empirical Anomaly Analysis**: Seed 5 represents a legitimate stochastic extreme run where un-governed Baseline-B rescue vehicles entered an infinite rerouting deadlock loop in deep flood waters, recording $1,048$ stalls, $8,905$ trip attempts, $0.0$ km travel, and a $6.29\%$ survivor rate.
- **Trimmed Benchmark ($N=9$, excluding Seed 5)**: Across seeds 0–4 and 6–9, Baseline-B achieves a mean of **$4.0 \pm 0.0$ stalls/run** and a **$25.24\% \pm 3.12\%$ survivor rate** ($2,221.8$ trips, $1,533.2$ km distance).
- **Sentinel DSS Stability**: Sentinel (AMIS-RU) maintains **$0.6 \pm 0.0$ stalls/run** ($27.26\%$ survivor rate) consistently across all 10 seeds, demonstrating safety governance resilience against dynamic rerouting collapse.
