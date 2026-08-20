import pytest
from backend.execution_governance.dap import DAPResult
from backend.execution_governance.human_override import HumanOverrideManager

@pytest.fixture
def escalate_dap_result():
    return DAPResult(
        outcome="ESCALATE",
        phase="GOLDEN_HOUR",
        epsilon=0.45,
        sigma=0.8,
        kappa=0.8,
        rho=0.8,
        delta=0.8,
        tau_avg=0.9,
        aem=1.0,
        irreversibility=0.55,  # High irreversibility
        regret_act=1.5,
        regret_wait=1.45,
        effective_margin=0.15,
        veto=None
    )

def test_hom_request_and_resolution(escalate_dap_result):
    hom = HumanOverrideManager()
    
    # Request override
    req = hom.request_override(escalate_dap_result, "RESCUE_1", "node_A", "Test Rationale")
    assert req.agent_id == "RESCUE_1"
    assert req.target_node == "node_A"
    assert req.timeout_s == 30  # Golden hour timeout default is 30s
    assert req.timeout_default == "DEFER"  # I >= 0.50 -> DEFER
    assert not req.resolved
    
    # Resolve - Approve
    res = hom.receive_response(req.request_id, "APPROVE_EXECUTE", "CMD_1")
    assert res is not None
    assert res.resolution == "APPROVE_EXECUTE"
    assert res.final_outcome == "EXECUTE"
    assert req.resolved
    assert req.resolution == "APPROVE_EXECUTE"

def test_hom_timeout_default_rules(escalate_dap_result):
    hom = HumanOverrideManager()
    
    # Case 1: High irreversibility (I >= 0.50) -> Defaults to DEFER
    req_high = hom.request_override(escalate_dap_result, "RESCUE_1", "node_A")
    res_high = hom.apply_timeout_default(req_high.request_id)
    assert res_high.final_outcome == "DEFER"
    
    # Case 2: Low irreversibility (I < 0.50) -> Defaults to EXECUTE
    escalate_dap_result.irreversibility = 0.20
    req_low = hom.request_override(escalate_dap_result, "SCOUT_1", "node_A")
    res_low = hom.apply_timeout_default(req_low.request_id)
    assert res_low.final_outcome == "EXECUTE"

def test_hom_override_rate_alert(escalate_dap_result):
    hom = HumanOverrideManager()
    
    # 2 requests: 1 approved (override), 1 deferred (confirmed default/DAP logic)
    req1 = hom.request_override(escalate_dap_result, "RESCUE_1", "node_A")
    hom.receive_response(req1.request_id, "APPROVE_EXECUTE", "CMD_1")
    
    req2 = hom.request_override(escalate_dap_result, "RESCUE_2", "node_A")
    hom.receive_response(req2.request_id, "CONFIRM_DEFER", "CMD_1")
    
    rate_info = hom.get_override_rate()
    assert rate_info["total"] == 2
    assert rate_info["overrides"] == 1
    assert rate_info["rate"] == 0.50
    assert rate_info["alert"] is True  # Override rate of 50% is > 40% threshold
