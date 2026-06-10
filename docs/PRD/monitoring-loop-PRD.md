# PRD — Phase 1: Core Monitoring Loop
**Project:** Python-Based Global IT Infrastructure Monitor & Automated Alerting System  
**Phase:** 1 of 4  
**Status:** Draft  
**Author:** *[Your Name]*  
**Created:** 2026-06-11  
**Last Updated:** 2026-06-11

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [Background & Context](#3-background--context)
4. [User Stories](#4-user-stories)
5. [Functional Requirements](#5-functional-requirements)
6. [Technical Specification](#6-technical-specification)
7. [Package Decision Matrix](#7-package-decision-matrix)
8. [Data Design](#8-data-design)
9. [Configuration Design](#9-configuration-design)
10. [Project Structure](#10-project-structure)
11. [Constraints & Assumptions](#11-constraints--assumptions)
12. [Out of Scope (Phase 1)](#12-out-of-scope-phase-1)
13. [Success Metrics](#13-success-metrics)
14. [Risks & Mitigations](#14-risks--mitigations)
15. [Glossary](#15-glossary)

---

## 1. Overview

### 1.1 Summary

Phase 1 delivers the **core monitoring loop**: a scheduled Python process that reads a list of target hosts from a config file, runs ICMP ping checks and TCP port checks against each host concurrently, and writes all results to a local SQLite database for persistence and later querying.

This phase establishes the engine that every subsequent phase builds on. No alerting, no dashboard, no SNMP — just the probe-collect-store cycle running reliably on a schedule.

### 1.2 Target Audience

| Role | Interest |
|------|----------|
| IT Infrastructure Engineer | Wants automated reachability checks replacing manual pings |
| IT Manager | Wants a history log of uptime per host |
| Portfolio Reviewer | Evaluates Python skills, architecture decisions, and engineering maturity |

### 1.3 Deliverable Summary

A single runnable Python project that:
- Reads host targets from a `.env` + `config.yaml` file
- Pings each host (ICMP) and checks its port (TCP) concurrently
- Logs every result to SQLite with a timestamp
- Runs this cycle on a configurable schedule (e.g. every 60 seconds)
- Outputs structured logs to console and a log file

---

## 2. Goals & Non-Goals

### Goals

- Establish a working, concurrent, scheduled monitoring loop
- Persist all check results to SQLite for future querying
- Use plain Python where it's sufficient; use packages only where they add clear value
- Write clean, well-structured code suitable for a professional portfolio
- Handle errors gracefully (unreachable host, timeout, permission denied) without crashing

### Non-Goals (covered in later phases)

- No alerting or notifications (Phase 2)
- No HTTP endpoint checks (Phase 2)
- No SNMP checks (Phase 3)
- No dashboard or web UI (Phase 4)
- No DNS checks (Phase 2)
- No remote/multi-agent deployment

---

## 3. Background & Context

### 3.1 Why this project exists

The target job role (IT Infrastructure + Network + Security, global sites) requires:
- Automation scripting for system management
- Remote incident support for international locations
- Proactive monitoring and anomaly detection

A purpose-built monitoring tool demonstrates all three competencies in one portfolio piece.

### 3.2 Why build Phase 1 first

Before alerting or metrics are useful, you need a **reliable data collection pipeline**. Phase 1 is that pipeline. It answers the most fundamental question in infrastructure monitoring:

> "Is this host reachable, and is its service running?"

Every higher-level feature (alerting, dashboards, trends) depends on this data being collected consistently.

### 3.3 Networking concepts this phase covers

| Concept | Applied where |
|---------|---------------|
| ICMP (ping) | Reachability check via `subprocess` |
| TCP socket | Port open/closed check via `socket` |
| Timeout behavior | Handling unreachable hosts without hanging |
| IP vs hostname | Both supported in config |
| Cross-platform differences | `ping` command flags differ on Windows vs Linux/macOS |

---

## 4. User Stories

### US-01 — Define hosts to monitor
**As an** IT engineer,  
**I want to** define a list of hosts and ports in a config file,  
**so that** I can change what is monitored without touching the code.

**Acceptance Criteria:**
- Config file supports hostname or IP address
- Config file supports a list of ports per host
- Config file supports a human-readable label for each host
- App loads config on startup; invalid entries are logged and skipped

---

### US-02 — ICMP ping check
**As an** IT engineer,  
**I want to** run a ping check against each host,  
**so that** I know if the host is alive at the network layer.

**Acceptance Criteria:**
- Sends 1 ICMP packet per check cycle
- Returns `UP` or `DOWN` with latency in milliseconds
- Times out after a configurable number of seconds (default: 3s)
- Works on Windows, Linux, and macOS

---

### US-03 — TCP port check
**As an** IT engineer,  
**I want to** check if a specific port on each host is open,  
**so that** I know if the service (web, SSH, database) is running.

**Acceptance Criteria:**
- Connects to the target host:port using raw TCP socket
- Returns `OPEN` or `CLOSED`
- Times out after a configurable number of seconds (default: 3s)
- Multiple ports per host are each checked independently

---

### US-04 — Concurrent execution
**As an** IT engineer,  
**I want to** check all hosts at the same time,  
**so that** a slow or unreachable host doesn't delay the entire cycle.

**Acceptance Criteria:**
- All host checks run concurrently in the same cycle
- One host timing out does not block others
- Maximum thread count is configurable (default: 20)

---

### US-05 — Persist results to SQLite
**As an** IT engineer,  
**I want to** store all check results in a local database,  
**so that** I can query uptime history and review past incidents.

**Acceptance Criteria:**
- Every check result is written to SQLite with a UTC timestamp
- Schema records: host label, IP, port, check type, result, latency, timestamp
- Database file path is configurable
- Database and tables are auto-created on first run

---

### US-06 — Scheduled monitoring loop
**As an** IT engineer,  
**I want to** run checks automatically on a schedule,  
**so that** I don't have to manually trigger them.

**Acceptance Criteria:**
- Check interval is configurable (in seconds)
- Loop runs until the process is stopped (Ctrl+C)
- Each cycle logs a summary (X hosts checked, Y UP, Z DOWN)
- Skips a cycle if the previous one is still running (no overlap)

---

### US-07 — Structured logging
**As a** developer reviewing the project,  
**I want to** see clear, structured logs,  
**so that** I can understand what happened and when.

**Acceptance Criteria:**
- Logs are written to both console and a rotating log file
- Each log entry includes: timestamp, level, host, check type, result
- Log level is configurable (`DEBUG`, `INFO`, `WARNING`)
- Log file rotates at 5MB, keeping last 3 files

---

## 5. Functional Requirements

### FR-01: Configuration loading
- The system MUST read host targets from `config/hosts.yaml`
- The system MUST read secrets and environment settings from `.env`
- The system MUST validate config on startup and exit with a clear error if the config is missing or malformed

### FR-02: ICMP probe
- The system MUST perform ICMP ping using the OS `ping` command via `subprocess`
- The system MUST parse the output to extract round-trip latency in milliseconds
- The system MUST handle permission errors gracefully (ICMP requires root on some systems)

### FR-03: TCP probe
- The system MUST attempt a TCP connection using Python's built-in `socket` module
- The system MUST record the connection time as latency
- The system MUST support checking multiple ports per host

### FR-04: Concurrency
- The system MUST use `concurrent.futures.ThreadPoolExecutor` for parallel checks
- The system MUST not allow one timed-out check to block others

### FR-05: Storage
- The system MUST auto-create the SQLite database and schema on first run
- The system MUST write every check result as a new row (append-only)
- The system MUST use UTC timestamps in all stored records

### FR-06: Scheduler
- The system MUST run the full check cycle on a configurable interval
- The system MUST use `APScheduler` for scheduling (see Package Decision Matrix)
- The system MUST gracefully handle `KeyboardInterrupt` and shut down cleanly

### FR-07: Logging
- The system MUST use `loguru` for structured logging (see Package Decision Matrix)
- The system MUST write logs to both stdout and `logs/monitor.log`
- The system MUST rotate log files automatically

---

## 6. Technical Specification

### 6.1 High-Level Flow

```
START
  ↓
Load config (hosts.yaml + .env)
  ↓
Initialize SQLite DB (create tables if not exist)
  ↓
Start scheduler loop (every N seconds)
  ↓
  ┌─────────────────────────────────────────────┐
  │  For each host (concurrent):                │
  │    → Run ICMP ping probe                    │
  │    → Run TCP port probe (per port)          │
  │    → Collect: result, latency, timestamp    │
  └─────────────────────────────────────────────┘
  ↓
Write all results to SQLite
  ↓
Log cycle summary
  ↓
Wait for next interval
  ↓
(Repeat until Ctrl+C)
```

### 6.2 ICMP Probe Logic

```python
import subprocess
import platform
import re
import time

def ping(host: str, timeout: int = 3) -> dict:
    """
    Sends one ICMP ping to the host.
    Uses subprocess + OS ping command (plain Python).
    Returns: { 'status': 'UP'|'DOWN', 'latency_ms': float|None }
    """
    # OS-specific ping flags
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'

    try:
        result = subprocess.run(
            ['ping', param, '1', timeout_param, str(timeout), host],
            capture_output=True,
            text=True,
            timeout=timeout + 2
        )
        if result.returncode == 0:
            # Parse latency from output
            match = re.search(r'time[=<]([\d.]+)', result.stdout)
            latency = float(match.group(1)) if match else None
            return {'status': 'UP', 'latency_ms': latency}
        else:
            return {'status': 'DOWN', 'latency_ms': None}

    except (subprocess.TimeoutExpired, Exception):
        return {'status': 'DOWN', 'latency_ms': None}
```

### 6.3 TCP Probe Logic

```python
import socket
import time

def check_port(host: str, port: int, timeout: int = 3) -> dict:
    """
    Attempts a TCP connection to host:port.
    Uses Python's built-in socket module (plain Python).
    Returns: { 'status': 'OPEN'|'CLOSED', 'latency_ms': float|None }
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    start = time.time()
    try:
        result = sock.connect_ex((host, port))
        latency = (time.time() - start) * 1000  # convert to ms

        if result == 0:
            return {'status': 'OPEN', 'latency_ms': round(latency, 2)}
        else:
            return {'status': 'CLOSED', 'latency_ms': None}

    except (socket.timeout, socket.error):
        return {'status': 'CLOSED', 'latency_ms': None}

    finally:
        sock.close()
```

### 6.4 Concurrent Execution

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def run_all_checks(hosts: list, max_workers: int = 20) -> list:
    """
    Runs all probes concurrently using ThreadPoolExecutor.
    Plain Python standard library — no third-party needed.
    """
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_checks_for_host, host): host
            for host in hosts
        }
        for future in as_completed(futures):
            try:
                results.extend(future.result())
            except Exception as e:
                logger.warning(f"Check failed: {e}")

    return results
```

### 6.5 SQLite Storage

```python
import sqlite3
from datetime import datetime, timezone

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS check_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at  TEXT NOT NULL,        -- UTC ISO-8601 timestamp
    host_label  TEXT NOT NULL,        -- Human-readable name e.g. "Tokyo Office"
    host_ip     TEXT NOT NULL,        -- IP or hostname
    check_type  TEXT NOT NULL,        -- 'ICMP' or 'TCP'
    port        INTEGER,              -- NULL for ICMP checks
    status      TEXT NOT NULL,        -- 'UP', 'DOWN', 'OPEN', 'CLOSED'
    latency_ms  REAL                  -- NULL if unreachable
);
"""

def save_results(db_path: str, results: list):
    """
    Writes check results to SQLite.
    Uses Python's built-in sqlite3 module (plain Python).
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(CREATE_TABLE_SQL)

    for r in results:
        cursor.execute("""
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
```

---

## 7. Package Decision Matrix

> **Principle:** Use plain Python where the standard library is sufficient. Use a package only when it saves meaningful complexity or prevents real errors.

| Concern | Plain Python option | Package chosen | Reason for choice |
|---------|--------------------|----|---|
| ICMP ping | `subprocess` + `os ping` | ✅ **plain Python** | Standard library is fully sufficient |
| TCP port check | `socket.connect_ex()` | ✅ **plain Python** | Built-in socket is exactly right here |
| Concurrency | `concurrent.futures` | ✅ **plain Python** | ThreadPoolExecutor covers this well |
| SQLite storage | `sqlite3` | ✅ **plain Python** | Built-in, stable, no ORM needed at this stage |
| Scheduling | `time.sleep()` loop | 📦 **APScheduler** | Handles missed runs, overlap prevention, and clean shutdown out of the box |
| Logging | `logging` module | 📦 **loguru** | File rotation + colored console + one-line setup vs 20+ lines of boilerplate |
| Config (secrets) | `os.environ` | 📦 **python-dotenv** | Loads `.env` file cleanly; standard practice for secret management |
| Config (hosts) | `json` / `configparser` | 📦 **PyYAML** | YAML is more readable for host lists with nested port configs |

### Package install summary

```
pip install apscheduler loguru python-dotenv pyyaml
```

All core probing, concurrency, and storage logic uses **plain Python only**.

---

## 8. Data Design

### 8.1 SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS check_results (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    checked_at  TEXT     NOT NULL,   -- '2026-06-11T08:30:00+00:00'
    host_label  TEXT     NOT NULL,   -- 'Tokyo Office Web Server'
    host_ip     TEXT     NOT NULL,   -- '203.0.113.10' or 'tokyo.company.com'
    check_type  TEXT     NOT NULL,   -- 'ICMP' | 'TCP'
    port        INTEGER,             -- 80, 443, 22, etc. (NULL for ICMP)
    status      TEXT     NOT NULL,   -- 'UP' | 'DOWN' | 'OPEN' | 'CLOSED'
    latency_ms  REAL                 -- 12.4 (NULL if unreachable)
);
```

### 8.2 Example rows

| checked_at | host_label | host_ip | check_type | port | status | latency_ms |
|---|---|---|---|---|---|---|
| 2026-06-11T08:30:00Z | Tokyo Office | 203.0.113.10 | ICMP | NULL | UP | 24.3 |
| 2026-06-11T08:30:00Z | Tokyo Office | 203.0.113.10 | TCP | 80 | OPEN | 31.1 |
| 2026-06-11T08:30:00Z | Tokyo Office | 203.0.113.10 | TCP | 443 | OPEN | 29.8 |
| 2026-06-11T08:30:00Z | London Office | 198.51.100.5 | ICMP | NULL | DOWN | NULL |
| 2026-06-11T08:30:00Z | London Office | 198.51.100.5 | TCP | 22 | CLOSED | NULL |

### 8.3 Useful queries for later phases

```sql
-- Last known status per host
SELECT host_label, host_ip, check_type, port, status, latency_ms, checked_at
FROM check_results
WHERE id IN (
    SELECT MAX(id) FROM check_results GROUP BY host_ip, check_type, port
);

-- All DOWN events in the last 24 hours
SELECT * FROM check_results
WHERE status IN ('DOWN', 'CLOSED')
AND checked_at > datetime('now', '-1 day')
ORDER BY checked_at DESC;

-- Average latency per host (last 1 hour)
SELECT host_label, check_type, port, ROUND(AVG(latency_ms), 2) AS avg_latency
FROM check_results
WHERE latency_ms IS NOT NULL
AND checked_at > datetime('now', '-1 hour')
GROUP BY host_label, check_type, port;
```

---

## 9. Configuration Design

### 9.1 `.env` file (secrets & environment settings)

```dotenv
# .env — do NOT commit to git
MONITOR_DB_PATH=data/monitor.db
MONITOR_LOG_LEVEL=INFO
MONITOR_INTERVAL_SECONDS=60
MONITOR_MAX_WORKERS=20
MONITOR_PROBE_TIMEOUT=3
```

### 9.2 `config/hosts.yaml` (host targets)

```yaml
# config/hosts.yaml — safe to commit (no secrets)
hosts:
  - label: "Tokyo Office - Web Server"
    host: "203.0.113.10"
    ports: [80, 443]

  - label: "London Office - SSH Gateway"
    host: "198.51.100.5"
    ports: [22]

  - label: "Singapore DB Server"
    host: "db.sg.company.internal"
    ports: [3306, 5432]

  - label: "Sydney VPN Gateway"
    host: "vpn.au.company.com"
    ports: [1194, 443]

  - label: "Google DNS (external baseline)"
    host: "8.8.8.8"
    ports: [53]
```

> **Design note:** Separating hosts (YAML) from secrets (.env) follows the [12-factor app](https://12factor.net/) principle. Config that changes per environment stays in `.env`; monitored hosts can safely live in version control.

---

## 10. Project Structure

```
global-it-monitor/
│
├── config/
│   └── hosts.yaml              # Host targets (committed to git)
│
├── data/
│   └── monitor.db              # SQLite database (gitignored)
│
├── logs/
│   └── monitor.log             # Rotating log file (gitignored)
│
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point — starts scheduler
│   ├── scheduler.py            # APScheduler setup + cycle runner
│   ├── probes/
│   │   ├── __init__.py
│   │   ├── icmp.py             # ICMP ping probe (plain Python)
│   │   └── tcp.py              # TCP port probe (plain Python)
│   ├── storage/
│   │   ├── __init__.py
│   │   └── database.py         # SQLite read/write (plain Python)
│   └── config/
│       ├── __init__.py
│       └── loader.py           # .env + YAML config loading
│
├── tests/
│   ├── test_icmp.py
│   ├── test_tcp.py
│   └── test_database.py
│
├── .env                        # Secrets (gitignored)
├── .env.example                # Template (committed to git)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 11. Constraints & Assumptions

| Constraint | Detail |
|---|---|
| ICMP requires elevated permissions on some systems | On Linux, raw ICMP sockets need root or `CAP_NET_RAW`. Workaround: use `subprocess` to call the system `ping` binary (already available to all users) |
| `ping` CLI output format differs by OS | Latency regex must handle Windows (`time=12ms`) and Linux/macOS (`time=12.3 ms`) formatting |
| Monitoring agent runs on a single machine in Phase 1 | Remote/distributed agent support is out of scope until Phase 3 |
| SQLite is single-file, single-writer | Sufficient for Phase 1. Migration to PostgreSQL is a Phase 3+ consideration |
| Target hosts must be reachable from the monitoring machine | Hosts behind NAT, VPN, or strict firewalls may need network-level access pre-configured |
| Config file is read at startup only | Hot-reloading the config without restart is out of scope for Phase 1 |

---

## 12. Out of Scope (Phase 1)

The following are explicitly deferred to later phases:

| Feature | Phase |
|---------|-------|
| Alert engine (thresholds, notifications) | Phase 2 |
| Email / Slack / Teams notifications | Phase 2 |
| HTTP endpoint checks | Phase 2 |
| DNS resolution checks | Phase 2 |
| SNMP checks | Phase 3 |
| Web dashboard (Flask) | Phase 4 |
| SSH-based remote checks | Phase 3 |
| Multi-agent / distributed deployment | Phase 3 |
| Data retention / auto-purge policy | Phase 3 |

---

## 13. Success Metrics

Phase 1 is considered **complete** when all of the following are true:

| # | Metric | Pass condition |
|---|--------|----------------|
| 1 | Monitoring loop runs | Process runs for 30+ minutes without crashing |
| 2 | ICMP probe works | Correctly identifies UP and DOWN hosts |
| 3 | TCP probe works | Correctly identifies OPEN and CLOSED ports |
| 4 | Concurrency works | 10 hosts checked in < 5 seconds (vs ~30 seconds sequential) |
| 5 | SQLite persistence | All results queryable after restart |
| 6 | Schedule is respected | Each cycle starts within 2 seconds of the configured interval |
| 7 | Errors are handled | Unreachable host does not crash the process |
| 8 | Logs are clear | A reviewer can understand what happened from logs alone |
| 9 | Config is clean | Host list changed without editing any `.py` file |

---

## 14. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| ICMP blocked by firewall | High | Medium | Log clearly as "ICMP_BLOCKED" not "DOWN"; fall back to TCP check as secondary confirmation |
| `ping` output format varies unexpectedly | Medium | Low | Use defensive regex with fallback to `None` latency; write unit tests for each OS format |
| Thread pool exhausted by slow hosts | Low | Medium | Set configurable `timeout` per probe; ThreadPoolExecutor handles backpressure |
| SQLite write contention if threads write simultaneously | Low | Medium | Use a single writer thread / queue (or `check_same_thread=False` with care) |
| Config file has invalid host entries | Medium | Low | Validate on startup; skip invalid entries with a warning log |
| Developer forgets to install packages | Low | Low | Provide `requirements.txt` and setup instructions in `README.md` |

---

## 15. Glossary

| Term | Definition |
|------|-----------|
| **ICMP** | Internet Control Message Protocol. Used by `ping` to test reachability at the network layer |
| **TCP** | Transmission Control Protocol. A connection-oriented protocol used to check if a service port is open |
| **Port** | A numbered "door" on a computer (0–65535). Different services listen on different ports |
| **Probe** | A single check action — one ping or one TCP connection attempt |
| **Cycle** | One complete pass through all hosts and all their checks |
| **SQLite** | A lightweight, file-based SQL database. No server required |
| **APScheduler** | Python package for scheduling jobs at fixed intervals |
| **ThreadPoolExecutor** | Python standard library tool for running multiple tasks concurrently using threads |
| **Latency** | Round-trip time in milliseconds from sending a probe to receiving a response |
| **UP / DOWN** | Status result for ICMP checks |
| **OPEN / CLOSED** | Status result for TCP port checks |
| **OID** | Object Identifier — used in SNMP (Phase 3) to specify what metric to query |
| **.env file** | A plain text file holding environment variables and secrets, never committed to git |

---

*End of PRD — Phase 1: Core Monitoring Loop*

> **Next document:** Phase 2 PRD will cover the Alert Engine (threshold logic, flap detection, DNS checks, email/Slack notifications).