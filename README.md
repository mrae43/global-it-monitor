# Global IT Monitor

A Python-based scheduled monitoring system that probes remote hosts via ICMP ping and TCP port checks, persists results to SQLite, and runs on a configurable schedule.

This is **Phase 1** (Core Monitoring Loop) of a 4-phase project. No alerting, dashboard, or distributed deployment yet — just a reliable probe-collect-store cycle.

## Quick Start

```bash
git clone <repo>
cd global-it-monitor
uv sync
cp .env.example .env
uv run python src/main.py
```

## Dependencies

```
uv sync
```

All probe, concurrency, and storage logic uses the Python standard library (`subprocess`, `socket`, `concurrent.futures`, `sqlite3`). Third-party packages are only for scheduling, logging, and config loading.

## Configuration

### Environment (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `MONITOR_DB_PATH` | `data/monitor.db` | SQLite database file path |
| `MONITOR_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING) |
| `MONITOR_INTERVAL_SECONDS` | `60` | Check cycle interval in seconds |
| `MONITOR_MAX_WORKERS` | `20` | ThreadPoolExecutor max workers |
| `MONITOR_PROBE_TIMEOUT` | `3` | Timeout per probe in seconds |

### Host Targets (`config/hosts.yaml`)

```yaml
hosts:
  - label: "Tokyo Office - Web Server"
    host: "203.0.113.10"
    ports: [80, 443]
```

## Project Structure

```
global-it-monitor/
├── config/
│   └── hosts.yaml            # Host targets (committed)
├── src/
│   ├── main.py               # Entry point — starts scheduler
│   ├── scheduler.py          # APScheduler setup + cycle runner
│   ├── monitor.py            # Orchestrates one full check cycle
│   ├── probes/
│   │   ├── icmp.py           # ICMP ping via subprocess + OS ping
│   │   └── tcp.py            # TCP port check via socket.connect_ex()
│   ├── storage/
│   │   └── database.py       # SQLite read/write (plain sqlite3)
│   └── config/
│       └── loader.py         # .env + YAML config loading
├── tests/
│   ├── test_icmp.py
│   ├── test_tcp.py
│   ├── test_database.py
│   ├── test_config_loader.py
│   ├── test_main.py
│   ├── test_monitor.py
│   └── test_scheduler.py
├── .env.example
├── pyproject.toml
├── uv.lock
└── README.md
```

## Architecture Decisions

| Decision | Approach | Package |
|---|---|---|
| ICMP probe | OS `ping` via `subprocess` | stdlib |
| TCP port check | `socket.connect_ex()` | stdlib |
| Concurrency | `ThreadPoolExecutor` | stdlib |
| Storage | SQLite via `sqlite3` | stdlib |
| Scheduling | APScheduler `BlockingScheduler` | `apscheduler` |
| Logging | `loguru` with file rotation | `loguru` |
| Host config | YAML via `PyYAML` | `pyyaml` |
| Secrets | `.env` via `python-dotenv` | `python-dotenv` |

See `docs/ADR/monitoring-loop-ADR.md` for full rationale on all 12 ADRs.

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS check_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at  TEXT    NOT NULL,   -- UTC ISO-8601
    host_label  TEXT    NOT NULL,
    host_ip     TEXT    NOT NULL,
    check_type  TEXT    NOT NULL,   -- 'ICMP' | 'TCP'
    port        INTEGER,            -- NULL for ICMP
    status      TEXT    NOT NULL,   -- 'UP'|'DOWN'|'OPEN'|'CLOSED'
    latency_ms  REAL                -- NULL if unreachable
);
```

Append-only writes — no UPDATE or DELETE in Phase 1.

## Out of Scope (Phase 1)

- Alerting / notifications (Phase 2)
- HTTP endpoint checks (Phase 2)
- DNS resolution checks (Phase 2)
- SNMP checks (Phase 3)
- Web dashboard (Phase 4)
- Distributed / multi-agent deployment (Phase 3)
- Hot-reload of config
- Data retention / auto-purge (Phase 3)
