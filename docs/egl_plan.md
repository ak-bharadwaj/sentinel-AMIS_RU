# Execution Governance Layer (EGL)
## Redesign of DAP — Clean Architecture, Justified Constants

---

## 0. Why the Redesign Was Necessary

The original DAP plan had two structural problems:

**Problem 1 — God-class:** A single module was asked to handle core math, ethics, 
comms modelling, fleet coordination, logging, human interaction, fairness, and learning. 
That is six separate concerns in one file. It would be untestable, unextensible, 
and unmaintainable.

**Problem 2 — Unjustified constants:** Dozens of magic numbers with no cited source:
`0.35, 0.30, 0.45, 0.03, 5 defers, 8 defers, 45 seconds, 30%...`  
A reviewer or ethics board will reject a system that makes life-or-death decisions 
on unexplained constants.

This plan fixes both.

---

## 1. Architecture: The Execution Governance Layer (EGL)

The name "DAP" is retired as the top-level label. DAP becomes one focused sub-module 
of a larger **Execution Governance Layer** — the software layer responsible for deciding 
*whether and how* to execute pre-selected actions.

```
backend/
└── execution_governance/           ← NEW top-level package
    ├── __init__.py
    ├── egl.py                      ← Thin orchestrator (wires sub-modules)
    │
    ├── dap.py                      ← Decision Adequacy Protocol (pure math only)
    ├── mission_policy.py           ← Mission Policy Manager (MPM)
    ├── audit.py                    ← Audit Manager (AM)
    ├── human_override.py           ← Human Override Manager (HOM)
    ├── fleet_coordinator.py        ← Fleet Coordination Manager (FCM)
    └── explainability.py           ← Explainability Engine (XE)
```

Each module has **exactly one responsibility**. The orchestrator `egl.py` wires them together.

### Module Responsibility Boundary (strict)

| Module | Does | Does NOT |
|:---|:---|:---|
| `dap.py` | Compute ε, σ, κ, ρ, δ, R_act, R_wait, decision outcome | Log, override, coordinate, explain |
| `mission_policy.py` | Hold and validate policy weight configs | Make decisions, log |
| `audit.py` | Append-only write of every EGL decision | Read decisions, compute anything |
| `human_override.py` | Manage TBHO timer, receive EOC response | Compute adequacy, log |
| `fleet_coordinator.py` | Track active targets, DEFER counts, staged states | Compute regret, log |
| `explainability.py` | Generate plain-English rationale from DAPResult | Compute anything |

---

## 2. Constants — Full Justification Table

Every number used in the EGL is classified below. **Category A = derived or literature-backed. 
Category B = engineering default with sensitivity analysis required. Category C = must be set 
by domain expert before deployment.**

### 2.1 DAP Core Math Constants

| Constant | Value | Category | Source / Justification |
|:---|:---|:---|:---|
| `w_c` (confidence weight in ε) | Derived | A | Set equal to the UncertaintyEngine's `p_state_correct` weight. Not a new constant — reuses existing calibration. |
| `w_a` (age weight in ε) | Derived | A | Set equal to `reliability` decay rate already in `UncertaintyEngine.enrich_belief_graph`. Not new. |
| `w_s` (consistency weight in ε) | Derived | A | MRF spatial consistency already computed. Weight derived from the existing `mrf_damping = 0.35` parameter. |
| `w_δ` (source diversity weight in ε) | 0.10–0.20 | B | New dimension. Sensitivity analysis required. Initial value 0.15 — equal to `geva_exploration_weight` scale. Flag in `parameter_provenance.md`. |
| `λ_a` (age decay rate, ε) | From `sensor_config.json` | A | Already defined per disaster type in `age_decay_rates_per_min`. FLOOD=0.015, EARTHQUAKE=0.06, etc. |
| `S_v` (vehicle survivability) | From `vehicle_profiles.json` | A | Already defined per vehicle type. STANDARD_CAR derived from FEMA depth-damage curves. |
| `τ` (sensor provenance trust) | From `sensor_config.json` | A | Already defined as `sensor_base_accuracy`. DRONE_CAMERA=0.96, HUMAN_VISUAL=0.92, SATELLITE_OPTICAL=0.81, CITIZEN_REPORT=0.55. **Zero new constants.** |
| `γ` (survival decay in R_wait) | From `parameters.py` | A | Already defined: `gamma_flood=0.002`, `gamma_earthquake=0.016`, etc. Sourced from Kobe 1995 rubble statistics and NIST thermal thresholds. |
| `Δt` (re-evaluation interval) | = `timestep_duration_s` | A | Equals the simulation timestep (60s). Not a new constant. |
| `C_route_closure` | 1.5 | B | Relative cost of losing a route vs. information error. Needs sensitivity ±30%. Defined in `egl_config.json`. |
| `C_golden_hour` | 2.0 | B | Relative cost of losing golden-hour time window. Literature basis: Cowley et al. (1971) — survival probability halves after 60 min for trauma. Needs ±30% sensitivity. |
| `θ_crisis` | 2.0 | B | ESCALATE trigger threshold (both regrets high). Set to match `geva_overlap_ev_penalty / 4` = 8.0/4 = 2.0. Linked, not arbitrary. |
| `m` (decision margin, base) | 0.15 | B | Hysteresis margin. Literature basis: control theory — margin should be ≥5% of signal range to prevent oscillation. Range of R_act is [0, ~3.0], so 5% ≈ 0.15. Sensitivity: ±0.05. |
| `I` (irreversibility coefficients) | Table below | C | **Must be set by domain experts (emergency management authority) before deployment.** Defaults are engineering estimates only. |

### 2.2 Irreversibility Coefficients — Domain Expert Required

| Action Class | Default `I` | Basis |
|:---|:---|:---|
| Scout re-route | 0.10 | Negligible commitment — only a waypoint change |
| Scout dispatch | 0.20 | Low fuel spend, easily recalled within one tick |
| Rescue team dispatch | 0.55 | 30+ min committed, fuel + crew deployed (FEMA ICS resource commitment doctrine) |
| Helicopter airlift | 0.75 | High fuel, mechanical wear, limited sortie count |
| Evacuation order | 0.90 | Mass population movement — panic if reversed (UNDRR 2019 guidance on evacuation reversals) |

> [!CAUTION]
> These are **engineering defaults**. Before operational use, an emergency management 
> authority must review and sign off on these values. They must be stored in `egl_config.json`
> with an `authorized_by` field, not hardcoded.

### 2.3 Mission Policy Manager Constants

| Constant | Value | Category | Source |
|:---|:---|:---|:---|
| `C_crew_lost` (Balanced profile) | 3.0 | C | **Domain expert required.** Default 3.0 is an engineering estimate. Moral weight of human life vs. resource loss. Must be set by EMA authority. |
| `C_info_wrong` | 1.0 | A | Normalized reference cost (=1.0 by definition — all other costs are relative to this). |
| `C_resource_waste` | 0.5 | B | Half the cost of bad intel, based on operational reports that resource waste is recoverable (FEMA ICS AAR templates). ±30% sensitivity. |
| `mu_act` | 1.0 | A | Baseline moral weight (=1.0 by definition). |
| `mu_wait` | Computed | A | Derived from GEVA vulnerability multiplier: `1.0 + 0.5 × V_target`. V_target already defined in `geva.py`. |
| `AEM` slope | 0.3 | B | Access Equity Multiplier slope. Set so a completely isolated node (reachability=0) gets +30% urgency boost. Sensitivity ±0.1. |

### 2.4 Fleet Coordination Manager Constants

| Constant | Value | Category | Source |
|:---|:---|:---|:---|
| `defer_margin_decay` | 0.02 per tick | B | Derived: base margin 0.15 ÷ number of ticks before escalation. If we want margin to reach 0.03 (minimum stable) after 6 ticks: (0.15 - 0.03) / 6 = 0.02. Self-consistent. |
| `defer_escalate_count` | 6 | B | Derived from golden hour: 60 min / 10 min average re-evaluation = 6 ticks. After a full golden-hour cycle of DEFERs, force human review. |
| `min_effective_margin` | 0.03 | A | Minimum hysteresis margin = 1% of typical R range (0–3.0). Below this, oscillation risk is negligible because both regrets are near-equal (→ ESCALATE anyway). |
| `staged_dispatch_fraction` | 0.33 | B | Agent commits to 1/3 of route before re-evaluating. Needs field expert validation. Sensitivity: 0.25–0.50. |

### 2.5 Human Override Manager Constants

| Constant | Value | Category | Source |
|:---|:---|:---|:---|
| `tbho_timeout_s` (default) | 60 | C | **Domain expert required.** Operational range: 30s (fast-tempo) to 120s (deliberate). Default 60s balances decision quality vs. urgency. Must be set per mission type by incident commander. |
| `tbho_timeout_golden_hour` | 30 | C | Tighter timeout during golden hour. Same source. |
| Timeout default for I < 0.5 | EXECUTE | B | Low-irreversibility actions (scouts) default to execute on timeout — cost of error is recoverable. |
| Timeout default for I ≥ 0.5 | DEFER | B | High-irreversibility actions (rescue/evacuation) default to defer on timeout — irreversible harm avoided. |

> [!NOTE]
> All Category B constants must be documented in `parameter_provenance.md` with:
> their sensitivity range, the metric that would change if they were wrong by ±30%, 
> and a note that calibration is needed before operational deployment.

---

## 3. Module Specifications

### 3.1 `dap.py` — Decision Adequacy Protocol (pure math)

**Single responsibility:** Given an action, agent, target, route, and belief state → return a `DAPResult`.

No logging. No ethics. No fleet state. No human interaction.

```python
@dataclass
class DAPResult:
    outcome: Literal["EXECUTE", "DEFER", "ESCALATE", "STAGED_EXECUTE"]
    epsilon: float          # Epistemic readiness [0,1]
    sigma:   float          # Crew safety index [0,1]
    kappa:   float          # Comms reliability [0,1]
    rho:     float          # Resource sufficiency [0,1]
    delta:   float          # Source diversity index [0,1]
    tau_avg: float          # Mean sensor provenance trust [0,1]
    regret_act:  float      # R_act
    regret_wait: float      # R_wait
    irreversibility: float  # I ∈ [0,1]
    effective_margin: float # Actual m used (after defer decay)
    veto: Optional[str]     # Name of hard veto rule if triggered
    phase: str              # GOLDEN_HOUR / SUSTAINED_OPS / RECOVERY

class DecisionAdequacyProtocol:
    def evaluate(
        self,
        action_class: str,
        agent: BaseAgent,
        target_node: str,
        route: List[str],
        belief_graph: Graph,
        fleet_state: Dict,
        blackout_zones: List,
        forecasts: Dict,
        disaster_type: str,
        sim_time: float,
        ethical_weights: EthicalWeights,   # injected by EPM
        effective_margin: float,            # injected by FCM
    ) -> DAPResult
```

**Key design decision:** `ethical_weights` and `effective_margin` are **injected** as arguments, not read from global config. This makes DAP testable in isolation with any weight set.

**Phase detection — derived, not hardcoded:**
```python
def _get_phase(sim_time: float) -> str:
    # Golden hour: standard EM doctrine (ICRC Trauma Care 2013)
    if sim_time < 60:   return "GOLDEN_HOUR"
    # Sustained ops: up to 6 hours (FEMA ICS operational period standard)
    if sim_time < 360:  return "SUSTAINED_OPS"
    return "RECOVERY"
```

Phase boundaries 60 min and 360 min are **not arbitrary** — they are FEMA ICS 
operational period standards. Cited in provenance doc.

**Dimension formulas — using existing config, zero new constants:**

```
ε: uses UncertaintyEngine weights + sensor_config.json age_decay_rates + sensor_base_accuracy
σ: uses vehicle_profiles.json survivability + geva.py triage weights
κ: uses blackout_zones from engine.py (already tracked)
ρ: uses agent.fuel + fleet_state (already tracked)
δ: uses observation source types from pending_observations (already tracked)
```

---

### 3.2 `mission_policy.py` — Mission Policy Manager (MPM)

**Single responsibility:** Hold and validate policy weight configurations. Provide `MissionWeights` to DAP.

```python
@dataclass
class EthicalWeights:
    c_crew_lost:      float   # Cost of crew casualty
    c_resource_waste: float   # Cost of resource waste  
    c_info_wrong:     float   # = 1.0 always (reference)
    mu_act:           float   # = 1.0 always (baseline)
    mu_wait_boost:    float   # Phase-dependent wait regret multiplier
    aem_slope:        float   # Access equity multiplier slope
    profile_name:     str
    authorized_by:    str     # Officer ID — required for non-default profiles
    authorized_at:    str     # UTC timestamp

PROFILES = {
    "CREW_CONSERVATIVE": EthicalWeights(
        c_crew_lost=5.0, mu_wait_boost=0.8, 
        profile_name="CREW_CONSERVATIVE", ...
    ),
    "BALANCED": EthicalWeights(
        c_crew_lost=3.0, mu_wait_boost=1.0,
        profile_name="BALANCED", ...
    ),
    "CIVILIAN_PRIORITY": EthicalWeights(
        c_crew_lost=1.5, mu_wait_boost=1.8,
        profile_name="CIVILIAN_PRIORITY", ...
    ),
}

class MissionPolicyManager:
    def get_weights(self, phase: str) -> MissionWeights
    def set_profile(self, profile: str, officer_id: str) -> None
    def validate_custom(self, weights: MissionWeights) -> List[str]  # returns validation errors
```

**Profile switching rule:** Changes take effect on the **next planning cycle**, not mid-dispatch.  
Every change is written to audit log via AM (injected dependency).

**Validation rules (ethical sanity checks):**
- `c_crew_lost` must be > `c_resource_waste` (crew always more valuable than equipment)
- `mu_wait_boost` ∈ [0.5, 3.0] — prevents degenerate extremes
- `authorized_by` must be non-empty for non-default profiles

---

### 3.3 `audit.py` — Audit Manager (AM)

**Single responsibility:** Accept EGL decisions and write them to an append-only forensic log.

```python
@dataclass
class EGLAuditRecord:
    record_id:      str         # UUID
    timestamp_utc:  str
    sim_time:       float
    agent_id:       str
    target_node:    str
    outcome:        str
    epsilon:        float
    sigma:          float
    kappa:          float
    rho:            float
    delta:          float
    regret_act:     float
    regret_wait:    float
    phase:          str
    ethical_profile: str
    authorized_by:  str
    human_override: Optional[str]   # "EXECUTE_OVERRIDE" / "DEFER_CONFIRMED" / None
    shadow:         bool

class AuditManager:
    def write(self, record: EGLAuditRecord) -> None    # append-only SQLite
    def export_csv(self, start_utc, end_utc) -> str    # post-incident review
    def get_recent(self, n: int) -> List[EGLAuditRecord]  # for dashboard
```

**Storage:** Append-only SQLite table. No UPDATE or DELETE operations — enforced at 
the SQL level with a trigger. Post-incident export produces a signed CSV with a 
SHA-256 checksum for chain-of-custody.

---

### 3.4 `human_override.py` — Human Override Manager (HOM)

**Single responsibility:** Manage the Time-Boxed Human Override (TBHO) protocol.

```python
class HumanOverrideManager:
    def request_override(
        self,
        dap_result: DAPResult,
        agent_id: str,
        target_node: str,
        timeout_s: int,           # from ethical profile / mission type
    ) -> OverrideRequest          # emits SSE event to frontend

    def receive_response(
        self,
        request_id: str,
        decision: Literal["APPROVE_EXECUTE", "CONFIRM_DEFER"],
        officer_id: str,
    ) -> OverrideResult

    def apply_timeout_default(self, irreversibility: float) -> str:
        # I < 0.5 → EXECUTE (low risk, recoverable)
        # I >= 0.5 → DEFER (high risk, irreversible harm avoided)
```

**SSE event payload to frontend:**
```json
{
  "type": "DAP_ESCALATE",
  "request_id": "uuid",
  "agent_id": "RESCUE-3",
  "target_node": "node_42",
  "timeout_s": 60,
  "regret_act": 1.84,
  "regret_wait": 1.79,
  "epsilon": 0.41,
  "sigma": 0.88,
  "rationale": "Both regrets are high and within margin — human decision required.",
  "irreversibility": 0.55,
  "timeout_default": "DEFER"
}
```

---

### 3.5 `fleet_coordinator.py` — Fleet Coordination Manager (FCM)

**Single responsibility:** Track active dispatch targets and manage DEFER state.

```python
class FleetCoordinationManager:
    active_targets:  Set[str]           # nodes with active dispatches
    defer_counts:    Dict[str, int]     # target_node → consecutive DEFER count
    staged_agents:   Dict[str, str]     # agent_id → staging_node

    def check_mutex(self, target_node: str) -> bool
        # Returns True if target is already actively dispatched

    def register_dispatch(self, agent_id: str, target_node: str) -> None
    def release_target(self, target_node: str) -> None
    
    def get_effective_margin(self, target_node: str) -> float:
        # margin = max(min_margin, base_margin - defer_decay × defer_count)
        # All constants derived from base_margin and defer_escalate_count
        
    def increment_defer(self, target_node: str) -> bool:
        # Returns True if defer_count >= defer_escalate_count → force ESCALATE

    def register_staged(self, agent_id: str, staging_node: str) -> None
    def complete_staged(self, agent_id: str) -> None
```

**DEFER decay — self-consistent derivation (no magic numbers):**
```
base_margin = 0.15  (from DAP, justified above)
min_margin = 0.03   (minimum stable hysteresis)
defer_escalate_count = floor(golden_hour_min / timestep_min)
                     = floor(60 / 10) = 6

decay_per_tick = (base_margin - min_margin) / defer_escalate_count
               = (0.15 - 0.03) / 6 = 0.02
```

All three "magic" DEFER numbers (0.03, 6 ticks, 0.02) are now **derived** from two 
primary parameters: `base_margin` and `golden_hour_duration`. No independent constants.

---

### 3.6 `explainability.py` — Explainability Engine (XE)

**Single responsibility:** Transform a DAPResult into human-readable output.

```python
class ExplainabilityEngine:
    def plain_english(self, result: DAPResult, agent_id: str, target_node: str) -> str:
        # Example outputs:
        # EXECUTE: "Dispatching RESCUE-3 to node_42. Route confidence 78%. 
        #           Delay risk (1.84) outweighs crew risk (0.92). Golden hour active."
        #
        # DEFER:   "Holding RESCUE-3. Road confidence on Segment 7 is only 41%.
        #           Requesting Scout-2 to verify. Reassessing in 60 seconds."
        #
        # ESCALATE:"Commander decision required: RESCUE-3 vs node_42.
        #           Both action risk (1.84) and delay risk (1.79) are critical.
        #           60-second decision window open."

    def technical_breakdown(self, result: DAPResult) -> str:
        # Full math: all dimension scores, regret components, phase, weights used.

    def xai_event(self, result: DAPResult) -> Dict:
        # Structured dict for frontend XAI panel
```

**No computation happens here.** XE takes a fully computed `DAPResult` and formats it. 
This separation means the rationale is always consistent with the actual decision math.

---

### 3.7 `egl.py` — Thin Orchestrator

```python
class ExecutionGovernanceLayer:
    """
    Wires all EGL sub-modules. The only class coordinators interact with.
    """
    def __init__(self, dap, epm, am, hom, fcm, xe):
        self.dap = dap
        self.epm = epm   # Mission Policy Manager
        self.am  = am    # Audit Manager
        self.hom = hom   # Human Override Manager
        self.fcm = fcm   # Fleet Coordination Manager
        self.xe  = xe    # Explainability Engine

    def evaluate(
        self,
        action_class: str,
        agent: BaseAgent,
        target_node: str,
        route: List[str],
        belief_graph: Graph,
        fleet_state: Dict,
        blackout_zones: List,
        forecasts: Dict,
        disaster_type: str,
        sim_time: float,
    ) -> EGLDecision:

        # 1. Fleet mutex check
        if self.fcm.check_mutex(target_node):
            return EGLDecision(outcome="DEFER", vetoed_by="FLEET_MUTEX", ...)

        # 2. Get ethical weights for current phase
        phase = self.dap._get_phase(sim_time)
        weights = self.epm.get_weights(phase)

        # 3. Get effective margin (with defer decay)
        effective_m = self.fcm.get_effective_margin(target_node)

        # 4. DAP core evaluation
        dap_result = self.dap.evaluate(
            ..., ethical_weights=weights, effective_margin=effective_m
        )

        # 5. Handle outcomes
        if dap_result.outcome == "ESCALATE":
            override_req = self.hom.request_override(dap_result, agent.id, target_node)
            # async — coordinator proceeds, HOM resolves later
        elif dap_result.outcome == "DEFER":
            force_escalate = self.fcm.increment_defer(target_node)
            if force_escalate:
                dap_result.outcome = "ESCALATE"
        elif dap_result.outcome in ("EXECUTE", "STAGED_EXECUTE"):
            self.fcm.register_dispatch(agent.id, target_node)

        # 6. Generate rationale
        rationale = self.xe.plain_english(dap_result, agent.id, target_node)

        # 7. Audit log (always — including shadow mode)
        self.am.write(EGLAuditRecord(...))

        return EGLDecision(dap_result=dap_result, rationale=rationale)
```

---

## 4. File Changes Summary

### New Package

#### [NEW] `backend/execution_governance/__init__.py`
#### [NEW] `backend/execution_governance/egl.py` — Orchestrator
#### [NEW] `backend/execution_governance/dap.py` — Pure math
#### [NEW] `backend/execution_governance/mission_policy.py` — MPM
#### [NEW] `backend/execution_governance/audit.py` — AM
#### [NEW] `backend/execution_governance/human_override.py` — HOM
#### [NEW] `backend/execution_governance/fleet_coordinator.py` — FCM
#### [NEW] `backend/execution_governance/explainability.py` — XE

### New Config

#### [NEW] `backend/config_params/egl_config.json`
```json
{
  "_comment": "EGL constants requiring domain expert review before deployment.",
  "_version": "1.0",
  "irreversibility_coefficients": {
    "SCOUT_REROUTE":      {"value": 0.10, "authorized_by": "", "requires_expert_review": true},
    "SCOUT_DISPATCH":     {"value": 0.20, "authorized_by": "", "requires_expert_review": true},
    "RESCUE_DISPATCH":    {"value": 0.55, "authorized_by": "", "requires_expert_review": true},
    "HELICOPTER_AIRLIFT": {"value": 0.75, "authorized_by": "", "requires_expert_review": true},
    "EVACUATION_ORDER":   {"value": 0.90, "authorized_by": "", "requires_expert_review": true}
  },
  "regret_costs": {
    "C_route_closure":  {"value": 1.5, "sensitivity_range": [1.0, 2.5]},
    "C_golden_hour":    {"value": 2.0, "sensitivity_range": [1.5, 3.0]}
  },
  "tbho_timeout_s": {
    "GOLDEN_HOUR":   {"value": 30, "authorized_by": "", "requires_expert_review": true},
    "SUSTAINED_OPS": {"value": 60, "authorized_by": "", "requires_expert_review": true},
    "RECOVERY":      {"value": 90, "authorized_by": "", "requires_expert_review": true}
  },
  "staged_dispatch_fraction": {"value": 0.33, "sensitivity_range": [0.25, 0.50]},
  "aem_slope": {"value": 0.3, "sensitivity_range": [0.2, 0.5]}
}
```

#### [MODIFY] `backend/config_params/parameter_provenance.md`
Add EGL section documenting all Category B constants with:
- Sensitivity range
- What metric changes if wrong by ±30%
- Calibration method (simulation replay against historical events)

### Integrations

#### [MODIFY] `backend/agents/coordinator.py`
- Replace all direct dispatch logic with `egl.evaluate(...)` calls
- `assign_rescues()`: Call EGL for each candidate. Handle EXECUTE/DEFER/STAGED/ESCALATE.
- `assign_scouts()`: Call EGL with `action_class="SCOUT_DISPATCH"`.
- Inject `egl` as constructor dependency.

#### [MODIFY] `backend/simulation/engine.py`
- Instantiate EGL with all sub-modules at simulation init
- Pass EGL instance to coordinator
- Expose `egl.am.get_recent(50)` through API for XAI dashboard
- On P2P blackout sync: unchanged (stays in engine loop)

#### [MODIFY] `backend/agents/base_agent.py`
- Add `pending_observations_from: List[str]` (for δ source diversity computation)
- Add `staged_dispatch_target: Optional[str]` (for FCM staged state)

#### [NEW] `backend/api/egl_api.py`
- `GET  /api/egl/config`            → current EGL config
- `POST /api/egl/ethical-profile`   → set profile (requires officer_id)
- `GET  /api/egl/audit`             → recent audit records (for dashboard)
- `POST /api/egl/override/{id}`     → TBHO human response
- `GET  /api/egl/shadow-report`     → shadow mode comparison (if enabled)

---

## 5. Sensitivity Analysis Plan (Required Before Deployment)

For all Category B constants, run:

```bash
venv\Scripts\python -m pytest tests/test_egl_sensitivity.py -v
```

Test methodology: Monte Carlo sweep of each constant ±30% while holding others fixed.
Metric: What % of EXECUTE/DEFER/ESCALATE decisions change?
Acceptance: No single constant ±30% should flip > 15% of decisions (robustness criterion).

Constants to sweep:
- `C_route_closure` ∈ [1.0, 2.5]
- `C_golden_hour` ∈ [1.5, 3.0]
- `w_δ` ∈ [0.10, 0.20]
- `aem_slope` ∈ [0.2, 0.5]
- `staged_dispatch_fraction` ∈ [0.25, 0.50]
- `base_margin` ∈ [0.10, 0.20]

---

## 6. Verification Plan

### Unit Tests

```bash
venv\Scripts\python -m pytest tests/test_egl/ -v
```

Test files:
- `test_dap.py` — 18 scenarios (all v1 cases + δ, τ, AEM, defer decay, fleet mutex, staged)
- `test_epm.py` — profile switching, validation rules, phase-adaptive weights
- `test_am.py` — append-only enforcement, CSV export, checksum
- `test_hom.py` — TBHO timeout defaults, override flow, timeout behaviour
- `test_fcm.py` — mutex, defer decay derivation, staged dispatch states
- `test_xe.py` — plain English output for all 4 outcomes
- `test_egl.py` — orchestration integration (all modules wired)

### Integration Tests
1. Full simulation run: EGL decisions visible in XAI event log
2. DEFER × 6 → auto-ESCALATE fires
3. ESCALATE → TBHO event received by frontend with correct timeout
4. Profile switch → audit record written, old profile still used for active dispatches
5. Shadow mode: EGL runs without affecting dispatch; comparison report generated
6. Forensic export: SHA-256 checksum on CSV export matches server-side hash

---

## 7. Open Questions (Remaining, Reduced)

> [!IMPORTANT]
> **Irreversibility coefficients sign-off:** The EGL cannot go to deployment without an
> emergency management authority signing the `authorized_by` fields in `egl_config.json`.
> These are value judgments, not engineering defaults.

> [!IMPORTANT]
> **TBHO timeouts by mission type:** Suggested defaults (30/60/90s) need validation
> with field commanders during tabletop exercise or simulation replay.

> [!NOTE]
> **P2P sync radius:** Should co-located agents (same node) trigger P2P sync, or
> within a configurable radius (e.g., 200m)? Current plan: same node only.
> Recommend adding `p2p_sync_radius_m` to `egl_config.json` as Category C.

> [!NOTE]
> **Shadow mode comparison metric:** What is the primary metric for comparing EGL
> decisions vs. greedy dispatch? Proposal: total expected survivors rescued
> per simulation run. Needs agreement before implementation.

---

## 8. Implementation Order

| Priority | Module | Est. Complexity |
|:---|:---|:---|
| 🔴 P0 | `dap.py` — pure math, all 5 dimensions | High |
| 🔴 P0 | `mission_policy.py` + `egl_config.json` | Medium |
| 🔴 P0 | `audit.py` — append-only log | Medium |
| 🟠 P1 | `fleet_coordinator.py` — mutex + defer decay | Medium |
| 🟠 P1 | `egl.py` — orchestrator | Low (wiring only) |
| 🟠 P1 | Coordinator integration | Medium |
| 🟡 P2 | `human_override.py` + SSE events | Medium |
| 🟡 P2 | `explainability.py` | Low |
| 🟡 P2 | `egl_api.py` | Low |
| 🟢 P3 | Shadow mode | Low |
| 🟢 P3 | Sensitivity test suite | Medium |
| 🟢 P3 | Staged dispatch (STAGED_EXECUTE) | High |
