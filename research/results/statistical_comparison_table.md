# Statistical Comparison Table: Sentinel DSS (AMIS-RU) vs Baselines (Matched Seeds 0–9, N=10)

### Part 1: Survivor Extrication Rate (%) Comparison

| Disaster Scenario | Comparison Pair | Sentinel Mean | Baseline Mean | Absolute Diff | % Improvement | Paired Wilcoxon p-value | Significance (p < 0.05) | Cohen's d |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Mumbai 2005 Flood | Sentinel vs Baseline-A | 27.26% | 28.38% | -1.12 pp | -3.95% | p = 0.3535 | Not Significant (p ≥ 0.05) | d = -0.30 |
| Mumbai 2005 Flood | Sentinel vs Baseline-B | 27.26% | 23.34% | +3.92 pp | +16.79% | p = 0.0078 | **Significant (p < 0.05)** | d = 0.74 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Bhuj 2001 Earthquake | Sentinel vs Baseline-A | 35.24% | 35.24% | -0.01 pp | -0.02% | p = 0.6094 | Not Significant (p ≥ 0.05) | d = -0.00 |
| Bhuj 2001 Earthquake | Sentinel vs Baseline-B | 35.24% | 31.37% | +3.87 pp | +12.32% | p = 0.0020 | **Significant (p < 0.05)** | d = 3.65 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Nisarga 2020 Cyclone | Sentinel vs Baseline-A | 46.98% | 44.17% | +2.81 pp | +6.37% | p = 0.1895 | Not Significant (p ≥ 0.05) | d = 1.02 |
| Nisarga 2020 Cyclone | Sentinel vs Baseline-B | 46.98% | 38.64% | +8.34 pp | +21.59% | p = 0.0020 | **Significant (p < 0.05)** | d = 8.87 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Aarey 2018 Wildfire | Sentinel vs Baseline-A | 56.10% | 55.12% | +0.98 pp | +1.77% | p = 0.3594 | Not Significant (p ≥ 0.05) | d = 0.26 |
| Aarey 2018 Wildfire | Sentinel vs Baseline-B | 56.10% | 49.56% | +6.53 pp | +13.18% | p = 0.2246 | Not Significant (p ≥ 0.05) | d = 1.03 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

### Part 2: Vehicle Stall Events Comparison (Safety Metric)

> **Note on Cohen's d**: Where within-group variance is zero across seeds (e.g. Sentinel 0.6 vs Baseline-A 4.2 every seed), pooled standard deviation collapses to zero. Cohen's d is reported as `N/A (zero within-group variance)` alongside the exact absolute stall reduction and paired Wilcoxon p-value.

| Disaster Scenario | Comparison Pair | Sentinel Mean Stalls | Baseline Mean Stalls | Stall Reduction | Paired Wilcoxon p-value | Significance | Cohen's d |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| Mumbai 2005 Flood | Sentinel vs Baseline-A | 0.6 | 4.2 | -3.6 stalls | p = 0.0020 | **Significant (p < 0.01)** | N/A (zero variance) |
| Mumbai 2005 Flood | Sentinel vs Baseline-B | 0.6 | 108.4 | -107.8 stalls | p = 0.0020 | **Significant (p < 0.01)** | d = -0.46 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bhuj 2001 Earthquake | Sentinel vs Baseline-A | 122.4 | 668.6 | -546.2 stalls | p = 0.0020 | **Significant (p < 0.01)** | N/A (zero variance) |
| Bhuj 2001 Earthquake | Sentinel vs Baseline-B | 122.4 | 1515.6 | -1393.2 stalls | p = 0.0020 | **Significant (p < 0.01)** | N/A (zero variance) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Nisarga 2020 Cyclone | Sentinel vs Baseline-A | 0.0 | 0.0 | -0.0 stalls | p = 1.0000 | Not Significant (p ≥ 0.05) | d = 0.00 |
| Nisarga 2020 Cyclone | Sentinel vs Baseline-B | 0.0 | 0.0 | -0.0 stalls | p = 1.0000 | Not Significant (p ≥ 0.05) | d = 0.00 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Aarey 2018 Wildfire | Sentinel vs Baseline-A | 0.0 | 0.0 | -0.0 stalls | p = 1.0000 | Not Significant (p ≥ 0.05) | d = 0.00 |
| Aarey 2018 Wildfire | Sentinel vs Baseline-B | 0.0 | 0.0 | -0.0 stalls | p = 1.0000 | Not Significant (p ≥ 0.05) | d = 0.00 |
| --- | --- | --- | --- | --- | --- | --- | --- |
