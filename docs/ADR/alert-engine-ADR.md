# ADR — Phase 2: Alert Engine with Threshold Logic
**Project:** Python-Based Global IT Infrastructure Monitor & Automated Alerting System  
**Phase:** 2 of 4  
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
| [ADR-001](#adr-001) | Stateless threshold evaluation via `check_results` queries | Accepted |
| [ADR-002](#adr-002) | Alert severity model with configurable thresholds | Accepted |
| [ADR-003](#adr-003) | Alert persistence with dedicated `alerts` table | Accepted |
| [ADR-004](#adr-004) | Alert lifecycle: escalation with promotion and auto-resolve | Accepted |

---

## ADR-001

### Stateless threshold evaluation via `check_results` queries

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

The alert engine must determine, for each Alert Track (defined as a unique combination of `host_address`, `check_type`, and `port`), whether the most recent Check Results represent enough consecutive failures to warrant an alert.

There are three general approaches to tracking consecutive failure count:

1. Maintain an in-memory counter dict in the scheduler process
2. Maintain a separate state table with counters in SQLite
3. Query the existing `check_results` table each cycle and count consecutive failures from the results

### Decision

Query `check_results` at each cycle. Walk backwards from the most recent row per track, counting consecutive failures until a passing status is found. No separate state — in memory or in tables — is maintained.

```sql
SELECT status FROM check_results
WHERE host_address = ? AND check_type = ? AND port IS ?
ORDER BY checked_at DESC
LIMIT ?
```

The Python wrapper iterates the returned rows in order, counting FAILURE statuses (`DOWN` for ICMP, `CLOSED` for TCP) until it hits a passing status (`UP` or `OPEN`) or runs out of rows. The count is compared against the warning and critical thresholds.

The flow is:

```
run_cycle()
  → run_checks_for_host() × N (ThreadPoolExecutor)
  → save_results()                        # batch-writes current cycle
  → evaluate_alerts(db_path, results, ...) # queries check_results
```

### Alternatives Considered

**Option A: In-memory counter dictionary**

Maintain a `defaultdict(int)` keyed by `(host_address, check_type, port)` that increments on failure and resets to 0 on success.

Rejected because:
- State is entirely in process memory — lost on restart, crash, or any process lifecycle event.
- If the monitor is restarted mid-incident, the consecutive counter resets to 0 and the incident must re-accumulate failures before alerting again.
- In a Phase 3 distributed deployment, in-memory state in one agent is invisible to other agents.

**Option B: Separate `alert_state` table with counters**

A dedicated table storing the current consecutive failure count per track, updated each cycle.

Rejected because:
- Creates a second source of truth that must stay synchronized with `check_results`.
- Every cycle requires an extra write per track (UPDATE or UPSERT), adding write contention to SQLite.
- If `check_results` rows are ever manually cleaned or purged, the state table diverges silently.

**Option C: Query `check_results` (chosen)**

- Stateless — the entire alert history is derived from the immutable append-only `check_results` table.
- Resilient to restart — the same query always produces the same result for the same data.
- No synchronization needed — `check_results` is the single source of truth for both check history and alert state derivation.
- Write profile unchanged — no additional writes per cycle beyond the existing `save_results()` batch.

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| Extra `SELECT` per active track per cycle | At ~20 hosts × ~3 tracks each = ~60 queries per cycle, each scanning a handful of rows. Negligible at our default 60s interval. |
| Cannot detect "missed cycles" as failures | A missed cycle produced no Check Result. In the domain language, "no result" is not a failure — only a result with status DOWN/CLOSED is. |
| Requires historical data to accumulate before alerts fire | Cold start simply has fewer rows than the threshold; no alert fires until enough data accumulates. This is correct behavior — don't alert on empty history. |

### Consequences

- `evaluate_alerts()` queries by row count (`LIMIT = critical_threshold`), not by time window. Row count is the natural unit for "consecutive."
- `evaluate_alerts()` runs after `save_results()` within the same cycle, so the current cycle's results are included in the query.
- Only currently active tracks (those with a result in the current cycle) are evaluated. Hosts removed from `config/hosts.yaml` stop producing results and stop being evaluated — no stale alerts.
- The first cycle after startup may have fewer results than the threshold; no alerts fire until enough consecutive failures accumulate.
- Gaps between results (e.g., monitor was offline) do not break or extend the consecutive count — only Check Result rows with FAILURE status count.

---

## ADR-002

### Alert severity model with configurable thresholds

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

A binary alert state ("alerting" or "not alerting") lacks the expressiveness needed for operational triage. A service that has been unreachable for 3 cycles may warrant attention; one unreachable for 10 cycles may warrant immediate escalation. We need a severity system that communicates urgency and allows operators to prioritise.

### Decision

Two severity levels with configurable consecutive-failure thresholds:

| Severity | Consecutive failures | Default threshold |
|----------|---------------------|-------------------|
| WARNING  | >= N                | 3                 |
| CRITICAL | >= M                | 5                 |

Where `M > N`. When the consecutive failure count reaches N, a WARNING alert fires. If the count continues to M, it escalates to CRITICAL.

Thresholds are configured globally via environment variables:

```
MONITOR_WARNING_THRESHOLD=3
MONITOR_CRITICAL_THRESHOLD=5
```

### Alternatives Considered

**Option A: Single threshold**

One threshold separates "alerting" from "not alerting." No distinction between a brief hiccup and a prolonged outage.

Rejected because:
- All alerts carry the same operational weight — a 3-cycle blip and a 15-cycle outage look identical.
- No natural escalation path for notifications (Phase 3).
- Does not match standard NOC practice, which distinguishes concerning from critical.

**Option B: Three or more severity levels (INFO, WARNING, ERROR, CRITICAL)**

A richer severity ladder matching ITIL incident priority scales.

Rejected for Phase 2 because:
- Three thresholds create a more complex state machine with diminishing practical returns.
- The operational value of "4 consecutive failures = INFO" is unclear — at Phase 2 scale, INFO alerts would be noise.
- Can be extended later if needed (add an `EMERGENCY` level in Phase 3).

**Option C: Two levels with configurable thresholds (chosen)**

- WARNING for "this is trending bad but not yet urgent" (3 failures).
- CRITICAL for "this requires immediate attention" (5 failures).
- Standard pattern used by Prometheus, Nagios, and most monitoring platforms.
- Thresholds exposed as env vars — adjustable without code changes.

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| Global thresholds apply to every track equally | Per-host or per-track customization is reserved for Phase 3. Global defaults cover all Phase 2 use cases. |
| Thresholds are integer consecutive-failure counts, not percentage-based | Consecutive counts are unambiguous and match the "3 strikes" mental model. Percentages over time windows would be harder to reason about at cycle-granularity. |

### Consequences

- Two new environment variables: `MONITOR_WARNING_THRESHOLD` (default 3) and `MONITOR_CRITICAL_THRESHOLD` (default 5).
- `config/hosts.yaml` schema reserves an optional `thresholds` block per host for future per-host overrides, but the block is not implemented in Phase 2.
- The `evaluate_alerts()` function receives the thresholds as parameters from config.
- Thresholds are integers. The critical threshold must be greater than the warning threshold (validated at startup).

---

## ADR-003

### Alert persistence with dedicated `alerts` table

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

When an alert fires, escalates, or resolves, the system needs a record of that event. The record must be:
- Queryable: "Which alerts are open right now?" should be a simple SQL query.
- Auditable: When did an alert fire? When did it resolve? Why was it resolved?
- Durable: Survives restarts and is independent of the Check Results history.

Alternatively, alert state could be derived entirely from `check_results`, with no explicit alert records.

### Decision

Create a dedicated `alerts` table in SQLite alongside the existing `check_results` table.

```sql
CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at    TEXT NOT NULL,
    host_label      TEXT NOT NULL,
    host_address    TEXT NOT NULL,
    check_type      TEXT NOT NULL,
    port            INTEGER,
    severity        TEXT NOT NULL,   -- 'WARNING' or 'CRITICAL'
    resolved_at     TEXT,            -- NULL means open; set when resolved
    resolved_reason TEXT              -- 'RECOVERED' | 'ESCALATED' | NULL
);
```

Key design choices:
- `resolved_at IS NULL` = alert is currently open. This is the simplest query for "what's firing now."
- `resolved_reason` distinguishes natural recovery (`RECOVERED`) from escalation (`ESCALATED`), providing a richer audit trail.
- `host_address` uses the canonical column name (not `host_ip`) — aligning with the Phase 1 glossary cleanup.
- `port` is NULL for ICMP alerts, matching the `check_results` pattern.
- `host_label` is denormalized into the alert row (same trade-off as ADR-011: storage is cheap, queries are simpler).

### Alternatives Considered

**Option A: Derive alert state entirely from `check_results`**

Any consumer (dashboard, notification system) queries `check_results` to count consecutive failures and determine "is there an active alert?"

Rejected because:
- Every consumer re-implements the consecutive-failure counting logic.
- "What was the last alert state at time X?" requires replaying history from `check_results` — expensive and non-obvious.
- No canonical answer to "which alerts are open" — different consumers might use slightly different queries and get different results.
- The `alerts` table IS the canonical alert history, not a cache.

**Option B: Log-based alert record**

Write alert events to a structured log file (JSON lines) and parse it for history.

Rejected because:
- Not directly queryable — any "current alerts" query requires scanning and parsing the log file.
- Log rotation would destroy or archive alert history.
- Introducing a database and then keeping alert records in files is inconsistent.

**Option C: Dedicated `alerts` table (chosen)**

- "Current open alerts" = `SELECT * FROM alerts WHERE resolved_at IS NULL` — one trivial query.
- Full audit trail of every fire, escalation, and resolution.
- Data lives alongside `check_results` — one backup captures both.
- Future notification system (Phase 3) queries open alerts to decide what to send.

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| Alert data duplicates information derivable from `check_results` | The `alerts` table exists for queryability and audit, not storage efficiency. The derivation cost (counting consecutive failures) is what we're avoiding on every read. |
| Additional table to manage in schema | One more `CREATE TABLE IF NOT EXISTS` in `init_database()`. Trivial cost. |
| `host_label` in alert rows can drift if YAML is updated | Same trade-off as `check_results` (ADR-011). Historical alert rows preserve the label at time of alert. Acceptable. |

### Consequences

- `init_database()` in `src/storage/database.py` is updated to create the `alerts` table at startup.
- New query functions are added:
  - `get_open_alerts()` — returns currently unresolved alerts.
  - `get_recent_alerts(limit)` — returns recent alert history.
  - `insert_alert()` — inserts a new alert row.
  - `resolve_alert(alert_id, reason)` — sets `resolved_at` and `resolved_reason`.
- All alert DB functions live in `src/storage/database.py` alongside the existing check result functions.
- The `alerts` table is populated only by the alert engine, not by external consumers.

---

## ADR-004

### Alert lifecycle: escalation with promotion and auto-resolve

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

An alert is not a static record — it transitions through states over time. A typical incident lifecycle looks like:

1. Consecutive failures accumulate (pre-alert)
2. Warning threshold crossed → WARNING fires
3. More failures accumulate
4. Critical threshold crossed → incident becomes more severe
5. Service recovers → alert clears

We need a state machine that faithfully represents this lifecycle.

### Decision

Use an **escalation-with-promotion** model for severity increases and **immediate auto-resolve** for recovery.

#### State transitions

```
[pre-alert] ──(N failures)──▶ [WARNING open]
    │                               │
    │                          (M failures)
    │                               │
    │                               ▼
    │                      [WARNING resolved]
    │                      [CRITICAL open]     ← escalation (promotion)
    │                               │
    │                          (1 passing)
    │                               │
    │                               ▼
    │                      [CRITICAL resolved]  ← auto-resolve
    │
    └──(1 passing)──▶ (no alert created)
```

#### Escalation (promotion)

When consecutive failures cross the critical threshold while a WARNING alert is open:

1. The WARNING row gets `resolved_at = now` and `resolved_reason = 'ESCALATED'`
2. A new CRITICAL row is inserted with `resolved_at = NULL`

This creates an audit trail: you can see when severity increased and why the WARNING was no longer current. At any point, there is at most one open alert per track.

#### Auto-resolve

When the most recent Check Result for a track has a passing status (`UP` or `OPEN`):

1. The consecutive failure counter is implicitly 0 (the query returns 0 consecutive failures)
2. The latest open alert (if any) for that track gets `resolved_at = now` and `resolved_reason = 'RECOVERED'`

No minimum number of passing results is required. One passing result = resolved. This ensures the alert clears promptly when the service is healthy.

#### Defensive handling

If multiple open alerts exist for the same track (should not happen under normal operation), ALL are resolved when a passing result arrives. This self-heals any state inconsistencies.

#### Jumped threshold

If no alert exists yet but the consecutive failure count is already >= the CRITICAL threshold (e.g., the monitor was just started cold and the first 7 results are all failures), only a CRITICAL alert is inserted. No backfilling of WARNING records — the CRITICAL row is the first and only alert.

### Alternatives Considered

**Option A: Severity upgrade in place**

Keep a single alert row and update its `severity` field when the threshold escalates (WARNING → CRITICAL).

Rejected because:
- Destroys audit history — you can no longer see *when* the severity changed, just the current value.
- If the user is reviewing incidents later, there's no record that the service was at WARNING for 2 cycles before escalating.

**Option B: Independent alerts per threshold crossing**

Insert a WARNING alert at 3 failures and a separate CRITICAL alert at 5 failures. Both remain open simultaneously.

Rejected because:
- Two open alerts for the same track is confusing to operators — "Why is this track both WARNING and CRITICAL?"
- Auto-resolve must clear both, creating ambiguity about partial resolution (WARNING resolved but CRITICAL still open).

**Option C: Escalation with promotion (chosen)**

- At most one open alert per track at any time.
- Full audit trail: WARNING row shows when it fired and when/why it was resolved (escaped to CRITICAL).
- CRITICAL row shows when severity escalated and when the incident ultimately recovered.
- Auto-resolve is unambiguous — when a passing result arrives, the sole open alert is resolved.

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| WARNING row is mutated (resolved_at set) on escalation, breaking pure append-only | The mutation is a single field update with a clear reason. The alerts table is append-dominated, not strictly append-only. The check_results table retains its strict append-only contract. |
| Escalation requires two DB operations (UPDATE WARNING, INSERT CRITICAL) | Two operations per escalation event. Escalation events are rare relative to normal cycles. |
| No grace period before auto-resolve (one passing result = resolved) | A single passing result is proof the service is reachable. Requiring multiple passing results delays the "all clear" and conflates recovery with confidence in recovery. |

### Consequences

- The `evaluate_alerts()` function implements the full state machine logic.
- Alert state transitions are logged at appropriate levels:
  - WARNING fires → `logger.warning()`
  - CRITICAL fires → `logger.critical()`
  - Escalation (WARNING → CRITICAL) → `logger.critical()` with escalation message
  - Auto-resolve → `logger.info()`
- The cycle summary in `src/monitor.py` includes alert counts: how many fired, escalated, and resolved this cycle.
- The `alerts` table is append-dominated but not strictly append-only — `UPDATE alerts SET resolved_at = ..., resolved_reason = ...` is used for resolution and escalation. This is an intentional exception to the Phase 1 append-only rule, scoped to the alerts table only.

---

## Decision Summary

| ADR | Decision | Plain Python? | Package used |
|-----|----------|:---:|---|
| ADR-001 | Threshold evaluation | ✅ | `sqlite3` (stdlib) |
| ADR-002 | Severity model | ✅ | Design decision |
| ADR-003 | Alert persistence | ✅ | `sqlite3` (stdlib) |
| ADR-004 | Alert lifecycle | ✅ | Design decision |

**Result: 4 plain Python decisions, 0 third-party packages.**  
The alert engine builds entirely on the existing storage, configuration, and scheduling infrastructure. No new dependencies are introduced.

---

*End of ADR — Phase 2: Alert Engine with Threshold Logic*
