# ADR — Phase 2: Alert Engine with Threshold Logic
**Project:** Python-Based Global IT Infrastructure Monitor & Automated Alerting System  
**Phase:** 2 of 4  
**Status:** Accepted  
**Author:** *[Your Name]*  
**Created:** 2026-06-11  
**Last Updated:** 2026-06-11 (ADR-005 added)

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
| [ADR-005](#adr-005) | Flap detection with FLAPPING severity and stabilisation | Accepted |

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
- At scale (1000+ hosts), querying consecutive failures per track across a growing `check_results` table becomes expensive without indexing. A composite index is added to support the ADR-001 query pattern:

```sql
CREATE INDEX IF NOT EXISTS idx_check_results_track_time
  ON check_results(host_address, check_type, port, checked_at DESC);
```

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
    severity        TEXT NOT NULL,   -- 'WARNING' | 'CRITICAL' | 'FLAPPING'
    resolved_at     TEXT,            -- NULL means open; set when resolved
    resolved_reason TEXT              -- 'RECOVERED' | 'ESCALATED' | 'FLAPPING' | NULL
);
```

Key design choices:
- `resolved_at IS NULL` = alert is currently open. This is the simplest query for "what's firing now."
- `resolved_reason` distinguishes natural recovery (`RECOVERED`) from escalation (`ESCALATED`) and flap detection (`FLAPPING`), providing a richer audit trail.
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
[pre-alert] ──(N failures)──▶ [WARNING open] ──╮
    │                               │            │
    │                          (M failures)     │
    │                               │        (3+ alert rows
    │                               ▼          in 10 min)
    │                      [WARNING resolved]    │
    │                      [CRITICAL open]  ←╯   │
    │                               │            │
    │                    ┌────────────────────────╯
    │                    │         │
    │               (3+ alert     (1 passing)
    │               rows in        │
    │               10 min)        ▼
    │                    │  [CRITICAL resolved]  ← auto-resolve
    │                    │         │
    │                    │    (3+ alert
    │                    │    rows in
    │                    │    10 min)
    │                    ▼         ▼
    │          [WARNING resolved]  │
    │          ┌───────────────────╯
    │          ▼
    │    [FLAPPING open]   ← flap detection (terminal)
    │          │
    │    (3 consecutive
    │     passing results)
    │          │
    │          ▼
    │    [FLAPPING resolved]  ← stabilisation
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

#### Flap detection

A track is considered **flapping** when it has produced 3 or more alert rows (counted by `triggered_at`) within a rolling 10-minute window. Flap detection is evaluated before threshold escalation — it short-circuits the normal alert lifecycle.

When flapping is detected for a track with an open alert:

1. The current open alert (WARNING or CRITICAL) receives `resolved_at = now` and `resolved_reason = 'FLAPPING'`
2. A new alert row is inserted with `severity = 'FLAPPING'` and `resolved_at = NULL`

FLAPPING is a **terminal severity** — no escalation occurs while a track is in FLAPPING state. The purpose is to suppress alert noise from oscillating services. All new Check Results for a flapping track are evaluated only against the stabilisation condition.

#### Stabilisation

A flapping track exits FLAPPING state when it produces **3 consecutive passing Check Results** (UP for ICMP, OPEN for TCP). This is intentionally stricter than the normal auto-resolve threshold (1 passing result), requiring sustained recovery before clearing the FLAPPING alert.

When stabilisation is met:

1. The FLAPPING alert row receives `resolved_at = now` and `resolved_reason = 'RECOVERED'`
2. The track returns to normal threshold evaluation with a clean slate — the consecutive failure counter starts from 0

If a failure arrives before stabilisation is reached, the consecutive-passing counter resets to 0 and the track remains in FLAPPING.

#### State transition examples

The following examples walk through the alert lifecycle cycle-by-cycle for a track with `WARNING_THRESHOLD = 3` and `CRITICAL_THRESHOLD = 5`.

**Scenario A: Normal threshold escalation and auto-resolve**

| Cycle | Check Result | Alert event |
|-------|-------------|-------------|
| 1 | DOWN | consecutive = 1, no alert |
| 2 | DOWN | consecutive = 2, no alert |
| 3 | DOWN | consecutive = 3, **WARNING fires** |
| 4 | DOWN | consecutive = 4, WARNING still open |
| 5 | DOWN | consecutive = 5, **WARNING escalated → CRITICAL fires** |
| 6 | DOWN | consecutive = 6, CRITICAL still open |
| 7 | UP | consecutive fail = 0, **CRITICAL resolved** (reason = RECOVERED) |

**Scenario B: Jumped threshold (cold start)**

| Cycle | Check Result | Alert event |
|-------|-------------|-------------|
| 1 | DOWN | consecutive = 1, no alert |
| 2 | DOWN | consecutive = 2, no alert |
| 3 | DOWN | consecutive = 3, no alert (below CRITICAL, but no WARNING shown — jumped) |
| 4 | DOWN | consecutive = 4, no alert |
| 5 | DOWN | consecutive = 5, **CRITICAL fires directly** (no WARNING row) |

No WARNING is inserted because the consecutive count jumped straight to the CRITICAL threshold. This is the correct behavior: the operator sees one alert (CRITICAL) rather than two (WARNING → CRITICAL) for the same incident.

**Scenario C: Flap detection and stabilisation**

| Cycle | Check Result | Alert event |
|-------|-------------|-------------|
| 1 | DOWN | consecutive = 1, no alert |
| 2 | DOWN | consecutive = 2, no alert |
| 3 | DOWN | consecutive = 3, **WARNING fires** (alert row 1) |
| 4 | UP | consecutive fail = 0, **WARNING resolved** (reason = RECOVERED) |
| 5 | DOWN | consecutive = 1, no alert |
| 6 | DOWN | consecutive = 2, no alert |
| 7 | DOWN | consecutive = 3, **WARNING fires** (alert row 2) |
| 8 | UP | consecutive fail = 0, **WARNING resolved** (reason = RECOVERED) |
| 9 | DOWN | consecutive = 1, no alert |
| 10 | DOWN | consecutive = 2, no alert |
| 11 | DOWN | consecutive = 3 → WARNING fires (alert row 3); flap detection fires → **WARNING resolved** (reason = FLAPPING), **FLAPPING inserted** |
| 12 | UP | consecutive pass = 1, FLAPPING still open |
| 13 | DOWN | consecutive pass resets to 0, FLAPPING still open |
| 14 | UP | consecutive pass = 1, FLAPPING still open |
| 15 | UP | consecutive pass = 2, FLAPPING still open |
| 16 | UP | consecutive pass = 3, **FLAPPING resolved** (reason = RECOVERED), track returns to normal evaluation |

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
| FLAPPING stabilisation requires 3 consecutive passing results (asymmetric with auto-resolve's 1) | Flapping services have demonstrated instability — requiring more evidence before trusting recovery prevents toggling. This is an intentional asymmetry documented in ADR-005. |

### Consequences

- The `evaluate_alerts()` function implements the full state machine logic.
- Alert state transitions are logged at appropriate levels:
  - WARNING fires → `logger.warning()`
  - CRITICAL fires → `logger.critical()`
  - Escalation (WARNING → CRITICAL) → `logger.critical()` with escalation message
  - Auto-resolve → `logger.info()`
  - Flap detected → `logger.warning()` with count and severity
  - FLAPPING fired → `logger.warning()`
  - Stabilisation reached → `logger.info()`
- The cycle summary in `src/monitor.py` includes alert counts: how many fired, escalated, and resolved this cycle.
- The `alerts` table is append-dominated but not strictly append-only — `UPDATE alerts SET resolved_at = ..., resolved_reason = ...` is used for resolution and escalation. This is an intentional exception to the Phase 1 append-only rule, scoped to the alerts table only.

---

## ADR-005

### Flap detection with FLAPPING severity and stabilisation

**Date:** 2026-06-11  
**Status:** Accepted

---

### Context

When a service oscillates between UP and DOWN rapidly (e.g., every 2-3 cycles), the threshold engine fires and auto-resolves WARNING or CRITICAL alerts multiple times in quick succession. Without flap detection, this creates alert noise — operators receive a stream of "DOWN → alert → UP → resolved → DOWN → alert" messages without any indication that the underlying service is unstable.

Flap detection addresses the question: **"At what point do we stop treating each UP/DOWN transition as a separate incident and start treating it as a single unstable event?"**

### Decision

Add a flap detection layer to `evaluate_alerts()` that runs before threshold escalation. When a track has produced 3 or more alert rows within a rolling 10-minute window, the track enters **FLAPPING** severity and no further alerting occurs until stabilisation is confirmed.

#### Detection query

Flap detection queries the `alerts` table directly for the current track:

```sql
SELECT COUNT(*) FROM alerts
WHERE host_address = ? AND check_type = ? AND port IS ?
  AND triggered_at >= datetime('now', '-10 minutes');
```

If the count is >= `MONITOR_FLAP_TRANSITIONS` (default: 3), the track is flapping.

#### Evaluation order

`evaluate_alerts()` processes each track in the following order:

```
for each track:
  1. Is there an open FLAPPING alert for this track?
     → Yes: check stabilisation (step 4). No threshold evaluation.
  2. Count recent alert rows (triggered_at within window).
     → >= 3 in last 10 minutes? Resolve current open alert.
       Insert new FLAPPING row. Skip threshold evaluation.
  3. Normal threshold evaluation (consecutive failures →
     auto-resolve, WARNING, CRITICAL, or escalation).
  4. Stabilisation check (only reached if FLAPPING open):
     Count consecutive passing Check Results.
     → >= 3? Resolve FLAPPING (reason = RECOVERED).
     → < 3? Track remains in FLAPPING.
```

When a track enters FLAPPING, the current open alert (WARNING or CRITICAL) is resolved with `resolved_reason = 'FLAPPING'` and a new alert row is inserted with `severity = 'FLAPPING'`. The existing escalation-with-promotion pattern is preserved — WARNING and CRITICAL rows are closed before FLAPPING replaces them.

#### Stabilisation

A FLAPPING alert exits when the track produces 3 consecutive passing Check Results. This is intentionally stricter than the standard auto-resolve (1 passing result) because a flapping service has demonstrated instability. The consecutive-passing counter resets to 0 if any failure arrives before stabilisation is reached.

Once stabilised, the track returns to normal threshold evaluation with a clean slate — the consecutive failure counter starts from 0 and follows the standard WARNING/CRITICAL logic.

#### Configuration

Three new environment variables follow the existing pattern:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MONITOR_FLAP_TRANSITIONS` | 3 | Number of alert rows within the window to trigger FLAPPING |
| `MONITOR_FLAP_WINDOW_MINUTES` | 10 | Rolling time window for flap detection (in minutes) |
| `MONITOR_STABILISATION_THRESHOLD` | 3 | Consecutive passing results required to exit FLAPPING |

All defaults are validated at startup alongside existing threshold env vars.

### Alternatives Considered

**Option A: Grace period before auto-resolve**

Instead of a separate flapping state, require N consecutive passing results before resolving any alert. A service needs 2-3 consecutive passing results to auto-resolve.

Rejected because:
- Delays resolution for all tracks, not just oscillating ones — a stable recovery waits longer than necessary.
- Does not reduce noise from repeated fire/resolve cycles; it only delays the "all clear" message.
- An operator sees the same number of alerts, just spaced further apart.

**Option B: Suppress notifications only**

Alerts fire and resolve normally in the `alerts` table, but a notification dispatch layer (Phase 3) suppresses sending messages for tracks that are flapping.

Rejected because:
- Pushes the problem to Phase 3, requiring the notification layer to implement its own flap detection.
- The `alerts` table records noise that consumers must filter — "was this alert meaningful or part of a flap?"
- The `alerts` table is the source of truth; it should reflect the operational reality, not require consumers to re-derive it.

**Option C: FLAPPING severity (chosen)**

- The `alerts` table cleanly represents the track's real state: "this service is unstable, not WARNING or CRITICAL."
- Consumers (dashboard, future notification system) can trivially filter or highlight FLAPPING alerts.
- The escalation-with-promotion pattern continues through the new state — no new database or state management infrastructure.
- Stabilisation provides a clear, queryable exit condition.

### Trade-offs Accepted

| Trade-off | Accepted because |
|-----------|-----------------|
| Three more environment variables to manage | Follows the existing pattern; sensible defaults mean no operator action required. |
| FLAPPING stabilisation requires 3 consecutive passing results (asymmetric with auto-resolve's 1) | Intentional: a flapping service needs more proof of stability. The asymmetry is documented in both ADR-004 and ADR-005. |
| A track in FLAPPING ignores consecutive failure count — failures still accumulate but no new alerts fire | This is the goal of flap detection: suppress noise. Once flapping is detected, further failures add no new information. |
| Stabilisation check adds one extra query per track per cycle | Only queried for tracks currently in FLAPPING state. At expected scale (< 5% of tracks flapping), negligible overhead. |

### Consequences

- `evaluate_alerts()` is restructured to run flap detection before threshold evaluation.
- Three new environment variables in `.env.example` and `config/loader.py`.
- The `alerts` table gains an index to support the flap detection query:

```sql
CREATE INDEX IF NOT EXISTS idx_alerts_track_time
  ON alerts(host_address, check_type, port, triggered_at DESC);
```

- Flap detection logging:
  - Flap detected → `logger.warning("Track {track} has flapped {count} times in {window} minutes")`
  - FLAPPING alert inserted → `logger.warning("Track {track} entered FLAPPING")`
  - Stabilisation reached → `logger.info("Track {track} stabilised after {count} consecutive passing results")`
- The cycle summary in `src/monitor.py` includes flap counts: how many tracks entered FLAPPING and how many stabilised this cycle.
- If a track is already in FLAPPING when `evaluate_alerts()` runs, only stabilisation is checked — no new WARNING/CRITICAL alert is created.

---

## Decision Summary

| ADR | Decision | Plain Python? | Package used |
|-----|----------|:---:|---|
| ADR-001 | Threshold evaluation | ✅ | `sqlite3` (stdlib) |
| ADR-002 | Severity model | ✅ | Design decision |
| ADR-003 | Alert persistence | ✅ | `sqlite3` (stdlib) |
| ADR-004 | Alert lifecycle | ✅ | Design decision |
| ADR-005 | Flap detection and stabilisation | ✅ | `sqlite3` (stdlib) |

**Result: 5 plain Python decisions, 0 third-party packages.**  
The alert engine builds entirely on the existing storage, configuration, and scheduling infrastructure. No new dependencies are introduced.

---

## Out of Scope (Phase 2)

The following items are explicitly deferred to later phases. Documenting them here prevents ambiguity about what Phase 2 delivers vs what a reader might expect from an "Automated Alerting System."

| Item | Phase | Rationale |
|------|-------|-----------|
| Per-host alert threshold overrides | Phase 3 | Global thresholds cover Phase 2 use cases. Per-host overrides add YAML schema+loader changes. |
| Alert notification dispatch (Slack, email, webhook, PagerDuty) | Phase 3 | Phase 2 logs alert state changes via loguru. The `alerts` table is the integration point for Phase 3 dispatch. |
| Multi-level severity beyond WARNING, CRITICAL, FLAPPING | Phase 3+ | Three levels cover the operational spectrum. Adding more (INFO, EMERGENCY) shows diminishing returns at this scale. |
| Data retention / auto-purge of `check_results` and `alerts` | Phase 3 | Phase 1 and 2 write unbounded history. Auto-purge requires a background job and retention policy configuration. |
| Web dashboard (Phase 4) | Phase 4 | The dashboard reads from `check_results` and `alerts` via SQLite — the schema is the API contract. |
| HTTP endpoint checks (status codes, response time) | Phase 3 | Phase 2 focuses on TCP reachability. HTTP application-layer checks are a separate check type. |
| DNS resolution checks | Phase 3 | Verifying DNS resolution is a distinct domain concern from host reachability. |
| SNMP checks | Phase 3+ | SNMP monitoring targets network infrastructure (switches, routers) — a different class of hosts than Phase 1 targets. |
| Alert suppression rules beyond flap detection | Phase 3+ | Maintenance windows, silence rules, and scheduled downtime are Phase 3+ features. |

---

## Next Steps

1. Implement `evaluate_alerts()` with the state machine in `src/monitor.py`
2. Add `alerts` table creation to `init_database()` in `src/storage/database.py`
3. Add alert query functions (get_open_alerts, insert_alert, resolve_alert) to `src/storage/database.py`
4. Add flap detection query and stabilisation logic to `evaluate_alerts()`
5. Register environment variables for all thresholds (including flap parameters)
6. Write unit tests for:
   - Threshold escalation (WARNING → CRITICAL)
   - Jumped threshold (cold start)
   - Flap detection (3 alert rows within window)
   - Stabilisation (3 consecutive passing results)
   - Auto-resolve (1 passing result)

---

*End of ADR — Phase 2: Alert Engine with Threshold Logic*
