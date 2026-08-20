import os
import sqlite3
import pytest
from backend.execution_governance.audit import AuditManager, EGLAuditRecord

@pytest.fixture
def temp_db_file():
    db_file = os.path.abspath("temp_egl_audit.db")
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    yield db_file
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass

def test_audit_manager_append_only(temp_db_file):
    am = AuditManager(db_path=temp_db_file)
    
    # Insert record
    rec = EGLAuditRecord(
        sim_time=5.0,
        agent_id="RESCUE_1",
        target_node="node_A",
        outcome="EXECUTE",
        epsilon=0.8,
        sigma=0.8,
        kappa=0.8,
        rho=0.8,
        delta=0.8,
        regret_act=0.1,
        regret_wait=0.2,
        irreversibility=0.55,
        effective_margin=0.15,
        phase="GOLDEN_HOUR",
        ethical_profile="BALANCED",
        composite_score=0.8
    )
    am.write(rec)
    
    # Verify record exists
    recent = am.get_recent(5)
    assert len(recent) == 1
    assert recent[0]["agent_id"] == "RESCUE_1"
    
    # Try updating record - should fail due to triggers
    con = am._connect()
    try:
        with pytest.raises(sqlite3.IntegrityError, match=" forbidden"):
            con.execute("UPDATE egl_audit SET outcome = 'DEFER' WHERE agent_id = 'RESCUE_1'")
            con.commit()
            
        # Try deleting record - should fail due to triggers
        with pytest.raises(sqlite3.IntegrityError, match=" forbidden"):
            con.execute("DELETE FROM egl_audit WHERE agent_id = 'RESCUE_1'")
            con.commit()
    finally:
        con.close()

def test_audit_manager_csv_export_and_checksum(temp_db_file):
    am = AuditManager(db_path=temp_db_file)
    
    rec1 = EGLAuditRecord(
        sim_time=1.0, agent_id="SCOUT_1", target_node="node_A", outcome="DEFER",
        epsilon=0.3, sigma=0.9, kappa=0.9, rho=0.9, delta=0.5,
        regret_act=0.9, regret_wait=0.1, irreversibility=0.2, effective_margin=0.15,
        phase="GOLDEN_HOUR", ethical_profile="BALANCED", composite_score=0.67
    )
    am.write(rec1)
    
    export = am.export_csv()
    assert export["record_count"] == "1"
    assert "SCOUT_1" in export["csv_content"]
    assert len(export["sha256"]) == 64  # SHA-256 hex digest is 64 characters
