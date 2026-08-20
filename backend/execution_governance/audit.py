"""
Execution Governance Layer — Audit Manager (AM)
================================================
Single responsibility: write every EGL decision to an append-only
forensic log. No reads used for decision-making. No computation.

Decoupled storage: uses an AuditBackend interface. The default
reference implementation SQLiteAuditBackend uses database-level triggers
to prevent UPDATE and DELETE operations.
"""

from __future__ import annotations

import abc
import csv
import hashlib
import io
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# SQLite Configuration Strings
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS egl_audit (
    record_id        TEXT PRIMARY KEY,
    timestamp_utc    TEXT NOT NULL,
    sim_time         REAL NOT NULL,
    agent_id         TEXT NOT NULL,
    target_node      TEXT NOT NULL,
    outcome          TEXT NOT NULL,
    epsilon          REAL,
    sigma            REAL,
    kappa            REAL,
    rho              REAL,
    delta            REAL,
    regret_act       REAL,
    regret_wait      REAL,
    irreversibility  REAL,
    effective_margin REAL,
    phase            TEXT,
    ethical_profile  TEXT,
    authorized_by    TEXT,
    human_override   TEXT,
    veto             TEXT,
    shadow           INTEGER DEFAULT 0,
    composite_score  REAL
);
"""

_CREATE_IMMUTABILITY_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS prevent_update_egl_audit
BEFORE UPDATE ON egl_audit
BEGIN
    SELECT RAISE(ABORT, 'EGL Audit: UPDATE is forbidden. Records are append-only.');
END;

CREATE TRIGGER IF NOT EXISTS prevent_delete_egl_audit
BEFORE DELETE ON egl_audit
BEGIN
    SELECT RAISE(ABORT, 'EGL Audit: DELETE is forbidden. Records are append-only.');
END;
"""

_COLUMNS = [
    "record_id", "timestamp_utc", "sim_time", "agent_id", "target_node",
    "outcome", "epsilon", "sigma", "kappa", "rho", "delta",
    "regret_act", "regret_wait", "irreversibility", "effective_margin",
    "phase", "ethical_profile", "authorized_by", "human_override",
    "veto", "shadow", "composite_score",
]

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class EGLAuditRecord:
    """One audit log entry per EGL evaluation."""
    sim_time:         float
    agent_id:         str
    target_node:      str
    outcome:          str
    epsilon:          float
    sigma:            float
    kappa:            float
    rho:              float
    delta:            float
    regret_act:       float
    regret_wait:      float
    irreversibility:  float
    effective_margin: float
    phase:            str
    ethical_profile:  str
    composite_score:  float
    authorized_by:    str = ""
    human_override:   Optional[str] = None   # "EXECUTE_OVERRIDE" | "DEFER_CONFIRMED" | None
    veto:             Optional[str] = None
    shadow:           bool = False
    # Auto-generated:
    record_id:        str = ""
    timestamp_utc:    str = ""

    def __post_init__(self) -> None:
        if not self.record_id:
            self.record_id = str(uuid.uuid4())
        if not self.timestamp_utc:
            self.timestamp_utc = datetime.now(tz=timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Abstract Backend Interface
# ---------------------------------------------------------------------------

class AuditBackend(abc.ABC):
    """Abstract interface defining required storage and query operations."""

    @abc.abstractmethod
    def write(self, record: EGLAuditRecord) -> None:
        """Write one audit record to the persistent log."""
        pass

    @abc.abstractmethod
    def get_recent(self, n: int) -> List[Dict[str, Any]]:
        """Retrieve the N most recent records."""
        pass

    @abc.abstractmethod
    def export_csv(
        self,
        start_utc: Optional[str] = None,
        end_utc:   Optional[str] = None,
    ) -> Dict[str, str]:
        """Export audit records to a signed CSV string."""
        pass

    @abc.abstractmethod
    def count_overrides(self, since_utc: str) -> int:
        """Count human override actions since a given timestamp."""
        pass

    @abc.abstractmethod
    def count_total(self, since_utc: str) -> int:
        """Count total evaluations since a given timestamp."""
        pass

# ---------------------------------------------------------------------------
# SQLite Reference Implementation
# ---------------------------------------------------------------------------

class SQLiteAuditBackend(AuditBackend):
    """SQLite-based reference implementation of the AuditBackend."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialise_db()

    def write(self, record: EGLAuditRecord) -> None:
        con = None
        try:
            con = self._connect()
            con.execute(
                f"INSERT INTO egl_audit ({', '.join(_COLUMNS)}) "
                f"VALUES ({', '.join(['?'] * len(_COLUMNS))})",
                (
                    record.record_id,
                    record.timestamp_utc,
                    record.sim_time,
                    record.agent_id,
                    record.target_node,
                    record.outcome,
                    record.epsilon,
                    record.sigma,
                    record.kappa,
                    record.rho,
                    record.delta,
                    record.regret_act,
                    record.regret_wait,
                    record.irreversibility,
                    record.effective_margin,
                    record.phase,
                    record.ethical_profile,
                    record.authorized_by,
                    record.human_override,
                    record.veto,
                    1 if record.shadow else 0,
                    record.composite_score,
                ),
            )
            con.commit()
        except Exception as exc:
            print(f"[EGL/AuditBackend] WARNING: failed to write audit record: {exc}")
        finally:
            if con:
                con.close()

    def get_recent(self, n: int) -> List[Dict[str, Any]]:
        con = None
        try:
            con = self._connect()
            rows = con.execute(
                "SELECT * FROM egl_audit ORDER BY timestamp_utc DESC LIMIT ?", (n,)
            ).fetchall()
            results = []
            for row in rows:
                record = dict(zip(_COLUMNS, row))
                # Compute per-record SHA-256 for forensic integrity verification
                record_str = "|".join(str(record.get(c, "")) for c in _COLUMNS)
                record["sha256_hash"] = hashlib.sha256(record_str.encode()).hexdigest()
                results.append(record)
            return results
        except Exception as exc:
            print(f"[EGL/AuditBackend] WARNING: get_recent failed: {exc}")
            return []
        finally:
            if con:
                con.close()

    def export_csv(
        self,
        start_utc: Optional[str] = None,
        end_utc:   Optional[str] = None,
    ) -> Dict[str, str]:
        try:
            con = self._connect()
            query = "SELECT * FROM egl_audit"
            params: list = []
            if start_utc and end_utc:
                query += " WHERE timestamp_utc BETWEEN ? AND ?"
                params = [start_utc, end_utc]
            elif start_utc:
                query += " WHERE timestamp_utc >= ?"
                params = [start_utc]
            elif end_utc:
                query += " WHERE timestamp_utc <= ?"
                params = [end_utc]
            query += " ORDER BY timestamp_utc ASC"

            rows = con.execute(query, params).fetchall()
            con.close()

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(_COLUMNS)
            for row in rows:
                writer.writerow(row)

            csv_content = buf.getvalue()
            sha256 = hashlib.sha256(csv_content.encode()).hexdigest()

            return {
                "csv_content":  csv_content,
                "sha256":       sha256,
                "record_count": str(len(rows)),
            }
        except Exception as exc:
            print(f"[EGL/AuditBackend] WARNING: export_csv failed: {exc}")
            return {"csv_content": "", "sha256": "", "record_count": "0"}

    def count_overrides(self, since_utc: str) -> int:
        try:
            con = self._connect()
            result = con.execute(
                "SELECT COUNT(*) FROM egl_audit "
                "WHERE human_override IS NOT NULL AND timestamp_utc >= ?",
                (since_utc,),
            ).fetchone()
            con.close()
            return result[0] if result else 0
        except Exception:
            return 0

    def count_total(self, since_utc: str) -> int:
        try:
            con = self._connect()
            result = con.execute(
                "SELECT COUNT(*) FROM egl_audit WHERE timestamp_utc >= ?",
                (since_utc,),
            ).fetchone()
            con.close()
            return result[0] if result else 0
        except Exception:
            return 0

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _initialise_db(self) -> None:
        try:
            con = self._connect()
            con.executescript(_CREATE_TABLE + _CREATE_IMMUTABILITY_TRIGGERS)
            con.commit()
            con.close()
        except Exception as exc:
            print(f"[EGL/AuditBackend] WARNING: DB initialisation failed: {exc}")

# ---------------------------------------------------------------------------
# Manager (Wires persistence logic)
# ---------------------------------------------------------------------------

class AuditManager:
    """
    Forensic logger interface wrapping an injected AuditBackend.
    """

    def __init__(self, backend: Optional[AuditBackend] = None, db_path: Optional[str] = None) -> None:
        if backend is None:
            if db_path is None:
                project_root = os.path.join(
                    os.path.dirname(__file__), "..", ".."
                )
                db_path = os.path.abspath(os.path.join(project_root, "egl_audit.db"))
            backend = SQLiteAuditBackend(db_path)
        self.backend = backend

    @property
    def _db_path(self) -> str:
        if isinstance(self.backend, SQLiteAuditBackend):
            return self.backend.db_path
        return ""

    @_db_path.setter
    def _db_path(self, val: str) -> None:
        if isinstance(self.backend, SQLiteAuditBackend):
            self.backend.db_path = val

    def _initialise_db(self) -> None:
        if isinstance(self.backend, SQLiteAuditBackend):
            self.backend._initialise_db()

    def _connect(self) -> sqlite3.Connection:
        if isinstance(self.backend, SQLiteAuditBackend):
            return self.backend._connect()
        raise AttributeError("Injected backend does not support _connect")

    def write(self, record: EGLAuditRecord) -> None:
        """Delegate audit record persistence to the injected backend."""
        self.backend.write(record)

    def write_profile_change(
        self,
        old_profile: str,
        new_profile: str,
        officer_id:  str,
        timestamp_utc: str,
    ) -> None:
        """Log policy profile changes."""
        record = EGLAuditRecord(
            sim_time=0.0,
            agent_id="MPM",
            target_node="N/A",
            outcome="PROFILE_CHANGE",
            epsilon=0.0, sigma=0.0, kappa=0.0, rho=0.0, delta=0.0,
            regret_act=0.0, regret_wait=0.0,
            irreversibility=0.0, effective_margin=0.0,
            phase="N/A",
            ethical_profile=f"{old_profile}→{new_profile}",
            composite_score=0.0,
            authorized_by=officer_id,
            timestamp_utc=timestamp_utc,
        )
        self.write(record)

    def get_recent(self, n: int = 50) -> List[Dict[str, Any]]:
        return self.backend.get_recent(n)

    def export_csv(
        self,
        start_utc: Optional[str] = None,
        end_utc:   Optional[str] = None,
    ) -> Dict[str, str]:
        return self.backend.export_csv(start_utc, end_utc)

    def count_overrides(self, since_utc: str) -> int:
        return self.backend.count_overrides(since_utc)

    def count_total(self, since_utc: str) -> int:
        return self.backend.count_total(since_utc)
