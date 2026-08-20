import pytest
from backend.execution_governance.dap import DAPResult
from backend.execution_governance.explainability import ExplainabilityEngine

@pytest.fixture
def sample_dap_result():
    return DAPResult(
        outcome="EXECUTE",
        phase="GOLDEN_HOUR",
        epsilon=0.85,
        sigma=0.9,
        kappa=0.75,
        rho=0.8,
        delta=0.67,
        tau_avg=0.9,
        aem=1.0,
        irreversibility=0.55,
        regret_act=0.15,
        regret_wait=0.85,
        effective_margin=0.15,
        veto=None
    )

def test_xe_plain_english_generation(sample_dap_result):
    xe = ExplainabilityEngine()
    
    # Execute case
    desc_exec = xe.plain_english(sample_dap_result, "RESCUE_1", "node_A")
    assert "Dispatching RESCUE_1" in desc_exec
    assert "Golden hour active" in desc_exec
    
    # Defer case
    sample_dap_result.outcome = "DEFER"
    sample_dap_result.regret_act = 0.85
    sample_dap_result.regret_wait = 0.15
    desc_defer = xe.plain_english(sample_dap_result, "RESCUE_1", "node_A")
    assert "deferred" in desc_defer
    
    # Veto case
    sample_dap_result.veto = "VETO_FUEL_CRITICAL"
    desc_veto = xe.plain_english(sample_dap_result, "RESCUE_1", "node_A")
    assert "BLOCKED" in desc_veto
    assert "VETO_FUEL_CRITICAL" in desc_veto

def test_xe_dimension_alerts(sample_dap_result):
    xe = ExplainabilityEngine()
    
    # High scores - no alerts
    alerts_none = xe.dimension_alerts(sample_dap_result)
    assert len(alerts_none) == 0
    
    # Epsilon below threshold (0.85 -> 0.35)
    sample_dap_result.epsilon = 0.35
    alerts = xe.dimension_alerts(sample_dap_result)
    assert len(alerts) == 1
    assert alerts[0]["dimension"] == "epsilon"
    assert alerts[0]["severity"] == "warning"
