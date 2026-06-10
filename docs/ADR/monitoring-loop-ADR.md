# ADR — Phase 1: Core Monitoring Loop
**Project:** Python-Based Global IT Infrastructure Monitor & Automated Alerting System  
**Phase:** 1 of 4  
**Status:** Accepted  
**Author:** *[Your Name]*  
**Created:** 2026-06-11  
**Last Updated:** 2026-06-11

---

## What is an ADR?

An Architecture Decision Record (ADR) documents a significant technical decision: **what was decided, why it was decided that way, what alternatives were considered, and what trade-offs were accepted.**

Every ADR in this document answers one specific question. Future readers (including yourself 6 months later, or a job interviewer) can understand not just *what* the system does, but *why* it was built that way.

---

## Table of Contents

| # | Decision | Status |
|---|----------|--------|
| [ADR-001](#adr-001) | Use `subprocess` + OS `ping` for ICMP probing | Accepted |
| [ADR-002](#adr-002) | Use built-in `socket` for TCP port checking | Accepted |
| [ADR-003](#adr-003) | Use `ThreadPoolExecutor` for concurrency | Accepted |
| [ADR-004](#adr-004) | Use SQLite for result persistence | Accepted |
| [ADR-005](#adr-005) | Use `APScheduler` for the monitoring loop | Accepted |
| [ADR-006](#adr-006) | Use `loguru` for logging | Accepted |
| [ADR-007](#adr-007) | Use YAML for host configuration | Accepted |
| [ADR-008](#adr-008) | Use `.env` + `python-dotenv` for secrets | Accepted |
| [ADR-009](#adr-009) | Use UTC timestamps for all stored records | Accepted |
| [ADR-010](#adr-010) | Append-only write strategy for SQLite | Accepted |
| [ADR-011](#adr-011) | Separate probe results from host config at the data layer | Accepted |
| [ADR-012](#adr-012) | Single-machine deployment for Phase 1 | Accepted |

---

## ADR-001

### Use `subprocess` + OS `ping` for ICMP probing

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

ICMP ping is the first-level reachability check in the monitoring stack. We need to determine if a remote host responds to ICMP echo requests and measure the round-trip latency.

There are two general approaches in Python:

1. Call the operating system's built-in `ping` binary via `subprocess`
2. Construct raw ICMP packets manually using Python's `socket` module at the raw socket level

### Decision

Use `subprocess` to invoke the operating system's `ping` command and parse its stdout for status and latency.

```python
import subprocess, platform, re

param = '-n' if platform.system().lower() == 'windows' else '-c'
result = subprocess.run(
    ['ping', param, '1', host],
    capture_output=True, text=True, timeout=5
)
latency = re.search(r'time[=<]([\d.]+)', result.stdout)
```

### Alternatives Considered

**Option A: Raw ICMP sockets (`socket.SOCK_RAW`)**

Constructing ICMP packets manually gives full control over packet contents and doesn't depend on the OS `ping` binary being present.

Rejected because:
- Raw sockets require `root` / `Administrator` privileges on every supported OS. A monitoring script that can't run without elevated permissions is impractical in most corporate IT environments.
- Implementing ICMP packet construction, checksum calculation, and response parsing from scratch is significant complexity with no benefit at this stage.
- The `icmplib` third-party package wraps this, but it still requires elevated permissions and adds a dependency.

**Option B: Third-party `ping3` package**

`ping3` is a pure-Python ICMP library that abstracts raw socket handling.

Rejected because:
- Still requires root/Administrator for raw socket access on most systems.
- Adds a dependency for functionality the OS `ping` binary already provides for free.

**Option C: subprocess + OS ping (chosen)**

Every major OS ships with a `ping` binary that:
- Works without elevated permissions for basic ICMP echo
- Handles all platform-specific ICMP details internally
- Returns a non-zero exit code when the host is unreachable

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| `ping` output format differs between Windows, Linux, macOS | We handle this with a platform-aware regex and unit tests per OS format |
| Cannot control ICMP packet size or TTL | Not needed for basic up/down monitoring |
| Subprocess fork overhead (~10–30ms per call) | Negligible at our polling interval (60s default) |
| `ping` binary must be present on the system | It is present on all target operating systems by default |

### Consequences

- ICMP probe code lives in `src/probes/icmp.py`
- Unit tests must cover Windows and Linux output format parsing
- Latency parsing returns `None` gracefully if regex fails (host UP but latency unparseable)
- The `platform` module (stdlib) is used to select the correct flag per OS

---

## ADR-002

### Use built-in `socket` for TCP port checking

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

TCP port checking is the second-level probe: confirming that a specific service (web server, SSH, database) is actually listening and accepting connections. We need to check whether a given `host:port` combination accepts a TCP connection.

### Decision

Use Python's built-in `socket` module with `connect_ex()` to attempt a TCP connection and measure the connection latency.

```python
import socket, time

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(timeout)
start = time.time()
result = sock.connect_ex((host, port))
latency_ms = (time.time() - start) * 1000
sock.close()
# result == 0 means OPEN
```

### Alternatives Considered

**Option A: `requests` library for HTTP-specific ports**

`requests.get()` could check port 80/443 and return status codes.

Rejected for Phase 1 because:
- `requests` is an HTTP client, not a generic port checker. It cannot check SSH (22), database (3306), or any non-HTTP port.
- HTTP-level checking is intentionally Phase 2 scope.
- Using `requests` here conflates two distinct check types (TCP connectivity vs HTTP application response).

**Option B: Third-party `portchecker` or `nmap` wrappers**

Libraries like `python-nmap` wrap the `nmap` scanner for comprehensive port scanning.

Rejected because:
- `nmap` is not installed by default on most systems.
- Port scanning tools may trigger security alerts in corporate environments.
- `socket.connect_ex()` does exactly what we need with zero dependencies.

**Option C: Built-in `socket` (chosen)**

The standard library `socket` module provides a direct, low-level TCP connection attempt. `connect_ex()` returns `0` on success and an error code on failure, without raising an exception — making it clean to use in a monitoring loop.

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| TCP connect completes the handshake (SYN/SYN-ACK/ACK) | Slightly more overhead than a SYN-only probe, but confirms real service availability |
| Does not check application-layer response | Intentional — HTTP-level checks are Phase 2 |
| IPv6 not supported in base implementation | IPv4 covers all Phase 1 target hosts; IPv6 support is a Phase 3 enhancement |

### Consequences

- TCP probe code lives in `src/probes/tcp.py`
- Each port configured per host generates a separate check result row in SQLite
- `sock.close()` is always called in a `finally` block to prevent socket leaks

---

## ADR-003

### Use `ThreadPoolExecutor` for concurrency

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

A monitoring cycle must check many hosts simultaneously. Checking hosts sequentially means one timed-out host (e.g. 3 seconds) multiplied by 20 hosts equals 60 seconds minimum per cycle — longer than the default cycle interval. Concurrency is essential.

Python offers several concurrency models: threads, async/await, and multiprocessing.

### Decision

Use `concurrent.futures.ThreadPoolExecutor` from the Python standard library.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(check_host, host): host for host in hosts}
    for future in as_completed(futures):
        results.extend(future.result())
```

### Alternatives Considered

**Option A: `asyncio` with `async/await`**

`asyncio` is Python's native async framework. It is highly efficient for I/O-bound tasks and is the modern preferred approach for network programming.

Rejected for Phase 1 because:
- `subprocess.run()` (used for ICMP ping) is blocking and not natively compatible with `asyncio` without `asyncio.create_subprocess_exec()` — adding meaningful complexity.
- Mixing sync and async code (subprocess + socket) requires careful handling that is better introduced once the learner has solid sync foundations.
- `asyncio` will be reconsidered for Phase 3 when HTTP and SNMP checks are added (both have async-friendly libraries).

**Option B: `multiprocessing`**

Spawns separate OS processes for each check, bypassing Python's GIL entirely.

Rejected because:
- Process spawning overhead is significant for short-lived probe tasks (milliseconds each).
- Network I/O is I/O-bound, not CPU-bound — the GIL is not actually the bottleneck here.
- Inter-process communication (collecting results) adds complexity.

**Option C: Manual `threading.Thread`**

Lower-level threading without the executor abstraction.

Rejected because:
- `ThreadPoolExecutor` provides thread reuse (pool), result collection via `Future`, and clean shutdown — all things you'd have to implement manually with raw threads.
- `ThreadPoolExecutor` is the standard library's recommended high-level interface for exactly this use case.

**Option D: `ThreadPoolExecutor` (chosen)**

- Built into the standard library (`concurrent.futures`)
- Thread pool reuse avoids per-probe thread creation overhead
- `as_completed()` collects results as they arrive, not in submission order
- Clean shutdown when the `with` block exits
- Network I/O (ping, TCP connect) releases the GIL, so threads run truly concurrently for our workload

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| GIL limits true parallelism for CPU-bound code | Our probes are I/O-bound — threads release the GIL during network waits |
| Thread count must be tuned (default: 20) | Configurable via `.env`; 20 threads handles most small-to-medium deployments |
| Thread safety required when writing shared state | We collect results into a list after all futures complete — no shared mutation during execution |

### Consequences

- Max thread count is configurable via `MONITOR_MAX_WORKERS` in `.env`
- Each host's checks (ICMP + all its TCP ports) are submitted as a single unit of work per thread
- Results are collected after the `with` block exits to avoid thread-safety concerns

---

## ADR-004

### Use SQLite for result persistence

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

All probe results must be persisted so that:
- History is available after a restart
- Phase 2 can query recent results to determine alert thresholds
- Uptime/downtime patterns can be analyzed over time

We need a storage backend that is simple to set up, reliable, and queryable with standard SQL.

### Decision

Use Python's built-in `sqlite3` module with a single-file SQLite database.

### Alternatives Considered

**Option A: Plain text / CSV files**

Write results as CSV rows to a flat file.

Rejected because:
- No query capability — you'd need to read and parse the entire file to find recent DOWN events.
- Concurrent writes (even sequential in Phase 1) are error-prone with flat files.
- Not demonstrating any database skill in the portfolio.

**Option B: PostgreSQL / MySQL**

A full relational database server.

Rejected for Phase 1 because:
- Requires a running server process, installation, and credential management.
- Significant setup overhead for a local development and portfolio project.
- SQLite can be migrated to PostgreSQL later with minimal schema changes.

**Option C: SQLAlchemy ORM**

An ORM layer abstracting the database backend.

Rejected for Phase 1 because:
- Adds a third-party dependency and learning curve.
- Raw `sqlite3` with plain SQL is more transparent and educational at this stage.
- ORMs make more sense when models are complex or multiple database backends are needed.

**Option D: SQLite via built-in `sqlite3` (chosen)**

- Zero installation — SQLite is built into Python and the OS
- Standard SQL queries work as expected
- Single-file database is trivially backed up or shared
- `sqlite3` module is part of the standard library
- Sufficient performance for our write rate (a few dozen rows per minute)

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| Single writer at a time | Our architecture uses a single writer thread (results collected, then written in batch) |
| No built-in network access | Not needed — the monitoring agent and DB are on the same machine in Phase 1 |
| Limited concurrency | Append-only writes from a single scheduler thread is sufficient |

### Consequences

- Database file path configured via `MONITOR_DB_PATH` in `.env`
- Schema is auto-created on first run via `CREATE TABLE IF NOT EXISTS`
- All writes are batched per cycle (not per probe) to minimize open/close overhead
- Migration path to PostgreSQL in Phase 3 is straightforward (same SQL, swap connection)

---

## ADR-005

### Use `APScheduler` for the monitoring loop

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

The monitoring cycle must run on a fixed interval (default: every 60 seconds). We need a scheduler that starts the cycle, handles the interval reliably, and prevents two cycles from running simultaneously if one cycle takes longer than expected.

### Decision

Use `APScheduler` (Advanced Python Scheduler) with an `IntervalTrigger`.

```python
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()
scheduler.add_job(run_cycle, 'interval', seconds=interval,
                  max_instances=1,  # prevents overlap
                  misfire_grace_time=30)
scheduler.start()
```

### Alternatives Considered

**Option A: `while True` + `time.sleep()`**

The simplest possible loop.

```python
while True:
    run_cycle()
    time.sleep(interval)
```

Rejected because:
- `time.sleep()` after the cycle means the actual interval is `cycle_duration + sleep_time`, causing drift over time.
- No built-in overlap prevention — if a cycle takes longer than the interval, the next cycle starts immediately on top of it.
- No built-in misfire handling (what happens if the machine wakes from sleep?).
- No clean shutdown mechanism.

**Option B: `schedule` library**

A lightweight scheduling library with a simple API.

Rejected because:
- `schedule` also relies on a `while True` + `time.sleep()` loop internally.
- Does not natively prevent job overlap (`max_instances`).
- `APScheduler` is more widely used in production contexts and more relevant to the job.

**Option C: OS-level cron / Task Scheduler**

Schedule the Python script via `cron` (Linux/macOS) or Windows Task Scheduler.

Rejected for Phase 1 because:
- External dependency on OS configuration — not portable or self-contained.
- Harder to demonstrate in a portfolio (requires OS setup, not just `python main.py`).
- Better suited for Phase 3 when deploying to production infrastructure.

**Option D: APScheduler (chosen)**

- `max_instances=1` prevents cycle overlap natively
- `misfire_grace_time` handles missed runs gracefully
- `BlockingScheduler` keeps `main.py` simple — it blocks until `Ctrl+C`
- Graceful shutdown on `KeyboardInterrupt` is built in
- Well-documented, actively maintained, widely used in IT automation contexts

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| Adds one third-party dependency | The overlap prevention and drift correction alone justify it |
| Slightly more setup than `time.sleep()` | 5 extra lines of code; well worth the reliability gain |

### Consequences

- Scheduler configuration lives in `src/scheduler.py`
- `MONITOR_INTERVAL_SECONDS` in `.env` controls the cycle frequency
- If a cycle takes longer than the interval, the next cycle is skipped (not queued)

---

## ADR-006

### Use `loguru` for logging

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

The monitoring system needs to log:
- Each probe result (host, check type, status, latency)
- Cycle summaries (X checked, Y UP, Z DOWN)
- Errors and warnings (unreachable hosts, config issues)
- Output to both the console (for development) and a rotating log file (for production review)

### Decision

Use the `loguru` third-party library instead of the standard `logging` module.

```python
from loguru import logger

logger.add("logs/monitor.log", rotation="5 MB", retention=3,
           level="INFO", format="{time} | {level} | {message}")

logger.info("Tokyo Office | ICMP | UP | 24.3ms")
logger.warning("London Office | TCP:443 | CLOSED")
logger.error("Config file not found: config/hosts.yaml")
```

### Alternatives Considered

**Option A: Standard library `logging` module**

Python's built-in logging framework.

Rejected because:
- Setting up file rotation + console output + formatting requires ~25 lines of boilerplate (`basicConfig`, `FileHandler`, `RotatingFileHandler`, `Formatter`, `addHandler`).
- The API is verbose for simple use cases — `logging.getLogger(__name__)` repeated in every module.
- Color output in the console requires a third-party handler anyway.

```python
# This is what stdlib logging needs just for basic setup:
import logging
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
fh = RotatingFileHandler('logs/monitor.log', maxBytes=5*1024*1024, backupCount=3)
fh.setFormatter(formatter)
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(ch)
```

**Option B: `loguru` (chosen)**

The same setup in `loguru`:

```python
from loguru import logger
logger.add("logs/monitor.log", rotation="5 MB", retention=3)
```

That's it. Console output with color is the default.

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| Adds a third-party dependency | Saves ~20 lines of boilerplate per module; significantly more readable |
| Less common in legacy codebases than stdlib `logging` | Widely adopted in modern Python; knowledge transfers to most new projects |
| Slightly different API from stdlib | The simpler API is the reason we chose it |

### Consequences

- Logger is initialized once in `src/main.py` and imported everywhere else
- Log level is controlled via `MONITOR_LOG_LEVEL` in `.env`
- Log files live in `logs/` directory (gitignored)
- `retention=3` means a maximum of 3 rotated log files are kept

---

## ADR-007

### Use YAML for host configuration

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

The list of monitored hosts needs to be stored in a config file that:
- Supports nested structure (host → list of ports)
- Is human-readable and easy to edit
- Does not require code changes when hosts are added or removed

### Decision

Use `PyYAML` to read host configuration from `config/hosts.yaml`.

```yaml
hosts:
  - label: "Tokyo Office - Web Server"
    host: "203.0.113.10"
    ports: [80, 443]
```

### Alternatives Considered

**Option A: `configparser` (INI format)**

Python's built-in `configparser` module reads `.ini` style files.

Rejected because:
- INI format does not natively support lists — representing multiple ports per host requires workarounds (comma-separated strings, repeated keys).
- Less readable than YAML for nested structures.

**Option B: JSON**

Python's built-in `json` module can read `.json` config files.

Rejected because:
- JSON does not support comments — you cannot annotate why a host is included or flag it as temporarily disabled.
- Less readable than YAML for human-edited config files (mandatory quotes on keys, no trailing commas allowed).

**Option C: Python file (`.py` config)**

Define hosts as a Python dict or dataclass directly.

Rejected because:
- Mixing configuration and code couples them unnecessarily.
- Requires a Python developer to edit — YAML can be edited by a non-developer IT admin.
- Executing arbitrary Python for config is a security concern.

**Option D: PyYAML (chosen)**

- Native support for lists, nested structures, and comments
- More readable than JSON for human-managed config
- `PyYAML` is the most widely used Python YAML library
- Adding or removing a host requires only editing the YAML file — no code changes

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| Adds `PyYAML` dependency | No standard library alternative supports YAML |
| YAML indentation errors are hard to spot | Validated on startup with clear error messages |

### Consequences

- Host config is validated on startup; invalid entries are logged and skipped
- `config/hosts.yaml` is safe to commit to git (contains no secrets)
- Schema: each host must have `label` (string), `host` (string), `ports` (list of ints)

---

## ADR-008

### Use `.env` + `python-dotenv` for secrets and environment settings

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

The application needs configurable settings (interval, log level, DB path, thread count, timeouts). Some of these may become sensitive in later phases (SNMP community strings, SMTP passwords). We need a pattern that:
- Keeps secrets out of source code and version control
- Is easy to use in both development and production
- Follows industry-standard practices

### Decision

Use `.env` files loaded via `python-dotenv`.

```python
from dotenv import load_dotenv
import os

load_dotenv()

DB_PATH = os.getenv('MONITOR_DB_PATH', 'data/monitor.db')
INTERVAL = int(os.getenv('MONITOR_INTERVAL_SECONDS', 60))
```

### Alternatives Considered

**Option A: Hardcoded values in source**

Rejected immediately — hardcoded credentials are a critical security anti-pattern. Even non-sensitive config values hardcoded in source make the project harder to deploy in different environments.

**Option B: Command-line arguments (`argparse`)**

Rejected because:
- A long-running daemon with 8+ configuration options is unwieldy to start via CLI flags.
- Not compatible with running as a service (`systemd`, Task Scheduler).
- `.env` is easier to manage and hand off to an ops team.

**Option C: `os.environ` only (no `.env` file)**

Technically correct but cumbersome in development — you'd have to `export` every variable in your shell before running.

**Option D: `.env` + `python-dotenv` (chosen)**

- Industry-standard approach (12-factor app methodology)
- `.env.example` is committed to git as a template
- `.env` is gitignored — secrets never enter version control
- `os.getenv()` with a default value means the app works even without a `.env` file
- Phase 2+ secrets (SMTP password, Slack webhook) fit naturally into the same pattern

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| `.env` file must be manually created per environment | This is the standard pattern; `.env.example` makes it easy |
| Environment variables are strings — type casting needed | Explicit `int()`, `float()` casts are simple and visible |

### Consequences

- `.env` is listed in `.gitignore`
- `.env.example` is committed with all keys and safe placeholder values
- All secrets and settings are loaded once at startup in `src/config/loader.py`

---

## ADR-009

### Use UTC timestamps for all stored records

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

This is a **global** monitoring system. Hosts in Tokyo, London, and Sydney operate in different timezones. Check results stored with local timestamps would be ambiguous and difficult to correlate across regions.

### Decision

All timestamps stored in SQLite use UTC in ISO 8601 format.

```python
from datetime import datetime, timezone

checked_at = datetime.now(timezone.utc).isoformat()
# → '2026-06-11T08:30:00.123456+00:00'
```

### Consequences

- Timestamps are unambiguous regardless of where the monitoring agent runs
- Log output also uses UTC (configured in `loguru` format string)
- Phase 4 dashboard converts UTC to local time in the browser — not in the database
- `datetime.now(timezone.utc)` is used everywhere — `datetime.utcnow()` is explicitly avoided (it returns a naive datetime with no timezone info, which is a common Python footgun)

---

## ADR-010

### Append-only write strategy for SQLite

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

When a probe result is collected, we could either:
1. **Append** a new row every cycle (full history retained)
2. **Upsert** (update if exists, insert if new) to keep only the latest status per host

### Decision

Use append-only inserts. Every probe result is a new row. We never update or delete rows in Phase 1.

### Rationale

- **History is valuable.** Alert logic in Phase 2 needs to look back at recent results (e.g. "was this host DOWN for 3 consecutive cycles?"). An upsert strategy destroys that history.
- **Trend analysis.** Average latency over time, uptime percentages, and incident duration all require historical rows.
- **Simplicity.** `INSERT` is simpler than `INSERT OR REPLACE` or `ON CONFLICT DO UPDATE`.
- **Storage cost is low.** At 60-second intervals with 20 hosts and 2 checks each, we generate ~2,400 rows/hour (~57,600/day). At ~100 bytes per row, that's ~5.5MB/day — trivial for SQLite.

### Consequences

- A data retention policy (auto-purge rows older than N days) is noted as Phase 3 scope
- Queries for "current status" use `MAX(id)` or `MAX(checked_at)` grouped by host and check type

---

## ADR-011

### Separate probe results from host config at the data layer

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

An alternative schema design would store the host list in a `hosts` table in SQLite and join it with a `check_results` table. This is the normalized relational approach.

### Decision

For Phase 1, store all host metadata (label, IP) directly in each `check_results` row (denormalized). Do not create a separate `hosts` table in SQLite.

### Rationale

- **Host config is already in YAML.** The authoritative source of truth for the host list is `config/hosts.yaml`, not the database. Duplicating it in a `hosts` table creates synchronization complexity for no gain in Phase 1.
- **Queries are simpler.** Retrieving all results for a host is a single `WHERE host_ip = ?` — no join needed.
- **Future phases may normalize.** When Phase 2 adds alert rules per host, a `hosts` table becomes useful. That migration is a `CREATE TABLE hosts` + `ALTER TABLE check_results ADD COLUMN host_id` — straightforward when the time comes.

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| Host label stored redundantly in every row | Storage cost is negligible; query simplicity is worth it in Phase 1 |
| Renaming a host in YAML doesn't update historical rows | Historical rows preserve the label at time of check — acceptable behavior |

---

## ADR-012

### Single-machine deployment for Phase 1

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

A production global monitoring system typically uses distributed agents — a lightweight process deployed at each site that reports back to a central collector. This avoids firewall issues and gives accurate local latency measurements.

### Decision

Phase 1 runs entirely on a single machine. The monitoring agent, scheduler, probes, and database all live on one host.

### Rationale

- **Scope control.** Distributed deployment introduces SSH key management, agent deployment, inter-process communication, and network security — all of which are Phase 3 concerns.
- **Portfolio demonstrability.** A single-machine setup runs with `python main.py` — no infrastructure provisioning required to demo the project.
- **Foundation first.** The probe logic, data model, and scheduler built in Phase 1 are reused unchanged in a distributed architecture. The architecture scales out; the code doesn't change.

### Known Limitation

Hosts behind strict firewalls or private NAT may not be reachable from a central monitor. This is documented as a constraint in the PRD and addressed by the agent-based architecture in Phase 3.

### Consequences

- No inter-process communication or message queues in Phase 1
- `README.md` documents the single-machine assumption clearly
- Phase 3 ADR will document the migration to a distributed agent model

---

## Decision Summary

| ADR | Decision | Plain Python? | Package used |
|-----|----------|:---:|---|
| ADR-001 | ICMP probe | ✅ | `subprocess` (stdlib) |
| ADR-002 | TCP port check | ✅ | `socket` (stdlib) |
| ADR-003 | Concurrency | ✅ | `concurrent.futures` (stdlib) |
| ADR-004 | Storage | ✅ | `sqlite3` (stdlib) |
| ADR-005 | Scheduling | 📦 | `APScheduler` |
| ADR-006 | Logging | 📦 | `loguru` |
| ADR-007 | Host config | 📦 | `PyYAML` |
| ADR-008 | Secrets | 📦 | `python-dotenv` |
| ADR-009 | UTC timestamps | ✅ | `datetime` (stdlib) |
| ADR-010 | Append-only writes | ✅ | `sqlite3` (stdlib) |
| ADR-011 | Denormalized schema | ✅ | Design decision |
| ADR-012 | Single-machine | ✅ | Architecture decision |

**Result: 8 plain Python decisions, 4 third-party packages.**  
Every package was chosen because it solves a real problem that stdlib handles poorly.

---

*End of ADR — Phase 1: Core Monitoring Loop*

> **Next document:** Phase 1 implementation. Start with `src/probes/icmp.py` and `src/probes/tcp.py`, then `src/storage/database.py`, then wire together in `src/scheduler.py` and `src/main.py`.