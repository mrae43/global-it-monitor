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