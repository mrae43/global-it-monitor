# PRD — Phase 2: Alert Engine with Threshold Logic
**Project:** Python-Based Global IT Infrastructure Monitor & Automated Alerting System  
**Phase:** 2 of 4  
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
10. [Project Structure Changes](#10-project-structure-changes)
11. [Constraints & Assumptions](#11-constraints--assumptions)
12. [Out of Scope (Phase 2)](#12-out-of-scope-phase-2)
13. [Success Metrics](#13-success-metrics)
14. [Risks & Mitigations](#14-risks--mitigations)
15. [Glossary](#15-glossary)

---

## 1. Overview

### 1.1 Summary

Phase 2 delivers the **alert engine**: a threshold evaluation layer that sits on top of the Phase 1 monitoring loop. Every cycle, after check results are written to SQLite, the alert engine queries the stored results, counts consecutive failures per host/check-type/port track, and decides whether to fire, escalate, or resolve alerts.

Phase 2 introduces:
- A severity model with WARNING and CRITICAL levels driven by configurable consecutive-failure thresholds
- A dedicated `alerts` table in SQLite to persist the full alert lifecycle (fire, escalate, resolve)
- An escalation-with-promotion state machine that preserves audit history
- Flap detection that suppresses alert noise from oscillating services, with a terminal FLAPPING severity and stabilisation requirement

No notification dispatch (email, Slack, PagerDuty) is included — alert state changes are logged via loguru and stored in the `alerts` table for Phase 3 consumption.

### 1.2 Target Audience

| Role | Interest |
|------|----------|
| IT Infrastructure Engineer | Wants automated alerting when hosts or services go down, without watching the dashboard |
| IT Manager | Wants a record of incidents: when they started, escalated, and resolved |
| Portfolio Reviewer | Evaluates ability to design a state machine, manage concurrency in SQLite, and write testable threshold logic |

### 1.3 Deliverable Summary

A backward-compatible extension of the Phase 1 project that:
- Evaluates consecutive failures per track after each monitoring cycle
- Fires WARNING and CRITICAL alerts based on configurable thresholds
- Escalates WARNING to CRITICAL with a resolved_at audit trail
- Auto-resolves alerts on the first passing result
- Detects flapping tracks (3+ alert transitions in 10 minutes) and elevates them to FLAPPING severity
- Stabilises FLAPPING tracks after 3 consecutive passing results, returning them to normal evaluation
- Persists every alert event in a dedicated `alerts` table

---

## 2. Goals & Non-Goals

### Goals

- Derive alert state entirely from the existing `check_results` table — no separate state management
- Implement a two-level severity model (WARNING, CRITICAL) with configurable thresholds
- Persist all alert events (fire, escalate, resolve) in a dedicated `alerts` table for queryability and audit
- Implement an escalation-with-promotion state machine: at most one open alert per track, with full history
- Detect flapping services and suppress further alerting until stabilisation is confirmed
- Use plain Python (stdlib) for all threshold, state machine, and flap detection logic
- Add no new third-party dependencies beyond what Phase 1 established

### Non-Goals (covered in later phases)

- No alert notification dispatch (email, Slack, webhook, PagerDuty) — Phase 3
- No per-host threshold overrides — Phase 3
- No HTTP endpoint checks — Phase 3
- No DNS resolution checks — Phase 3
- No web dashboard — Phase 4
- No data retention / auto-purge — Phase 3

---

## 3. Background & Context

### 3.1 Why Phase 2 matters

Phase 1 answers "is the host reachable right now?" — but an operator cannot watch the logs 24/7. Phase 2 answers "when should I be notified?" by defining a repeatable, configurable decision process that turns raw check results into actionable alerts.

### 3.2 Why stateless threshold evaluation

The alert engine queries the existing `check_results` table each cycle, walking backwards from the most recent row per track and counting consecutive failures until a passing status is found. This is stateless — no in-memory counters and no separate state table. The benefits are:

| Concern | Benefit |
|---------|---------|
| Restart resilience | Same query produces same result for same data; no state lost on restart |
| Single source of truth | `check_results` is the canonical record; alert state is derived, not duplicated |
| Write profile unchanged | No additional writes beyond the existing `save_results()` batch |
| Distributed-ready | Any agent can evaluate alerts from the same data |


### 3.3 Domain concepts introduced

| Concept | Definition |
|---------|-----------|
| **Track** | A unique combination of `host_address`, `check_type`, and `port`. Each track is evaluated independently for alerting. |
| **Consecutive failure count** | Number of most recent Check Results in a row with a FAILURE status (DOWN for ICMP, CLOSED for TCP). Determined by querying `check_results` ordered by time descending. |
| **Flapping** | A track that oscillates between UP and DOWN rapidly, producing 3+ alert rows within a rolling 10-minute window. |

---

## 4. User Stories

### US-01 — Consecutive failure threshold alerts
**As an** IT engineer,  
**I want to** receive an alert when a host has been unreachable for a configurable number of consecutive cycles,  
**so that** I am notified of sustained outages, not transient blips.

**Acceptance Criteria:**
- WARNING fires after N consecutive failures (default: 3)
- CRITICAL fires after M consecutive failures (default: 5, where M > N)
- Thresholds are configurable via environment variables
- Startup validation rejects CRITICAL ≤ WARNING

---

### US-02 — Alert escalation
**As an** IT engineer,  
**I want to** see when an alert escalates from WARNING to CRITICAL,  
**so that** I can understand how long a service has been degrading before becoming critical.

**Acceptance Criteria:**
- When failures continue past CRITICAL threshold with a WARNING open, the WARNING is resolved with reason `ESCALATED`
- A new CRITICAL alert row is inserted
- At most one open alert exists per track at any time

---

### US-03 — Auto-resolve on recovery
**As an** IT engineer,  
**I want to** see alerts automatically cleared when the service recovers,  
**so that** I don't have to manually acknowledge resolved incidents.

**Acceptance Criteria:**
- A single passing result (UP or OPEN) auto-resolves the current open alert
- The alert row gets `resolved_at` set and `resolved_reason = 'RECOVERED'`
- If multiple open alerts exist for the same track (defensive), all are resolved

---

### US-04 — Jumped threshold detection
**As an** IT engineer,  
**I want to** see only a CRITICAL alert when a service was already failing for many cycles before monitoring started,  
**so that** I don't see a confusing WARNING→CRITICAL sequence for a single incident.

**Acceptance Criteria:**
- If consecutive failures are already ≥ CRITICAL threshold when no alert exists, only a CRITICAL alert is inserted
- No WARNING row is backfilled

---

### US-05 — Flap detection
**As an** IT engineer,  
**I want to** be notified when a service is flapping (oscillating UP/DOWN rapidly),  
**so that** I can investigate the instability rather than being spammed with individual alerts.

**Acceptance Criteria:**
- 3+ alert rows within a rolling 10-minute window triggers FLAPPING severity
- Current open alert is resolved with reason `FLAPPING`
- A new FLAPPING alert is inserted
- No further WARNING/CRITICAL alerts fire while the track is flapping

---

### US-06 — Flap stabilisation
**As an** IT engineer,  
**I want to** know when a flapping service has stabilised,  
**so that** I can trust that the service is healthy again.

**Acceptance Criteria:**
- 3 consecutive passing results (UP/OPEN) are required to exit FLAPPING
- Any failure resets the consecutive-passing counter to 0
- On stabilisation, the FLAPPING alert is resolved with reason `RECOVERED`
- Track returns to normal threshold evaluation with a clean consecutive-failure counter

---

### US-07 — Alert history query
**As an** IT manager,  
**I want to** query all alerts (current and historical) with their severity, timing, and resolution reason,  
**so that** I can review incident timelines and response effectiveness.

**Acceptance Criteria:**
- Open alerts = `SELECT * FROM alerts WHERE resolved_at IS NULL`
- Full history queryable by track, severity, or time range
- Each alert record shows when it fired, when it resolved, and why

---

## 5. Functional Requirements

### FR-01: Threshold evaluation
- The system MUST query `check_results` each cycle to count consecutive failures per track
- The system MUST compare the consecutive failure count against WARNING and CRITICAL thresholds
- The system MUST support thresholds configurable via environment variables

### FR-02: Alert severity model
- The system MUST support exactly two severity levels: WARNING and CRITICAL
- WARNING threshold MUST be lower than CRITICAL threshold
- The system MUST validate at startup that CRITICAL threshold > WARNING threshold

### FR-03: Alert lifecycle
- The system MUST support escalation (WARNING → CRITICAL) via promotion (resolve + insert)
- The system MUST auto-resolve the current open alert on the first passing result
- The system MUST support jumped threshold (CRITICAL fires directly without WARNING)
- The system MUST maintain at most one open alert per track at any time

### FR-04: Flap detection
- The system MUST detect flapping when a track produces ≥ N alert rows within a rolling M-minute window
- Flap detection MUST run before threshold escalation
- When FLAPPING is detected, the current open alert MUST be resolved with reason `FLAPPING`
- The system MUST insert a new alert row with severity `FLAPPING`
- A FLAPPING track MUST NOT create new WARNING or CRITICAL alerts

### FR-05: Flap stabilisation
- A FLAPPING track MUST exit flapping after N consecutive passing results
- Any failure during stabilisation MUST reset the consecutive-passing counter
- On stabilisation, the FLAPPING alert MUST be resolved with reason `RECOVERED`
- The track MUST return to normal threshold evaluation with a clean counter

### FR-06: Alert persistence
- The system MUST create a dedicated `alerts` table in SQLite
- The `alerts` table MUST store: triggered_at, host_label, host_address, check_type, port, severity, resolved_at, resolved_reason
- The system MUST provide query functions: get_open_alerts, get_recent_alerts, insert_alert, resolve_alert
- A composite index MUST exist on `alerts(host_address, check_type, port, triggered_at DESC)`

### FR-07: Logging
- The system MUST log WARNING fires at `logger.warning()`
- The system MUST log CRITICAL fires at `logger.critical()`
- The system MUST log escalation at `logger.critical()` with escalation message
- The system MUST log auto-resolve at `logger.info()`
- The system MUST log flap detection at `logger.warning()`
- The system MUST log stabilisation at `logger.info()`
- The cycle summary in `src/monitor.py` MUST include alert counts (fired, escalated, resolved)

### FR-08: Evaluation order
- `evaluate_alerts()` MUST process each track in this order:
  1. Check if open FLAPPING alert exists → if yes, check stabilisation only
  2. Count recent alert rows within flap window → if ≥ threshold, insert FLAPPING
  3. Normal threshold evaluation (consecutive failures → auto-resolve / WARNING / CRITICAL / escalation)
  4. Stabilisation check (only if FLAPPING is open)

---

## 6. Technical Specification

### 6.1 High-Level Flow

```
run_cycle()
  → run_checks_for_host() × N (ThreadPoolExecutor)
  → save_results()                        # batch-writes current cycle (Phase 1)
  → evaluate_alerts()                     # queries check_results, manages alerts
       ↓
  for each track in active_tracks:
    │
    ├── [Is there an open FLAPPING alert?]
    │     → Yes: check stabilisation only (step 4)
    │
    ├── [Count recent alert rows in window]
    │     → >= MONITOR_FLAP_TRANSITIONS?
    │       → Resolve current open alert (reason = FLAPPING)
    │       → Insert FLAPPING alert
    │       → Skip to next track
    │
    ├── [Normal threshold evaluation]
    │     Count consecutive failures from check_results:
    │     │
    │     ├── 0 failures → auto-resolve any open alert
    │     ├── >= CRITICAL threshold → escalate or insert CRITICAL
    │     ├── >= WARNING threshold → insert WARNING if none open
    │     └── < WARNING threshold → no action
    │
    └── [Stabilisation check (FLAPPING open)]
          Count consecutive passing results:
          ├── >= 3 → resolve FLAPPING (reason = RECOVERED)
          └── < 3 → stay in FLAPPING
```

### 6.2 Consecutive Failure Query

```python
import sqlite3

def count_consecutive_failures(db_path: str, host_address: str,
                                check_type: str, port: int | None,
                                limit: int) -> int:
    """
    Queries the most recent check_results for a track and counts
    consecutive failures (DOWN or CLOSED) from newest to oldest.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("""
            SELECT status FROM check_results
            WHERE host_ip = ? AND check_type = ? AND port IS ?
            ORDER BY checked_at DESC
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
```

### 6.3 Flap Detection Query

```python
def count_recent_alerts(db_path: str, track_key: tuple,
                        window_minutes: int) -> int:
    """Returns the number of alert rows for a track within the flap window."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("""
            SELECT COUNT(*) FROM alerts
            WHERE host_address = ? AND check_type = ? AND port IS ?
              AND triggered_at >= datetime('now', ? || ' minutes')
        """, (*track_key, f'-{window_minutes}')).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()
```

### 6.4 State Machine Logic (Simplified)

```python
def evaluate_track(db, track, config):
    host, check_type, port = track
    warning_threshold = config['warning_threshold']   # e.g. 3
    critical_threshold = config['critical_threshold']  # e.g. 5
    flap_transitions = config['flap_transitions']       # e.g. 3
    flap_window = config['flap_window_minutes']          # e.g. 10

    # Step 1: Is there an open FLAPPING alert?
    if open_alert_of_severity(db, track, 'FLAPPING'):
        check_stabilisation(db, track, config)
        return

    # Step 2: Flap detection
    alert_count = count_recent_alerts(db, track, flap_window)
    if alert_count >= flap_transitions:
        resolve_open_alert(db, track, reason='FLAPPING')
        insert_alert(db, track, severity='FLAPPING')
        return

    # Step 3: Normal threshold evaluation
    failures = count_consecutive_failures(db, track, critical_threshold)
    current = get_open_alert(db, track)

    if failures == 0:
        if current:
            resolve_alert(db, current['id'], reason='RECOVERED')
    elif failures >= critical_threshold:
        if current and current['severity'] == 'WARNING':
            resolve_alert(db, current['id'], reason='ESCALATED')
            insert_alert(db, track, severity='CRITICAL')
        elif not current:
            insert_alert(db, track, severity='CRITICAL')
    elif failures >= warning_threshold:
        if not current:
            insert_alert(db, track, severity='WARNING')
```

### 6.5 Evaluation Integration in Cycle

```python
def run_cycle():
    """Full monitoring cycle: probes → save → evaluate alerts."""
    hosts = load_hosts()
    all_results = run_checks_concurrently(hosts)
    save_results(DB_PATH, all_results)
    evaluate_alerts(DB_PATH, all_results, config)
```

The `evaluate_alerts()` function receives the current cycle's results to determine which tracks are active. Only tracks with a result in the current cycle are evaluated — hosts removed from `config/hosts.yaml` naturally stop being evaluated.

---

## 7. Package Decision Matrix

> **Principle:** Continue the Phase 1 approach — use plain Python where the standard library is sufficient. No new third-party packages are introduced in Phase 2.

| Concern | Plain Python option | Package chosen | Reason for choice |
|---------|--------------------|----|---|
| Threshold evaluation | `sqlite3` query + loop | ✅ **plain Python** | `SELECT ... WHERE ... ORDER BY ... LIMIT` is sufficient |
| Flap detection | `sqlite3` count query | ✅ **plain Python** | `SELECT COUNT(*) WHERE triggered_at >= ?` is sufficient |
| Alert persistence | `sqlite3` INSERT/UPDATE | ✅ **plain Python** | Standard SQL operations; no ORM needed |
| State machine logic | Plain `if/elif` conditions | ✅ **plain Python** | No framework needed for a 4-state track machine |
| Consecutive counting | Simple `for` loop over rows | ✅ **plain Python** | Single-pass iteration, break on first passing status |

### Package install summary

```
# No new packages. Phase 1 packages remain:
# apscheduler loguru python-dotenv pyyaml
```

All Phase 2 logic uses the Python standard library exclusively (primarily `sqlite3`).

---

## 8. Data Design

### 8.1 New: `alerts` table

```sql
CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at    TEXT NOT NULL,          -- UTC ISO-8601
    host_label      TEXT NOT NULL,          -- Denormalized from config
    host_address    TEXT NOT NULL,          -- host_ip from check_results
    check_type      TEXT NOT NULL,          -- 'ICMP' | 'TCP'
    port            INTEGER,               -- NULL for ICMP
    severity        TEXT NOT NULL,          -- 'WARNING' | 'CRITICAL' | 'FLAPPING'
    resolved_at     TEXT,                   -- NULL means open
    resolved_reason TEXT                    -- 'RECOVERED' | 'ESCALATED' | 'FLAPPING' | NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_track_time
    ON alerts(host_address, check_type, port, triggered_at DESC);
```

### 8.2 New: Composite index for threshold queries

```sql
CREATE INDEX IF NOT EXISTS idx_check_results_track_time
    ON check_results(host_ip, check_type, port, checked_at DESC);
```

### 8.3 Example alert rows

| triggered_at | host_label | host_address | check_type | port | severity | resolved_at | resolved_reason |
|---|---|---|---|---|---|---|---|
| 2026-06-11T08:30:00Z | Tokyo Office | 203.0.113.10 | ICMP | NULL | WARNING | 2026-06-11T08:32:00Z | ESCALATED |
| 2026-06-11T08:32:00Z | Tokyo Office | 203.0.113.10 | ICMP | NULL | CRITICAL | 2026-06-11T08:33:00Z | RECOVERED |
| 2026-06-11T08:35:00Z | London Office | 198.51.100.5 | TCP | 22 | WARNING | 2026-06-11T08:36:00Z | RECOVERED |
| 2026-06-11T08:40:00Z | Singapore DB | 10.0.1.50 | TCP | 3306 | WARNING | 2026-06-11T08:42:00Z | FLAPPING |
| 2026-06-11T08:42:00Z | Singapore DB | 10.0.1.50 | TCP | 3306 | FLAPPING | 2026-06-11T08:50:00Z | RECOVERED |

### 8.4 Useful queries

```sql
-- Currently open alerts
SELECT * FROM alerts WHERE resolved_at IS NULL;

-- Open alerts by severity
SELECT * FROM alerts WHERE resolved_at IS NULL ORDER BY severity DESC;

-- Alert history for a specific host
SELECT * FROM alerts WHERE host_address = '203.0.113.10' ORDER BY triggered_at DESC;

-- Flapping tracks
SELECT host_address, check_type, port, COUNT(*) AS alert_count
FROM alerts
WHERE triggered_at >= datetime('now', '-1 hour')
GROUP BY host_address, check_type, port
HAVING COUNT(*) >= 3;

-- Unresolved flapping alerts
SELECT * FROM alerts WHERE severity = 'FLAPPING' AND resolved_at IS NULL;

-- Recent escalations
SELECT * FROM alerts WHERE resolved_reason = 'ESCALATED' ORDER BY triggered_at DESC LIMIT 20;
```

---

## 9. Configuration Design

### 9.1 New environment variables

```dotenv
# .env (added to existing Phase 1 variables)

# Alert thresholds
MONITOR_WARNING_THRESHOLD=3
MONITOR_CRITICAL_THRESHOLD=5

# Flap detection
MONITOR_FLAP_TRANSITIONS=3
MONITOR_FLAP_WINDOW_MINUTES=10
MONITOR_STABILISATION_THRESHOLD=3
```

Full `.env.example`:

```dotenv
# .env.example — copy to .env and fill in
MONITOR_DB_PATH=data/monitor.db
MONITOR_LOG_LEVEL=INFO
MONITOR_INTERVAL_SECONDS=60
MONITOR_MAX_WORKERS=20
MONITOR_PROBE_TIMEOUT=3

MONITOR_WARNING_THRESHOLD=3
MONITOR_CRITICAL_THRESHOLD=5
MONITOR_FLAP_TRANSITIONS=3
MONITOR_FLAP_WINDOW_MINUTES=10
MONITOR_STABILISATION_THRESHOLD=3
```

### 9.2 Startup validation

The system MUST validate at startup:
- `CRITICAL_THRESHOLD > WARNING_THRESHOLD` (both positive integers)
- `FLAP_TRANSITIONS >= 2` (flap detection is meaningful)
- `FLAP_WINDOW_MINUTES > 0`
- `STABILISATION_THRESHOLD >= 1`

---

## 10. Project Structure Changes

Phase 2 adds/modifies these files within the existing Phase 1 structure:

```
src/
  monitor.py               # MODIFIED — adds evaluate_alerts() call after save_results()
  storage/
    database.py             # MODIFIED — adds alerts table creation, alert CRUD functions
  config/
    loader.py               # MODIFIED — loads new env vars, validates thresholds
```

No new source files, no new directories, no new dependencies. The alert engine lives inline:
- `evaluate_alerts()` in `src/monitor.py` (threshold logic, state machine, flap detection)
- Alert DB functions in `src/storage/database.py` (`get_open_alerts()`, `insert_alert()`, `resolve_alert()`)

---

## 11. Constraints & Assumptions

| Constraint | Detail |
|---|---|
| Alert state is derived from `check_results`, not maintained separately | Stateless evaluation means no in-memory or table-based counters; restart-safe by design |
| `alerts` table is append-dominated but NOT strictly append-only | `UPDATE ... SET resolved_at = ...` is used for resolution and escalation. This is the only exception to Phase 1's strict append-only rule, scoped to the `alerts` table. |
| `check_results` retains its strict append-only contract | No UPDATE or DELETE on check results in any phase |
| Global thresholds apply equally to all tracks | Per-host overrides are deferred to Phase 3 |
| Flap detection is evaluated before threshold escalation | This short-circuits normal alerting for flapping tracks |
| "No result" is not a failure | Missing cycles (monitor offline, config removal) do not break the consecutive count |
| Cold start requires data accumulation | First cycle after startup may have fewer results than the threshold; no alerts fire until enough data accumulates |

---

## 12. Out of Scope (Phase 2)

The following are explicitly deferred to later phases:

| Feature | Phase | Rationale |
|---------|-------|-----------|
| Alert notification dispatch (Slack, email, webhook, PagerDuty) | Phase 3 | Phase 2 logs changes via loguru; `alerts` table is the integration point |
| Per-host alert threshold overrides | Phase 3 | Global thresholds cover Phase 2; per-host overrides add YAML schema + loader changes |
| HTTP endpoint checks (status codes, response time) | Phase 3 | Phase 2 focuses on TCP reachability |
| DNS resolution checks | Phase 3 | DNS is a distinct domain from host reachability |
| SNMP checks | Phase 3+ | Targets network infrastructure (switches, routers) |
| Multi-level severity beyond WARNING, CRITICAL, FLAPPING | Phase 3+ | Three levels cover the operational spectrum |
| Web dashboard | Phase 4 | Dashboard reads from `check_results` and `alerts` tables |
| Data retention / auto-purge | Phase 3 | Phase 1 and 2 write unbounded history |
| Alert suppression rules beyond flap detection | Phase 3+ | Maintenance windows, silence rules, scheduled downtime |

---

## 13. Success Metrics

Phase 2 is considered **complete** when all of the following are true:

| # | Metric | Pass condition |
|---|--------|----------------|
| 1 | WARNING fires correctly | 3 consecutive failures produce a WARNING alert row |
| 2 | CRITICAL fires correctly | 5 consecutive failures produce a CRITICAL alert (or escalate from WARNING) |
| 3 | Escalation preserves history | WARNING row has resolved_at + ESCALATED reason when CRITICAL replaces it |
| 4 | Auto-resolve works | 1 passing result resolves the current open alert with RECOVERED reason |
| 5 | Jumped threshold | 7 consecutive failures with no prior alert produce only a CRITICAL row (no WARNING) |
| 6 | Flap detection | 3 alert rows within 10 minutes produce a FLAPPING row; no further alerts fire |
| 7 | Stabilisation | 3 consecutive passing results resolve FLAPPING; a failure resets the counter |
| 8 | Open alerts query | `SELECT * FROM alerts WHERE resolved_at IS NULL` returns only unresolved rows |
| 9 | No new dependencies | `pip freeze` shows no new packages beyond Phase 1 |

---

## 14. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SQLite write contention from evaluate_alerts() running after save_results() | Low | Medium | evaluate_alerts() is a single-threaded query-only pass. No writes to check_results, only reads + occasional alert writes. |
| Consecutive failure count resets on monitor restart | Medium | Low | Stateless design means no counter to lose. After restart, the next cycle queries check_results and gets the correct count. |
| FLAPPING track never stabilises (endless oscillation) | Medium | Low | Stabilisation check runs every cycle; 3 consecutive passes will always exit FLAPPING. An endlessly flapping track stays in FLAPPING, which is correct — the service is genuinely unstable. |
| `host_address` column rename from `host_ip` in alerts table | Medium | Low | The `alerts` table is new in Phase 2, so there is no migration. The column uses the canonical name `host_address` going forward. |
| Large check_results table slows threshold queries | Low (Phase 2 scale) | Medium | The composite index `idx_check_results_track_time` ensures the query scans only relevant rows. At 1000+ hosts, index performance should be validated. |
| Cold-start alerting gap | Low | Low | No alerts fire until enough data accumulates. This is correct behavior — don't alert on empty history. Documented and expected. |

---

## 15. Glossary

| Term | Definition |
|------|-----------|
| **Track** | A unique combination of `host_address`, `check_type`, and `port`. Each track is evaluated independently. |
| **Consecutive failures** | The count of most recent Check Results with FAILURE status (DOWN / CLOSED) in a row, from newest to oldest. |
| **WARNING** | A severity level indicating a configurable number of consecutive failures (default: 3) that warrants attention but is not yet critical. |
| **CRITICAL** | A severity level indicating a configurable number of consecutive failures (default: 5) that requires immediate intervention. |
| **FLAPPING** | A terminal severity indicating a track has oscillated between UP and DOWN ≥ N times within a rolling M-minute window. Suppresses further alerting until stabilisation. |
| **Escalation** | The transition of a track from WARNING to CRITICAL as consecutive failures continue past the CRITICAL threshold. Implemented via promotion: WARNING is resolved (reason: ESCALATED), CRITICAL is inserted. |
| **Auto-resolve** | Automatic resolution of the current open alert when the most recent Check Result returns a passing status (UP or OPEN). |
| **Stabilisation** | The process of exiting FLAPPING state after N consecutive passing results (default: 3). Stricter than auto-resolve's 1-passing-result requirement. |
| **Jumped threshold** | A scenario where consecutive failures are already ≥ CRITICAL threshold when no alert exists, causing CRITICAL to fire directly without a WARNING phase. |

---

*End of PRD — Phase 2: Alert Engine with Threshold Logic*

> **Next document:** Phase 3 PRD will cover Notification Dispatch (email, Slack, PagerDuty integration) and advanced check types (HTTP, DNS).
