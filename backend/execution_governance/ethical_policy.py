"""
Backwards-compatibility wrapper for ethical_policy.py.
Forwards all classes to mission_policy.py.
"""

from backend.execution_governance.mission_policy import (
    MissionPolicyManager as EthicalPolicyManager,
    _validate_weights,
)
from backend.execution_governance.mission_policy import *
