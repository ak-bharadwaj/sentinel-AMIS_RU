"""
Execution Governance Layer — Package Init
==========================================
Clean public API for the execution_governance package.

External code should import from this module:

    from backend.execution_governance import (
        ExecutionGovernanceLayer,
        EGLDecision,
        DAPResult,
        EthicalWeights,
    )

Sub-modules are intentionally NOT re-exported at top level to
enforce the architectural boundary: external code talks to the
EGL orchestrator, not to individual sub-modules.
"""

from backend.execution_governance.egl import ExecutionGovernanceLayer, EGLDecision
from backend.execution_governance.dap import DAPResult, EthicalWeights

__all__ = [
    "ExecutionGovernanceLayer",
    "EGLDecision",
    "DAPResult",
    "EthicalWeights",
]
