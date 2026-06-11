# AGENTS.md

## Project Status

Phase 1 is **not yet implemented** — only design docs exist. The authoritative specs are:
- `docs/PRD/monitoring-loop-PRD.md` — requirements, data design, config design, project structure
- `docs/ADR/monitoring-loop-ADR.md` — architectural decisions and rationale (12 ADRs)

If code and docs conflict, the ADR/PRD are the source of truth. Follow them unless you have a concrete reason to deviate.

## Project Structure (Planned)

```
src/
  main.py              # Entry point — starts scheduler
  scheduler.py         # APScheduler setup + cycle runner
  probes/
    icmp.py            # ICMP ping via subprocess + OS ping
    tcp.py             # TCP port check via socket.connect_ex()
  storage/
    database.py         # SQLite read/write via sqlite3 (no ORM)
  config/
    loader.py           # .env + YAML config loading
config/
  hosts.yaml            # Host targets (committed, no secrets)
.env                    # Secrets & settings (gitignored)
.env.example            # Template (committed)
tests/
  test_icmp.py
  test_tcp.py
  test_database.py
```

The current `config/loader.py` at the repo root is a stale placeholder — real config loading code belongs in `src/config/loader.py`.

## Key Architectural Decisions

- **ICMP**: Use `subprocess` + OS `ping` binary (not raw sockets, not `ping3`). Output format differs between Windows (`time=12ms`) and Linux/macOS (`time=12.3 ms`) — must use a platform-aware regex.
- **TCP**: Use `socket.connect_ex()` (returns int, no exception). Always close sockets in a `finally` block.
- **Concurrency**: `ThreadPoolExecutor` (not `asyncio`, not `threading.Thread`). Each host's ICMP + all TCP ports are one unit of work.
- **Scheduler**: `APScheduler` with `BlockingScheduler` and `max_instances=1` to prevent cycle overlap.
- **Storage**: Raw `sqlite3` (no ORM). Append-only INSERT — no UPDATE or DELETE. Single `check_results` table, no `hosts` table (denormalized).
- **Timestamps**: Always `datetime.now(timezone.utc).isoformat()`. Never `datetime.utcnow()` — it returns naive datetimes.
- **Logging**: `loguru` (not stdlib `logging`). Initialized once in `src/main.py`, imported elsewhere.
- **Config**: `python-dotenv` for `.env`, `PyYAML` for `config/hosts.yaml`. Loaded at startup only, no hot-reload.

## Dependencies

```
uv sync
```

All probe, concurrency, and storage logic uses the Python standard library. Third-party packages are only for scheduling, logging, and config.

## SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS check_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at  TEXT NOT NULL,
    host_label  TEXT NOT NULL,
    host_ip     TEXT NOT NULL,
    check_type  TEXT NOT NULL,   -- 'ICMP' or 'TCP'
    port        INTEGER,          -- NULL for ICMP
    status      TEXT NOT NULL,    -- 'UP'|'DOWN'|'OPEN'|'CLOSED'
    latency_ms  REAL              -- NULL if unreachable
);
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `MONITOR_DB_PATH` | `data/monitor.db` | SQLite database file path |
| `MONITOR_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING) |
| `MONITOR_INTERVAL_SECONDS` | `60` | Check cycle interval in seconds |
| `MONITOR_MAX_WORKERS` | `20` | ThreadPoolExecutor max workers |
| `MONITOR_PROBE_TIMEOUT` | `3` | Timeout per probe in seconds |

## Host Config Schema (`config/hosts.yaml`)

```yaml
hosts:
  - label: "Tokyo Office - Web Server"
    host: "203.0.113.10"
    ports: [80, 443]
```

Each host requires `label` (string), `host` (string), `ports` (list of ints). Invalid entries are logged and skipped at startup.

## Phase 1 Scope Boundaries

Not in scope for Phase 1 (do not implement):
- Alerting / notifications
- HTTP endpoint checks
- DNS resolution checks
- SNMP checks
- Web dashboard
- Distributed / multi-agent deployment
- Hot-reload of config
- Data retention / auto-purge

## Gotchas

- `check_same_thread=False` may be needed if SQLite connections are shared across threads in the pool.
- Write results in batch per cycle (collect all, then write), not per-probe, to avoid SQLite write contention.
- `.env` is gitignored — `.env.example` must list all keys with safe placeholder values.
- `data/` and `logs/` directories must be auto-created at runtime if they don't exist.
