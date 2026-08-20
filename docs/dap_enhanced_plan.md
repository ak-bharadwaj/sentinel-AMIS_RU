# DAP Enhanced Design: Brainstorm, Ethics, Real-World Acceptability & Improved Architecture

---

## 1. HIGH-LEVEL BRAINSTORM

### What DAP v1 Gets Right
- **Post-optimizer gate** is architecturally sound — it cleanly separates *what to do* (NSGA-II/GEVA/OKV) from *whether to do it now*. This is the right separation of concerns.
- **Regret framing** (R_act vs R_wait) is elegant — it avoids the "action bias" trap where systems always prefer doing something.
- **Irreversibility scaling** is practically very important and often ignored in DSS literature.
- **Phase adaptation** (Golden Hour → Sustained → Recovery) reflects real emergency management practice.
- **Hard vetoes** are non-negotiable safety rails and are correctly placed above all math.
- **P2P blackout sync** is a novel real-world modelling insight.

### Where the Original Plan Has Gaps

| Gap | Problem | Proposed Fix |
|:---|:---|:---|
| **Open Q: Moral weights hardcoded** | `crew_lost_cost = 3.0` encodes a designer's value judgment | Expose as EOC-configurable params (resolved below) |
| **Open Q: Correlated observations** | Multiple scouts see same flood — evidence isn't independent | Source Diversity Index `δ` sub-dimension added to ε |
| **No audit trail / explainability hook** | If DAP DEFERs a rescue and someone dies, who is accountable? | DAPResult must write to append-only audit log |
| **No human override feedback loop** | ESCALATE just logs and stops — EOC has no mechanism to override | Human Override API endpoint + DAP learns from EOC decisions |
| **κ is binary-ish** | Blackout zones are modelled simply — no partial degradation | Multi-tier comms model (satphone / radio / LTE / none) |
| **No cascading DEFER handling** | Repeated DEFERs can cause "analysis paralysis" starvation | DEFER timeout → force ESCALATE after N ticks |
| **No inter-agent DAP coordination** | Agent A defers a rescue, Agent B dispatches to same node — redundant | Fleet-level DAP lock per target node |
| **Regret-of-waiting doesn't model route closure speed** | W is binary (worsening/not) — but roads close gradually | Probabilistic route degradation function replaces binary W |
| **No trust score for sensor source** | Drone observation vs. unverified civilian report treated equally | Sensor provenance weight `τ` in ε calculation |
| **No feedback loop — DAP doesn't learn** | Same bad parameter set is used forever | Optional Bayesian parameter updating from outcome data |

---

## 2. Open Questions Resolved

### 2.1 Moral Weight Calibration

**Question:** Should `crew_lost_cost` and `mu_act` be EOC-configurable?

**Answer:** Exposure of weights as a configurable parameter is required to align the Decision Support System with the moral accountability boundaries of the operating agency. Value weights are configurations representing human policy choices, not mathematical constants. The EPM implements distinct default profiles that are loaded under commander authorization:

| Profile | `C_crew_lost` | `mu_wait` boost | Use Case |
|:---|:---|:---|:---|
| **Crew-Conservative** | 5.0 | ×0.8 | High-risk environments, crew safety paramount |
| **Balanced (Default)** | 3.0 | ×1.0 | Standard multi-victim incidents |
| **Civilian-Priority** | 1.5 | ×1.8 | Mass casualty events where civilian lives dominate |
| **Custom** | User-set | User-set | Mission command override |

These profiles must be:
1. Logged with a timestamp and authorizing officer ID when changed
2. Immutable during active dispatch (changes take effect on next planning cycle)
3. Shown visibly on the EOC dashboard so operators know which ethical mode is active

### 2.2 Correlated Observations and Source Diversity Index (δ)

**Original question:** *Multiple scouts seeing the same flood provide correlated evidence — ε doesn't discount for this.*

**Answer: Add `δ` (Source Diversity Index) as a sub-dimension of ε.**

$$\delta = 1 - \frac{\text{max\_count\_from\_any\_single\_source\_type}}{\text{total\_observations}}$$

If 3 drone cameras all saw the same flood → δ = 1 - 3/3 = 0.0 (zero diversity, correlated).
If 1 drone + 1 satellite + 1 human → δ = 1 - 1/3 = 0.67 (diverse, partially independent).

Updated ε formula:
$$\varepsilon_{\text{node}} = w_c \cdot \text{conf}(n) + w_a \cdot e^{-\lambda_a \cdot \text{age}(n)} + w_s \cdot \text{consistency}(n) + w_\delta \cdot \delta(n)$$

With $w_c = 0.35, w_a = 0.30, w_s = 0.20, w_\delta = 0.15$.

This directly plugs into the existing `UncertaintyEngine` — observations already track their source type in `pending_observations`.

---

## 3. ETHICAL ANALYSIS

### 3.1 The Core Ethical Tension

DAP makes **life-and-death decisions algorithmically** in a domain where:
- Mistakes are irreversible (people die)
- The affected population cannot consent to the algorithm
- Accountability is diffuse (who is responsible for a DEFER that leads to death?)
- Edge cases are unpredictable (no algorithm covers all disaster scenarios)

This places DAP squarely in the category of **high-stakes algorithmic decision systems** covered by:
- EU AI Act (High-Risk AI, Annex III) — requires human oversight, explainability, audit trails
- ISO 9001 / IEC 62061 — safety-critical system standards
- Emergency Management ethics frameworks (IAEM Code of Ethics)

### 3.2 Ethical Issues in DAP v1 and Mitigations

#### Issue 1: Hardcoded Value Judgments (`C_crew_lost = 3.0`)
**Problem:** Saying "a crew member's life is worth 3× a resource" is a profound moral claim. If wrong, the algorithm systematically under- or over-values human life.

**Mitigation:** EOC Ethical Profiles (§2.1). Weights must be set by humans, not defaults. Log every change.

---

#### Issue 2: ESCALATE is a Dead End
**Problem:** The original plan says ESCALATE → "log XAI event, skip dispatch." But in a real disaster, skipping a dispatch **is** a life-or-death decision. There must be a human-in-the-loop path.

**Mitigation:** ESCALATE triggers an **active human override request** in the EOC dashboard with a countdown timer. If the EOC officer does not respond within N seconds, the system falls back to a safe default (DEFER for high-irreversibility, EXECUTE for scout-level actions). This is called **Time-Boxed Human Override (TBHO)**.

---

#### Issue 3: Analysis Paralysis / DEFER Starvation
**Problem:** A node that repeatedly gets DEFER'd (because R_act is always slightly above R_wait + m) could effectively be abandoned. Meanwhile, the golden hour expires.

**Mitigation:** **DEFER Decay Rule** — each consecutive DEFER on the same target node decrements the decision margin m by 0.02 per tick. After 5 DEFERs, m reaches 0.05, making EXECUTE much more likely. After 8 consecutive DEFERs → force ESCALATE.

---

#### Issue 4: Algorithmic Bias Toward Accessible Nodes
**Problem:** Nodes with high `reachability` scores will always win the R_wait calculation. Remote, isolated communities might consistently score lower → systematically under-served.

**Mitigation:** Add an **Access Equity Multiplier (AEM)** to R_wait. Nodes with poor road access (low reachability) get a corrective urgency boost to prevent systematic under-allocation to marginalized communities.

$$\text{AEM}(n) = 1 + 0.3 \times (1 - \text{reachability}(n))$$

This is both ethically correct and practically sound — isolated populations have no self-evacuation option.

---

#### Issue 5: No Accountability Trail
**Problem:** If DAP decides DEFER and a person dies, who is accountable? The algorithm? The designer? The operator?

**Mitigation:** Every DAPResult must be written to an **append-only forensic audit log** with:
- Timestamp (UTC + local)
- Agent ID + target node
- All dimension scores (ε, σ, κ, ρ, δ)
- R_act, R_wait, outcome
- Phase, ethical profile name, officer ID
- Human override (if any)

This log is never deleted and is exportable for post-incident review.

---

#### Issue 6: Operator Trust Calibration
**Problem:** If operators always override DAP's DEFER decisions, the system becomes useless. If they always blindly follow it, it creates automation complacency.

**Mitigation:** Track an **Override Rate** metric per operator session. If > 40% of DAP decisions are overridden in a session, trigger a calibration alert: *"High override rate detected — consider adjusting Ethical Profile or consulting system administrator."*

---

## 4. REAL-WORLD ACCEPTABILITY ANALYSIS

### 4.1 Does DAP Match How Real Emergency Commanders Think?

Real commanders use **Recognition-Primed Decision (RPD)** — pattern matching, not optimization. They ask:
1. *"Is this situation typical enough to recognize?"* → DAP's phase detection addresses this
2. *"Will my first-guess action work?"* → DAP validates this (it IS a mental simulation formalized)
3. *"If not, what's the modification?"* → DEFER/ESCALATE provides this

**Verdict: DAP aligns well with RPD.** The key is that DAP must be transparent enough that commanders can understand WHY it decides DEFER. The `rationale` field in DAPResult is critical here.

### 4.2 Real-World Gaps in DAP v1

| Gap | Real-World Impact | Fix |
|:---|:---|:---|
| **No radio / comms tier model** | κ treats blackout as binary — real comms degrade gradually | Multi-tier κ (§5.3 below) |
| **No fatigue model for crew** | `crew_lost_cost` doesn't rise as crew gets tired | Crew fatigue factor linked to simulation elapsed time |
| **No weather uncertainty in σ** | Route danger `d_max` doesn't account for forecasted weather | Integrate weather forecast into `p_danger` before σ calculation |
| **No multi-agent conflict** | Two agents could both EXECUTE to same target | Fleet-level mutex per target node |
| **DEFER doesn't trigger anything** | Original plan: DEFER → "push to OKV scout queue." But OKV is not always running | DEFER must explicitly enqueue a scout request with priority tag |
| **No partial execution** | Binary: EXECUTE or not. But what about "go halfway and reassess"? | **Staged Dispatch** mode for high-irreversibility actions |
| **No degraded mode** | If DAP module crashes, system halts dispatch entirely | **Fail-safe default**: if DAP unavailable, use legacy greedy dispatch |

### 4.3 Acceptance by Emergency Management Authorities

For DAP to be accepted by real EMAs (Emergency Management Agencies), it needs:

1. **Explainability in plain English** — not math. The `rationale` field must generate sentences like: *"DEFER: Road confidence is only 42% on Segment 7. Waiting 5 minutes for Scout-3 to confirm reduces crew risk from 68% to estimated 22%."*

2. **Manual override is always one click away** — no confirmation dialogs for overrides in an emergency.

3. **Graceful degradation** — if DAP disagrees with a human decision, it logs but complies. It never blocks a human command.

4. **Calibration period** — new deployments should run DAP in "shadow mode" (recommendations logged but not enforced) for the first simulation run.

---

## 5. DAP v2 — ENHANCED ARCHITECTURE

### 5.1 New Dimension: δ — Source Diversity Index

Already described in §2.2. Plugs into `UncertaintyEngine`. Weight: 0.15 in ε.

### 5.2 New Sub-Dimension: τ — Sensor Provenance Trust

Not all observations are equal:

| Source Type | Trust Weight `τ` |
|:---|:---|
| Satellite SAR (verified) | 1.0 |
| UAV with camera (DRONE_CAMERA) | 0.96 |
| Human visual (trained responder) | 0.92 |
| Satellite optical | 0.81 |
| Unverified civilian report | 0.45 |
| Algorithmic inference (MRF propagation) | 0.30 |

$$\varepsilon_{\text{node}} = w_c \cdot \text{conf}(n) \cdot \tau_{\text{avg}} + w_a \cdot e^{-\lambda_a \cdot \text{age}(n)} + w_s \cdot \text{consistency}(n) + w_\delta \cdot \delta(n)$$

Where $\tau_{\text{avg}}$ is the average trust weight across all observations for node `n`.

This directly uses the `sensor_config.json` already in the codebase.

### 5.3 Enhanced κ — Multi-Tier Communications Model

Replace binary blackout with a tiered model:

| Comms Level | κ Factor | Condition |
|:---|:---|:---|
| **Full LTE/Satellite** | 1.0 | Normal operations |
| **Radio (VHF/UHF)** | 0.75 | LTE down, radio functional |
| **Satphone only** | 0.55 | Radio down, satphone available |
| **P2P Mesh only** | 0.35 | All infrastructure down, only agent-to-agent |
| **Total blackout** | 0.10 | Complete comms loss (still allow emergency beacon) |

$$\kappa = \text{comms\_tier\_factor} \times (1 - B_{\text{route}}) \times R_f$$

### 5.4 Access Equity Multiplier (AEM) in R_wait

As described in §3.2 Issue 4:

$$\mathcal{R}_{\text{wait}} = \mu_{\text{wait}} \times \text{AEM}(n) \times \Big[\dot{D} \times \Delta t + W \times C_{\text{route\_closure}} + G \times C_{\text{golden\_hour}}\Big]$$

### 5.5 Probabilistic Route Closure (replacing binary W)

Replace binary worsening indicator with a probabilistic model:

$$W_{\text{prob}} = \frac{1}{|\mathcal{P}|} \sum_{e_i \in \mathcal{P}} P(\text{closure}_{e_i, T+15})$$

Where $P(\text{closure}_{e_i, T+15})$ comes from the disaster propagation model (flood.py / earthquake.py). This is more realistic — routes don't snap from "fine" to "closed," they have closure probabilities.

### 5.6 DEFER Decay Rule (Anti-Starvation)

Track `defer_count[target_node]` in simulation state:

```
effective_m = max(0.03, 0.15 - 0.02 × defer_count[target])
if defer_count[target] >= 8: force ESCALATE
```

### 5.7 Time-Boxed Human Override (TBHO)

When DAP returns ESCALATE:

1. Frontend receives a `DAP_ESCALATE` event with full dimension breakdown
2. EOC dashboard shows a **countdown timer** (configurable: 30–120 seconds)
3. Officer can:
   - **APPROVE EXECUTE** — overrides DAP, logged with officer ID
   - **CONFIRM DEFER** — officer agrees, logged
   - **TIMEOUT** — system applies safe default based on irreversibility:
     - I < 0.5 → EXECUTE (scout/recon level)
     - I >= 0.5 → DEFER (rescue/evacuation level)

### 5.8 Fleet-Level Mutex (Anti-Redundancy)

DAP maintains a `active_dispatch_targets: Set[str]` at the fleet level. Before any EXECUTE:

```python
if target_node in self.active_dispatch_targets:
    # Another agent is already dispatched — DEFER this one
    return DAPResult(outcome="DEFER", vetoed_by="FLEET_MUTEX", ...)
self.active_dispatch_targets.add(target_node)
```

### 5.9 Staged Dispatch (for High-Irreversibility)

For actions with I >= 0.70 (helicopter airlift, mass evacuation), introduce an intermediate state:

**STAGED_EXECUTE**: Agent moves to a staging point (e.g., 30% of the route) and pauses for confirmation. DAP re-evaluates with fresher data before committing to the full action.

```
STAGED_EXECUTE → [agent moves to staging point] → DAP re-evaluates → EXECUTE or ABORT
```

### 5.10 Shadow Mode (Calibration)

Add a `shadow_mode: bool` flag to DAP. In shadow mode:
- DAP computes all decisions normally
- Results are logged with `shadow=True`
- Actual dispatch uses legacy greedy allocator
- After shadow run, generate a comparison report showing what DAP would have done differently

---

## 6. UPDATED FILE CHANGES

### [NEW] `backend/decision_engine/dap.py`

**`DAPConfig`** dataclass (EOC-configurable):
- `ethical_profile: str` (CREW_CONSERVATIVE / BALANCED / CIVILIAN_PRIORITY / CUSTOM)
- `c_crew_lost: float`
- `mu_wait_boost: float`
- `decision_margin_base: float`
- `tbho_timeout_seconds: int`
- `shadow_mode: bool`
- `authorizing_officer_id: str`

**`DAPResult`** dataclass (expanded from v1):
- `outcome: Literal["EXECUTE", "DEFER", "ESCALATE", "STAGED_EXECUTE"]`
- `composite_score: float`
- `regret_act: float`, `regret_wait: float`
- `epsilon, sigma, kappa, rho, delta: float` (5 dimensions now)
- `tau_avg: float` (sensor provenance trust)
- `aem: float` (access equity multiplier)
- `irreversibility: float`
- `vetoed_by: Optional[str]`
- `rationale: str` (human-readable, plain English)
- `rationale_technical: str` (full math breakdown for logs)
- `phase: str`
- `defer_count: int`
- `shadow: bool`

**`DecisionAdequacyProtocol`** class (v2):
- All v1 methods, plus:
- `_source_diversity_index(target, observations) → float` (δ)
- `_sensor_provenance_trust(target, observations) → float` (τ)
- `_comms_tier(route, blackout_zones, comms_infrastructure) → float` (enhanced κ)
- `_access_equity_multiplier(target, graph) → float` (AEM)
- `_probabilistic_route_closure(route, forecasts, graph) → float` (W_prob)
- `_check_fleet_mutex(target, active_dispatches) → bool`
- `_apply_defer_decay(target, defer_counts) → float` (effective m)
- `_generate_plain_english_rationale(scores, outcome) → str`
- `_write_audit_log(result, agent, target, sim_time, officer_id) → None`

### [MODIFY] `backend/agents/coordinator.py`
- Import `DecisionAdequacyProtocol`, `DAPConfig`
- Accept `fleet_config`, `comms_infrastructure`, `ethical_profile` as inputs
- In `assign_rescues()`: DAP gate after GEVA ranking
  - EXECUTE → dispatch normally + add to `active_dispatch_targets`
  - STAGED_EXECUTE → dispatch to staging node only
  - DEFER → push to OKV scout queue + increment defer_count[target]
  - ESCALATE → emit TBHO event to frontend
- In `assign_scouts()`: DAP gate with I=0.15
- Track `active_dispatch_targets: Set[str]` and `defer_counts: Dict[str, int]`

### [MODIFY] `backend/simulation/engine.py`
- Pass `blackout_zones`, `forecasts_15_30_60`, `simulation_time`, `fleet_state`, `comms_infrastructure`, `ethical_profile` to coordinator
- In blackout check loop: P2P comms sync (unchanged from v1)
- Store `dap_results` per-agent for frontend
- If `shadow_mode`: run both DAP and legacy dispatch, log comparison

### [MODIFY] `backend/agents/base_agent.py`
- Add `pending_observations_from: List[str]` (P2P provenance)
- Add `staged_dispatch_target: Optional[str]` (for STAGED_EXECUTE)
- Add `staging_node: Optional[str]`

### [NEW] `backend/decision_engine/dap_audit.py`
- `DAPAuditLogger` class with append-only SQLite write
- Schema: `(id, timestamp_utc, agent_id, target_node, outcome, epsilon, sigma, kappa, rho, delta, r_act, r_wait, phase, ethical_profile, officer_id, shadow, rationale)`
- `export_to_csv(start_time, end_time) → str` for post-incident review

### [NEW] `backend/api/dap_config_api.py`
- `GET /api/dap/config` → returns current DAPConfig
- `POST /api/dap/config` → updates ethical profile (requires officer_id)
- `GET /api/dap/audit` → returns recent audit log entries
- `POST /api/dap/override` → human override for ESCALATE decisions (TBHO response)

---

## 7. UPDATED VERIFICATION PLAN

### Unit Tests (pytest)

```bash
venv\Scripts\python -m pytest tests/test_dap.py -v
```

Test cases from v1 (all 7) + new:

8. **Source diversity:** 3 drone observations → δ ≈ 0 → lower ε than mixed-source
9. **Sensor provenance:** civilian report vs satellite → civilian gets 0.45τ, lowers ε
10. **Multi-tier comms:** radio-only route → κ = 0.75 × (1 - B_route) × R_f
11. **DEFER decay:** 8 consecutive DEFERs → forced ESCALATE regardless of regret
12. **Fleet mutex:** second agent targeting same active node → DEFER
13. **AEM boost:** low-reachability isolated community → AEM > 1.0, R_wait increases
14. **TBHO timeout:** ESCALATE + no override within timeout → safe default applies
15. **Staged dispatch:** helicopter airlift (I=0.75) → STAGED_EXECUTE, not EXECUTE
16. **Audit log:** every DAPResult writes to SQLite, exportable to CSV
17. **Shadow mode:** DAP runs without affecting dispatch, comparison logged
18. **Ethical profile switch:** changing profile logs with officer_id, takes effect next cycle

### Integration Tests
- Full simulation run: verify DAP decisions in XAI event log
- DEFER → OKV scout queue: confirm scout is dispatched to deferred node
- ESCALATE → TBHO: confirm frontend receives event with countdown
- Override flow: officer approves execute, audit log records override

---

## 8. IMPLEMENTATION PRIORITY ORDER

| Priority | Task | Why |
|:---|:---|:---|
| 🔴 P0 | `dap.py` core v2 (all dimensions + regret rule) | The whole thing depends on this |
| 🔴 P0 | `dap_audit.py` + audit logging | Ethical/legal requirement |
| 🟠 P1 | Coordinator integration (EXECUTE/DEFER/ESCALATE gates) | Core functionality |
| 🟠 P1 | EOC Ethical Profiles + `dap_config_api.py` | Human control over value weights |
| 🟡 P2 | TBHO frontend event + countdown UI | Human-in-the-loop |
| 🟡 P2 | Fleet mutex + DEFER decay | Anti-starvation, anti-redundancy |
| 🟢 P3 | Staged dispatch (STAGED_EXECUTE) | High-value but complex |
| 🟢 P3 | Shadow mode + comparison report | Calibration / research |
| 🟢 P3 | Multi-tier κ comms model | Realism improvement |

---

## 9. OPEN QUESTIONS (REMAINING)

> [!IMPORTANT]
> **TBHO Timeout Duration:** What is the right timeout for a human override request? 30 seconds is realistic for a field commander. 120 seconds might be too long during a golden hour situation. Recommend 45 seconds as default, configurable per mission profile.

> [!IMPORTANT]
> **Staged Dispatch node selection:** For STAGED_EXECUTE, what defines the "staging node"? Proposal: the node at 30% of route distance from current position. Needs validation against real route topologies.

> [!NOTE]
> **Bayesian DAP parameter learning:** Should DAP update its internal cost weights (C_crew_lost, etc.) based on outcome data from previous incidents? This would make DAP a learning system — powerful but raises new accountability questions. Recommend keeping this as future work (DAP v3).

> [!NOTE]
> **P2P comms sync timing:** Original plan syncs when agents share `current_node`. In practice, agents may be nearby but not at the exact same node. Should we add a radius-based sync trigger (e.g., within 200m of each other)?
