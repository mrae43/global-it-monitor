# Global IT Infrastructure Monitor

A scheduled system that checks the reachability of network hosts and the availability of their TCP ports, persisting all results for later analysis.

## Language

**Check**:
A single ICMP ping or TCP connection attempt against one target.
_Avoid_: Probe

**Check Result**:
The complete persisted record of one Check: host label, address, check type, port, status, latency, and timestamp.
_Avoid_: Result (shorthand for just the status value)

**Check Type**:
The protocol a Check uses. Values: `ICMP` or `TCP`.

**Status**:
The outcome of a Check. ICMP Checks produce `UP` or `DOWN`. TCP Checks produce `OPEN` or `CLOSED`. Not interchangeable between check types.

**Host**:
A config entry with a label, address, and list of ports to check. Not the physical machine — two Hosts can share the same address.
_Avoid_: Target, server, machine

**Address**:
A Host's network location — an IP address or a DNS hostname. Stored as `host_address` (not `host_ip`, since DNS names are valid).
_Avoid_: IP (when the value may not be an IP)

**Port**:
A TCP port number on a Host that a Check connects to. Only applies to TCP Checks; NULL for ICMP.

**Latency**:
The time in milliseconds between sending a Check and receiving a response. Meaning differs by check type (ICMP round-trip vs TCP connection time).

**Cycle**:
One complete execution of the check loop across all Hosts. Can be triggered by the scheduler or run manually.

**Alert**:
A record indicating that an Alert Track has exceeded a severity threshold due to consecutive failures. Persisted in the `alerts` table.
_Avoid_: Notification, incident

**Alert Track**:
The unique combination of `(host_address, check_type, port)` that threshold evaluation targets. Each Alert Track is independent — ICMP and TCP for the same host on the same port are separate tracks.
_Avoid_: Check track (when referring to alert state)

**Severity**:
The urgency level of an Alert. Values: `WARNING` (N consecutive failures), `CRITICAL` (M consecutive failures, where M > N), or `FLAPPING` (oscillating state, terminal — no escalation). Configured globally via env vars.
_Avoid_: Priority, level, urgency

**Consecutive Failure Count**:
The number of most recent Check Results for an Alert Track that are failures, counting backwards from the most recent until a passing result is found. A failure is `DOWN` (ICMP) or `CLOSED` (TCP). Only actual Check Result rows count — gaps do not break or extend the counter.

**Auto-resolve**:
The process by which an open Alert is closed (`resolved_at` set) when the most recent Check Result for that Alert Track has a passing status. No human intervention required.

**Escalation**:
The process by which a WARNING Alert is resolved with `reason = 'ESCALATED'` and a new CRITICAL Alert is inserted, when the Consecutive Failure Count crosses the CRITICAL threshold while a WARNING is already open.

**Flapping**:
A state where an Alert Track has produced 3 or more Alert rows within a 10-minute rolling window, indicating an unstable service. Detected during threshold evaluation; the current open Alert is resolved with `reason = 'FLAPPING'` and a new Alert with severity `FLAPPING` is inserted.
_Avoid_: Oscillating, bouncing, unstable (when referring specifically to the FLAPPING alert state)

**Stabilisation**:
The process by which a FLAPPING Alert is resolved when its Alert Track produces 3 consecutive passing Check Results without any intervening failures. Exits flapping and returns the track to normal threshold evaluation with a clean slate.

## Relationships

- A **Host** has one ICMP **Check** and one TCP **Check** per **Port**
- Each **Check** produces one **Check Result** per **Cycle**
- One **Cycle** covers all **Hosts**, producing one **Check Result** per **Check** per **Host**
- **Status** is a field within a **Check Result** — a Host itself has no status

## Example dialogue

> **Dev:** "Tokyo is DOWN this cycle."
> **Domain expert:** "You mean the ICMP Check Result for the Tokyo Host was DOWN. The TCP Checks on ports 80 and 443 might still be OPEN."
> **Dev:** "Right — the Host doesn't have a status, only its Check Results do."

> **Dev:** "Should I rename `host_ip` to `host_address` in the schema?"
> **Domain expert:** "Yes — the Address can be a DNS name like `db.sg.company.internal`, not just an IP."

## Flagged ambiguities

- "Probe" was used in code (`probes/` directory) and PRD glossary alongside "Check" — resolved: the canonical term is **Check**. The `probes/` directory name remains as an implementation artifact but the domain language is Check.
- "host is DOWN" is shorthand for "the most recent ICMP Check Result for that Host has status DOWN" — a Host itself has no status.
- `host_ip` in the database column and result dicts conflicts with the fact that values can be DNS hostnames — resolved: the canonical domain term is **Address**, and the code should use `host_address`.