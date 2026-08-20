import pytest
from backend.execution_governance.mission_policy import MissionPolicyManager, _validate_weights

def test_ethical_policy_validation():
    # Valid weights
    valid = {"c_crew_lost": 3.0, "c_resource_waste": 0.5, "mu_wait_boost": 1.0}
    errors = _validate_weights(valid)
    assert not errors
    
    # Invalid: crew lost cost <= resource waste
    invalid_crew = {"c_crew_lost": 0.3, "c_resource_waste": 0.5, "mu_wait_boost": 1.0}
    errors_crew = _validate_weights(invalid_crew)
    assert len(errors_crew) > 0
    assert "c_crew_lost" in errors_crew[0]
    
    # Invalid: wait boost out of bounds
    invalid_boost = {"c_crew_lost": 3.0, "c_resource_waste": 0.5, "mu_wait_boost": 5.0}
    errors_boost = _validate_weights(invalid_boost)
    assert len(errors_boost) > 0
    assert "mu_wait_boost" in errors_boost[0]

def test_ethical_policy_profile_retrieval():
    epm = MissionPolicyManager()
    
    # Defaults to BALANCED
    assert epm.active_profile_name == "BALANCED"
    weights = epm.get_weights(phase="GOLDEN_HOUR")
    assert weights.profile_name == "BALANCED"
    assert weights.c_crew_lost == 3.0
    
    # Phase wait boost check (GOLDEN_HOUR = 1.5x wait boost)
    assert weights.mu_wait_boost == 1.5

def test_ethical_policy_profile_switch():
    epm = MissionPolicyManager()
    
    # Switch profile requires officer_id
    errors_no_id = epm.set_profile("CREW_CONSERVATIVE", officer_id="")
    assert len(errors_no_id) > 0
    
    # Successful profile queueing
    errors_success = epm.set_profile("CREW_CONSERVATIVE", officer_id="CMD_1")
    assert not errors_success
    assert epm.active_profile_name == "BALANCED"  # Still BALANCED until cycle commit
    assert epm.pending_profile_name == "CREW_CONSERVATIVE"
    
    # Commit change
    epm.commit_pending_profile()
    assert epm.active_profile_name == "CREW_CONSERVATIVE"
    assert epm.pending_profile_name is None
    
    # Retrieve weights after change
    weights = epm.get_weights(phase="SUSTAINED_OPS")
    assert weights.c_crew_lost == 5.0
