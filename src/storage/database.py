import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from loguru import logger

CREATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS check_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at  TEXT NOT NULL,
    host_label  TEXT NOT NULL,
    host_address TEXT NOT NULL,
    check_type  TEXT NOT NULL,
    port        INTEGER,
    status      TEXT NOT NULL,
    latency_ms  REAL
);"""

CREATE_ALERTS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at    TEXT NOT NULL,
    host_label      TEXT NOT NULL,
    host_address    TEXT NOT NULL,
    check_type      TEXT NOT NULL,
    port            INTEGER,
    severity        TEXT NOT NULL,
    resolved_at     TEXT,
    resolved_reason TEXT
);"""

CREATE_INDEX_CHECK_RESULTS_SQL = """CREATE INDEX IF NOT EXISTS idx_check_results_track_time
ON check_results(host_address, check_type, port, checked_at DESC);"""

CREATE_INDEX_ALERTS_SQL = """CREATE INDEX IF NOT EXISTS idx_alerts_track_time
ON alerts(host_address, check_type, port, triggered_at DESC);"""


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    rows = cursor.fetchall()
    return any(row[1] == column for row in rows)


def init_database(db_path: str) -> None:
    """Create the SQLite database and schema if they don't exist.

    Args:
        db_path: Path to the SQLite database file.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        # Migrate Phase 1 column name if needed
        if _column_exists(conn, 'check_results', 'host_ip') and not _column_exists(conn, 'check_results', 'host_address'):
            conn.execute("ALTER TABLE check_results RENAME COLUMN host_ip TO host_address")
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_ALERTS_TABLE_SQL)
        conn.execute(CREATE_INDEX_CHECK_RESULTS_SQL)
        conn.execute(CREATE_INDEX_ALERTS_SQL)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Database initialised at {db_path}")


def save_results(db_path: str, results: list[dict[str, Any]]) -> None:
    """Insert check results from a single monitoring cycle.

    Args:
        db_path: Path to the SQLite database file.
        results: List of result dicts with keys host_label, host_address, check_type,
                 port (optional), status, latency_ms (optional).
    """
    logger.debug(f"Saving {len(results)} results to {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(CREATE_TABLE_SQL)
        for r in results:
            conn.execute("""
                INSERT INTO check_results
                (checked_at, host_label, host_address, check_type, port, status, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                r['host_label'],
                r['host_address'],
                r['check_type'],
                r.get('port'),
                r['status'],
                r.get('latency_ms')
            ))
        conn.commit()
    finally:
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
            WHERE id IN (SELECT MAX(id) FROM check_results GROUP BY host_address, check_type, port)
            ORDER BY host_label
        """)
        return cursor.fetchall()
    finally:
        conn.close()


def count_consecutive_failures(db_path: str, host_address: str, check_type: str, port: int | None, limit: int) -> int:
    """Count consecutive failure statuses (DOWN/CLOSED) from newest to oldest.

    Args:
        db_path: Path to the SQLite database file.
        host_address: Host address.
        check_type: 'ICMP' or 'TCP'.
        port: Port number (None for ICMP).
        limit: Maximum rows to inspect.

    Returns:
        Number of consecutive failures.
    """
    logger.debug(f"Counting consecutive failures for {host_address}/{check_type}/{port} (limit={limit})")
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("""
            SELECT status FROM check_results
            WHERE host_address = ? AND check_type = ? AND port IS ?
            ORDER BY checked_at DESC, id DESC
            LIMIT ?
        """, (host_address, check_type, port, limit)).fetchall()
        count = 0
        for (status,) in rows:
            if status in ('DOWN', 'CLOSED'):
                count += 1
            else:
                break
        return count
    finally:
        conn.close()


def count_consecutive_passes(db_path: str, host_address: str, check_type: str, port: int | None, limit: int) -> int:
    """Count consecutive passing statuses (UP/OPEN) from newest to oldest.

    Args:
        db_path: Path to the SQLite database file.
        host_address: Host address.
        check_type: 'ICMP' or 'TCP'.
        port: Port number (None for ICMP).
        limit: Maximum rows to inspect.

    Returns:
        Number of consecutive passing results.
    """
    logger.debug(f"Counting consecutive passes for {host_address}/{check_type}/{port} (limit={limit})")
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("""
            SELECT status FROM check_results
            WHERE host_address = ? AND check_type = ? AND port IS ?
            ORDER BY checked_at DESC, id DESC
            LIMIT ?
        """, (host_address, check_type, port, limit)).fetchall()
        count = 0
        for (status,) in rows:
            if status in ('UP', 'OPEN'):
                count += 1
            else:
                break
        return count
    finally:
        conn.close()


def count_recent_alerts(db_path: str, host_address: str, check_type: str, port: int | None, window_minutes: int) -> int:
    """Count alert rows for a track within the rolling flap window.

    Args:
        db_path: Path to the SQLite database file.
        host_address: Host address.
        check_type: 'ICMP' or 'TCP'.
        port: Port number (None for ICMP).
        window_minutes: Rolling window in minutes.

    Returns:
        Number of alert rows in the window.
    """
    logger.debug(f"Counting recent alerts for {host_address}/{check_type}/{port} (window={window_minutes}m)")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("""
            SELECT COUNT(*) FROM alerts
            WHERE host_address = ? AND check_type = ? AND port IS ?
              AND triggered_at >= datetime('now', ? || ' minutes')
        """, (host_address, check_type, port, f'-{window_minutes}')).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_open_alerts(db_path: str, host_address: str | None = None, check_type: str | None = None, port: int | None = None) -> list[dict[str, Any]]:
    """Get currently open (unresolved) alerts, optionally filtered by track.

    Args:
        db_path: Path to the SQLite database file.
        host_address: Optional host address filter.
        check_type: Optional check type filter.
        port: Optional port filter.

    Returns:
        List of alert dicts.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        conditions = ["resolved_at IS NULL"]
        params: list[Any] = []
        if host_address is not None:
            conditions.append("host_address = ?")
            params.append(host_address)
        if check_type is not None:
            conditions.append("check_type = ?")
            params.append(check_type)
        if port is not None:
            conditions.append("port IS ?")
            params.append(port)
        where_clause = " AND ".join(conditions)
        cursor = conn.execute(f"""
            SELECT * FROM alerts
            WHERE {where_clause}
            ORDER BY triggered_at DESC
        """, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_open_alert_for_track(db_path: str, host_address: str, check_type: str, port: int | None) -> dict[str, Any] | None:
    """Get the single open alert for a specific track.

    Args:
        db_path: Path to the SQLite database file.
        host_address: Host address.
        check_type: 'ICMP' or 'TCP'.
        port: Port number (None for ICMP).

    Returns:
        Alert dict or None.
    """
    alerts = get_open_alerts(db_path, host_address, check_type, port)
    return alerts[0] if alerts else None


def get_open_flapping_alert(db_path: str, host_address: str, check_type: str, port: int | None) -> dict[str, Any] | None:
    """Get the open FLAPPING alert for a specific track.

    Args:
        db_path: Path to the SQLite database file.
        host_address: Host address.
        check_type: 'ICMP' or 'TCP'.
        port: Port number (None for ICMP).

    Returns:
        Alert dict or None.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT * FROM alerts
            WHERE host_address = ? AND check_type = ? AND port IS ?
              AND severity = 'FLAPPING' AND resolved_at IS NULL
            ORDER BY triggered_at DESC
            LIMIT 1
        """, (host_address, check_type, port))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insert_alert(db_path: str, host_label: str, host_address: str, check_type: str, port: int | None, severity: str) -> int:
    """Insert a new alert row.

    Args:
        db_path: Path to the SQLite database file.
        host_label: Host label.
        host_address: Host address.
        check_type: 'ICMP' or 'TCP'.
        port: Port number (None for ICMP).
        severity: 'WARNING', 'CRITICAL', or 'FLAPPING'.

    Returns:
        The id of the inserted alert.
    """
    logger.debug(f"Inserting {severity} alert for {host_label} ({host_address}/{check_type}/{port})")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("""
            INSERT INTO alerts
            (triggered_at, host_label, host_address, check_type, port, severity, resolved_at, resolved_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            host_label,
            host_address,
            check_type,
            port,
            severity,
            None,
            None
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def resolve_alert(db_path: str, alert_id: int, reason: str) -> None:
    """Resolve an alert by setting resolved_at and resolved_reason.

    Args:
        db_path: Path to the SQLite database file.
        alert_id: The alert id to resolve.
        reason: 'RECOVERED', 'ESCALATED', or 'FLAPPING'.
    """
    logger.debug(f"Resolving alert {alert_id} reason={reason}")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            UPDATE alerts
            SET resolved_at = ?, resolved_reason = ?
            WHERE id = ?
        """, (
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            reason,
            alert_id
        ))
        conn.commit()
    finally:
        conn.close()


def resolve_all_open_alerts_for_track(db_path: str, host_address: str, check_type: str, port: int | None, reason: str) -> int:
    """Resolve all open alerts for a specific track.

    Args:
        db_path: Path to the SQLite database file.
        host_address: Host address.
        check_type: 'ICMP' or 'TCP'.
        port: Port number (None for ICMP).
        reason: Resolution reason.

    Returns:
        Number of alerts resolved.
    """
    logger.debug(f"Resolving all open alerts for {host_address}/{check_type}/{port} reason={reason}")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("""
            UPDATE alerts
            SET resolved_at = ?, resolved_reason = ?
            WHERE host_address = ? AND check_type = ? AND port IS ? AND resolved_at IS NULL
        """, (
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            reason,
            host_address,
            check_type,
            port
        ))
        conn.commit()
        logger.debug(f"Resolved {cursor.rowcount} open alerts for {host_address}/{check_type}/{port}")
        return cursor.rowcount
    finally:
        conn.close()
