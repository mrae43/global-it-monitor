import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

CREATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS check_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at  TEXT NOT NULL,
    host_label  TEXT NOT NULL,
    host_ip     TEXT NOT NULL,
    check_type  TEXT NOT NULL,
    port        INTEGER,
    status      TEXT NOT NULL,
    latency_ms  REAL
);"""

def init_database(db_path: str) -> None:
    """Create the SQLite database and schema if they don't exist.

    Args:
        db_path: Path to the SQLite database file.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()
    conn.close()

def save_results(db_path: str, results: list[dict[str, Any]]) -> None:
    """Insert check results from a single monitoring cycle.

    Args:
        db_path: Path to the SQLite database file.
        results: List of result dicts with keys host_label, host_ip, check_type,
                 port (optional), status, latency_ms (optional).
    """
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_TABLE_SQL)
    for r in results:
        conn.execute("""
            INSERT INTO check_results
            (checked_at, host_label, host_ip, check_type, port, status, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            r['host_label'],
            r['host_ip'],
            r['check_type'],
            r.get('port'),
            r['status'],
            r.get('latency_ms')
        ))
    conn.commit()
    conn.close()

def query_latest(db_path: str) -> list[tuple]:
    """Get the most recent result per host/check-type/port combination.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        List of tuples (host_label, status, latency_ms, checked_at).
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("""
            SELECT host_label, status, latency_ms, checked_at
            FROM check_results
            WHERE id IN (SELECT MAX(id) FROM check_results GROUP BY host_ip, check_type, port)
            ORDER BY host_label
        """)
        return cursor.fetchall()
    finally:
        conn.close()