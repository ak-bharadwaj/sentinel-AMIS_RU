"""
Terrain Cache — Persistent SQLite-backed Elevation Store
=========================================================
Stores terrain data in the Sentinel SQLite database so it survives:
  - process restart
  - server reboot
  - deployment

Schema (terrain_cache table):
  node_id   TEXT    — graph node ID
  lat       REAL
  lon       REAL
  elevation REAL    — SRTM terrain elevation in metres
  slope     REAL    — degrees
  aspect    REAL    — degrees (compass)
  twi       REAL    — Topographic Wetness Index
  terrain_class  TEXT   — PEAK / CREST / SLOPE / VALLEY / BASIN
  source    TEXT    — provider name that resolved this point
  fetched_at     TEXT  — ISO timestamp

TerrainCache reads/writes are batch-optimised using executemany()
to avoid per-row round-trips on large city graphs.
"""
from __future__ import annotations

import sqlite3
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Default database path — same as sentinel.db
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "sentinel.db"
)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS terrain_cache (
    node_id       TEXT    NOT NULL,
    lat           REAL    NOT NULL,
    lon           REAL    NOT NULL,
    elevation     REAL    NOT NULL DEFAULT 0.0,
    slope         REAL    NOT NULL DEFAULT 0.0,
    aspect        REAL    NOT NULL DEFAULT 0.0,
    twi           REAL    NOT NULL DEFAULT 5.0,
    terrain_class TEXT    NOT NULL DEFAULT 'SLOPE',
    source        TEXT    NOT NULL DEFAULT 'unknown',
    fetched_at    TEXT    NOT NULL,
    PRIMARY KEY (node_id)
);
CREATE INDEX IF NOT EXISTS terrain_cache_lat_lon ON terrain_cache (lat, lon);
"""


class TerrainCache:
    """Thread-safe read/write cache for terrain data backed by SQLite.
    
    Usage:
        cache = TerrainCache()
        cache.init()
        
        # Write
        cache.store([{"node_id": "123", "lat": 19.07, "lon": 72.87, ...}])
        
        # Read all for a region (by bounding box)
        rows = cache.load_region(min_lat, max_lat, min_lon, max_lon)
        
        # Read single node
        row = cache.get_node("123")
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or _DEFAULT_DB_PATH

    def init(self) -> None:
        """Create table if it doesn't exist."""
        with self._connect() as conn:
            conn.executescript(_CREATE_SQL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def has_region(self, min_lat: float, max_lat: float, min_lon: float, max_lon: float, min_count: int = 5) -> bool:
        """Return True if at least min_count terrain records exist for this bounding box."""
        sql = """
        SELECT COUNT(*) as cnt FROM terrain_cache
        WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
        """
        with self._connect() as conn:
            row = conn.execute(sql, (min_lat, max_lat, min_lon, max_lon)).fetchone()
            return (row["cnt"] if row else 0) >= min_count

    def load_region(
        self, min_lat: float, max_lat: float, min_lon: float, max_lon: float
    ) -> Dict[str, dict]:
        """Load all cached terrain rows within the bounding box.
        Returns a dict: node_id → terrain_data dict.
        """
        sql = """
        SELECT * FROM terrain_cache
        WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (min_lat, max_lat, min_lon, max_lon)).fetchall()
        return {row["node_id"]: dict(row) for row in rows}

    def get_node(self, node_id: str) -> Optional[dict]:
        """Fetch cached terrain for a single node."""
        sql = "SELECT * FROM terrain_cache WHERE node_id = ?"
        with self._connect() as conn:
            row = conn.execute(sql, (node_id,)).fetchone()
        return dict(row) if row else None

    def store(self, records: List[dict]) -> None:
        """Upsert terrain records in batch.
        
        Each record must have: node_id, lat, lon, elevation, slope,
        aspect, twi, terrain_class, source.
        """
        if not records:
            return
        now = datetime.now(timezone.utc).isoformat()
        sql = """
        INSERT OR REPLACE INTO terrain_cache
            (node_id, lat, lon, elevation, slope, aspect, twi, terrain_class, source, fetched_at)
        VALUES
            (:node_id, :lat, :lon, :elevation, :slope, :aspect, :twi, :terrain_class, :source, :fetched_at)
        """
        data = [{**r, "fetched_at": now} for r in records]
        with self._connect() as conn:
            conn.executemany(sql, data)
            conn.commit()

    def clear_region(self, min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> int:
        """Delete all cached terrain records within a bounding box. Returns deleted count."""
        sql = """
        DELETE FROM terrain_cache
        WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
        """
        with self._connect() as conn:
            cursor = conn.execute(sql, (min_lat, max_lat, min_lon, max_lon))
            conn.commit()
            return cursor.rowcount


# Module-level singleton
terrain_cache = TerrainCache()
