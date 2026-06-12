# AGENTS.md

## Project Status

Phase 1 and Phase 2 are **implemented**. The authoritative specs are:
- `docs/PRD/monitoring-loop-PRD.md` — Phase 1 requirements, data design, config design, project structure
- `docs/ADR/monitoring-loop-ADR.md` — Phase 1 architectural decisions and rationale (12 ADRs)
- `docs/PRD/alert-engine-PRD.md` — Phase 2 requirements, schema, flow
- `docs/ADR/alert-engine-ADR.md` — Phase 2 architectural decisions and rationale (5 ADRs)

If code and docs conflict, the ADR/PRD are the source of truth. Follow them unless you have a concrete reason to deviate.

## Project Structure (Implemented)

```
src/
  main.py              # Entry point — loads config, validates alerts, init DB, starts scheduler
  scheduler.py         # APScheduler BlockingScheduler + cycle runner
  monitor.py           # Orchestrates one full check cycle (ThreadPoolExecutor) + alert engine
  probes/
    icmp.py            # ICMP ping via subprocess + OS ping
    tcp.py             # TCP port check via socket.connect_ex()
  storage/
    __init__.py        # Package marker
    database.py        # SQLite read/write via sqlite3 (no ORM)
  config/
    loader.py          # .env + YAML config loading + alert validation
config/
  hosts.yaml            # Host targets (committed, no secrets)
.env                    # Secrets & settings (gitignored)
.env.example            # Template (committed)
tests/
  test_icmp.py
  test_tcp.py
  test_database.py
  test_config_loader.py
  test_main.py
  test_monitor.py
  test_scheduler.py
  test_alert_engine.py  # Phase 2 alert engine tests
```

## Key Architectural Decisions

- **ICMP**: Use `subprocess` + OS `ping` binary (not raw sockets, not `ping3`). Output format differs between Windows (`time=12ms`) and Linux/macOS (`time=12.3 ms`) — must use a platform-aware regex.
- **TCP**: Use `socket.connect_ex()` (returns int, no exception). Always close sockets in a `finally` block.
- **Concurrency**: `ThreadPoolExecutor` (not `asyncio`, not `threading.Thread`). Each host's ICMP + all TCP ports are one unit of work.
- **Scheduler**: `APScheduler` with `BlockingScheduler` and `max_instances=1` to prevent cycle overlap.
- **Storage**: Raw `sqlite3` (no ORM). Append-only INSERT — no UPDATE or DELETE on `check_results`. Single `check_results` table + `alerts` table.
- **Alert Engine**: Stateless threshold evaluation — queries `check_results` each cycle, counts consecutive failures. No in-memory counters. Lives in `src/monitor.py`.
- **Alert Lifecycle**: Escalation-with-promotion (resolve WARNING as ESCALATED, insert CRITICAL). Auto-resolve on 1 passing result. Flap detection → FLAPPING severity, stabilisation after 3 consecutive passes.
- **Timestamps**: Always `datetime.now(timezone.utc).isoformat()`. Never `datetime.utcnow()` — it returns naive datetimes.
- **Logging**: `loguru` (not stdlib `logging`). Initialized once in `src/main.py`, imported elsewhere.
- **Config**: `python-dotenv` for `.env`, `PyYAML` for `config/hosts.yaml`. Loaded at startup only, no hot-reload.

## Dependencies

```
uv sync
```

All probe, concurrency, storage, and alert logic uses the Python standard library. Third-party packages are only for scheduling, logging, and config.

## SQLite Schema

### `check_results` table

```sql
CREATE TABLE IF NOT EXISTS check_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at  TEXT NOT NULL,
    host_label  TEXT NOT NULL,
    host_address TEXT NOT NULL,
    check_type  TEXT NOT NULL,   -- 'ICMP' or 'TCP'
    port        INTEGER,          -- NULL for ICMP
    status      TEXT NOT NULL,    -- 'UP'|'DOWN'|'OPEN'|'CLOSED'
    latency_ms  REAL              -- NULL if unreachable
);

CREATE INDEX IF NOT EXISTS idx_check_results_track_time
  ON check_results(host_address, check_type, port, checked_at DESC);
```

### `alerts` table (Phase 2)

```sql
CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at    TEXT NOT NULL,
    host_label      TEXT NOT NULL,
    host_address    TEXT NOT NULL,
    check_type      TEXT NOT NULL,
    port            INTEGER,
    severity        TEXT NOT NULL,   -- 'WARNING' | 'CRITICAL' | 'FLAPPING'
    resolved_at     TEXT,            -- NULL means open
    resolved_reason TEXT             -- 'RECOVERED' | 'ESCALATED' | 'FLAPPING' | NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_track_time
  ON alerts(host_address, check_type, port, triggered_at DESC);
```

- `alerts` is **append-dominated but NOT strictly append-only** — `UPDATE alerts SET resolved_at = ...` is the only write mutation. `check_results` retains its strict append-only contract.
- At most one open alert per track at any time.
- `host_address` is the canonical column name (renamed from `host_ip` in Phase 1).

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `MONITOR_DB_PATH` | `data/monitor.db` | SQLite database file path |
| `MONITOR_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING) |
| `MONITOR_INTERVAL_SECONDS` | `60` | Check cycle interval in seconds |
| `MONITOR_MAX_WORKERS` | `20` | ThreadPoolExecutor max workers |
| `MONITOR_PROBE_TIMEOUT` | `3` | Timeout per probe in seconds |
| `MONITOR_WARNING_THRESHOLD` | `3` | Consecutive failures to trigger WARNING |
| `MONITOR_CRITICAL_THRESHOLD` | `5` | Consecutive failures to trigger CRITICAL |
| `MONITOR_FLAP_TRANSITIONS` | `3` | Alert rows within window to trigger FLAPPING |
| `MONITOR_FLAP_WINDOW_MINUTES` | `10` | Rolling time window for flap detection |
| `MONITOR_STABILISATION_THRESHOLD` | `3` | Consecutive passing results to exit FLAPPING |

Startup validation rules:
- `CRITICAL_THRESHOLD > WARNING_THRESHOLD` (both positive integers)
- `FLAP_TRANSITIONS >= 2`
- `FLAP_WINDOW_MINUTES > 0`
- `STABILISATION_THRESHOLD >= 1`

## Host Config Schema (`config/hosts.yaml`)

```yaml
hosts:
  - label: "Tokyo Office - Web Server"
    host: "203.0.113.10"
    ports: [80, 443]
```

Each host requires `label` (string), `host` (string), `ports` (list of ints). Invalid entries are logged and skipped at startup.

## Phase 2 Scope Boundaries

Not in scope for Phase 2 (do not implement):
- Alert notification dispatch (email, Slack, PagerDuty, webhook)
- Per-host alert threshold overrides
- HTTP endpoint checks
- DNS resolution checks
- SNMP checks
- Web dashboard
- Distributed / multi-agent deployment
- Hot-reload of config
- Data retention / auto-purge

## Code Change Best Practices

When modifying or extending the codebase, follow these four principles:

1. **Test at each level — don't integrate prematurely**
   Each layer (probes, storage, config, scheduler, alert engine) must be independently testable and verified before wiring it into the next layer. Do not move to Step 3 (DB integration) until Step 2 (probe logic) is solid. Keep tests passing at every commit.

2. **Use type hints and docstrings**
   All new functions and classes must include type hints and docstrings. This is the contract for future maintainers and for static-analysis tooling.

3. **Log strategically**
   Use `loguru` from the start. Log at meaningful decision points (probe dispatch, threshold crossings, alert state transitions, config skips, DB write batches). Avoid noisy debug logs inside tight loops; prefer a single summary line per cycle.

4. **Handle errors gracefully**
   A single bad host or malformed config entry must never crash the whole system. Catch and log exceptions at the probe level, the per-host thread level, and the cycle level. Continue with the remaining hosts.

## Gotchas

- `check_same_thread=False` may be needed if SQLite connections are shared across threads in the pool.
- Write results in batch per cycle (collect all, then write), not per-probe, to avoid SQLite write contention.
- `.env` is gitignored — `.env.example` must list all keys with safe placeholder values.
- `data/` and `logs/` directories must be auto-created at runtime if they don't exist.
- The `host_address` column was renamed from `host_ip` in Phase 2. `init_database()` includes an `ALTER TABLE ... RENAME COLUMN` migration for existing databases.
- Flap detection fires **before** threshold escalation in `evaluate_track()` — it short-circuits normal alerting for oscillating tracks.
- Stabilisation requires **3 consecutive passing results** — stricter than auto-resolve's 1 pass. Asymmetric by design.
- `count_recent_alerts()` uses SQLite's `datetime('now', ? || ' minutes')` for the rolling window. `triggered_at` values are stored in SQLite-compatible UTC datetime format (`YYYY-MM-DD HH:MM:SS`), matching SQLite's `datetime('now')` which returns UTC.
- **Test pattern**: database tests use real SQLite via `tempfile.mkdtemp()` (no mocking). Monitor tests use `unittest.mock.patch` on probe and DB functions. Config tests use `patch.dict(os.environ, {}, clear=True)`.
