from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from loguru import logger

from probes.icmp import ping
from probes.tcp import check_port
from storage.database import (
    save_results,
    count_consecutive_failures,
    count_consecutive_passes,
    count_recent_alerts,
    get_open_alert_for_track,
    get_open_flapping_alert,
    insert_alert,
    resolve_alert,
    resolve_all_open_alerts_for_track,
)


def run_checks_for_host(host_config: dict[str, Any], probe_timeout: int = 3) -> list[dict[str, Any]]:
    """Run ICMP ping and TCP port checks for a single host.

    Args:
        host_config: Host configuration dict with keys 'label', 'host', 'ports'.
        probe_timeout: Timeout in seconds per probe.

    Returns:
        List of result dicts, one for ICMP and one per TCP port.
    """
    results = []

    # ICMP check
    ping_result = ping(host_config['host'], timeout=probe_timeout)
    logger.info(
        f"ICMP {host_config['label']} ({host_config['host']}): "
        f"{ping_result['status']}"
        + (f" ({ping_result['latency_ms']}ms)" if ping_result['latency_ms'] else "")
    )
    results.append({
        'host_label': host_config['label'],
        'host_address': host_config['host'],
        'check_type': 'ICMP',
        'status': ping_result['status'],
        'latency_ms': ping_result['latency_ms']
    })

    # TCP checks (one per port)
    for port in host_config.get('ports', []):
        tcp_result = check_port(host_config['host'], port, timeout=probe_timeout)
        logger.info(
            f"TCP {host_config['label']} ({host_config['host']}:{port}): "
            f"{tcp_result['status']}"
            + (f" ({tcp_result['latency_ms']}ms)" if tcp_result['latency_ms'] else "")
        )
        results.append({
            'host_label': host_config['label'],
            'host_address': host_config['host'],
            'check_type': 'TCP',
            'port': port,
            'status': tcp_result['status'],
            'latency_ms': tcp_result['latency_ms']
        })

    return results


def evaluate_track(db_path: str, result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Evaluate alerting for a single track based on the latest check result.

    Args:
        db_path: Path to the SQLite database file.
        result: The latest check result dict for this track.
        config: Alert configuration dict.

    Returns:
        Dict summarizing actions taken (fires, escalations, resolutions, flaps, stabilisations).
    """
    host_address = result['host_address']
    host_label = result['host_label']
    check_type = result['check_type']
    port = result.get('port')
    current_status = result['status']

    warning_threshold = config['warning_threshold']
    critical_threshold = config['critical_threshold']
    flap_transitions = config['flap_transitions']
    flap_window = config['flap_window_minutes']
    stabilisation_threshold = config['stabilisation_threshold']

    actions = {
        'fired': [],
        'escalated': 0,
        'resolved': 0,
        'flapped': 0,
        'stabilised': 0,
    }

    # Step 1: Is there an open FLAPPING alert?
    flapping_alert = get_open_flapping_alert(db_path, host_address, check_type, port)
    if flapping_alert:
        # Check stabilisation
        passes = count_consecutive_passes(db_path, host_address, check_type, port, stabilisation_threshold)
        if passes >= stabilisation_threshold:
            resolve_alert(db_path, flapping_alert['id'], 'RECOVERED')
            logger.info(f"Track {host_label} ({host_address}:{port or check_type}) stabilised after {passes} consecutive passing results")
            actions['stabilised'] += 1
        else:
            # Any failure resets the consecutive passing counter implicitly
            if current_status not in ('UP', 'OPEN'):
                logger.info(f"Track {host_label} ({host_address}:{port or check_type}) remains FLAPPING")
        return actions

    # Step 2: Flap detection
    recent_alert_count = count_recent_alerts(db_path, host_address, check_type, port, flap_window)
    if recent_alert_count >= flap_transitions:
        # Resolve current open alert
        resolved_count = resolve_all_open_alerts_for_track(db_path, host_address, check_type, port, 'FLAPPING')
        if resolved_count:
            logger.warning(f"Track {host_label} ({host_address}:{port or check_type}) has flapped {recent_alert_count} times in {flap_window} minutes — resolving open alert")
        else:
            logger.warning(f"Track {host_label} ({host_address}:{port or check_type}) has flapped {recent_alert_count} times in {flap_window} minutes")
        # Insert FLAPPING alert
        insert_alert(db_path, host_label, host_address, check_type, port, 'FLAPPING')
        logger.warning(f"Track {host_label} ({host_address}:{port or check_type}) entered FLAPPING")
        actions['flapped'] += 1
        return actions

    # Step 3: Normal threshold evaluation
    failures = count_consecutive_failures(db_path, host_address, check_type, port, critical_threshold)
    current_alert = get_open_alert_for_track(db_path, host_address, check_type, port)

    if failures == 0:
        if current_alert:
            resolve_alert(db_path, current_alert['id'], 'RECOVERED')
            logger.info(f"Track {host_label} ({host_address}:{port or check_type}) recovered — resolved alert {current_alert['severity']}")
            actions['resolved'] += 1
    elif failures >= critical_threshold:
        if current_alert and current_alert['severity'] == 'WARNING':
            # Escalation
            resolve_alert(db_path, current_alert['id'], 'ESCALATED')
            logger.error(f"Track {host_label} ({host_address}:{port or check_type}) escalated from WARNING to CRITICAL")
            actions['escalated'] += 1
            insert_alert(db_path, host_label, host_address, check_type, port, 'CRITICAL')
            logger.error(f"CRITICAL alert fired for {host_label} ({host_address}:{port or check_type})")
            actions['fired'].append('CRITICAL')
        elif not current_alert:
            # Jumped threshold or first alert
            insert_alert(db_path, host_label, host_address, check_type, port, 'CRITICAL')
            logger.error(f"CRITICAL alert fired for {host_label} ({host_address}:{port or check_type})")
            actions['fired'].append('CRITICAL')
        else:
            # Already CRITICAL open
            logger.debug(f"CRITICAL alert already open for {host_label} ({host_address}:{port or check_type}) — skipping")
    elif failures >= warning_threshold:
        if not current_alert:
            insert_alert(db_path, host_label, host_address, check_type, port, 'WARNING')
            logger.warning(f"WARNING alert fired for {host_label} ({host_address}:{port or check_type})")
            actions['fired'].append('WARNING')
        else:
            # Alert already open (WARNING or CRITICAL)
            logger.debug(f"Alert already open for {host_label} ({host_address}:{port or check_type}) — skipping")
    else:
        # Below warning threshold
        logger.debug(f"Below warning threshold ({failures} < {warning_threshold}) for {host_label} ({host_address}:{port or check_type}) — skipping")

    return actions


def evaluate_alerts(db_path: str, results: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """Evaluate alerting for all tracks in the current cycle.

    Args:
        db_path: Path to the SQLite database file.
        results: List of check result dicts from the current cycle.
        config: Alert configuration dict.

    Returns:
        Aggregated actions dict.
    """
    total_actions = {
        'fired': [],
        'escalated': 0,
        'resolved': 0,
        'flapped': 0,
        'stabilised': 0,
    }

    for result in results:
        actions = evaluate_track(db_path, result, config)
        total_actions['fired'].extend(actions['fired'])
        total_actions['escalated'] += actions['escalated']
        total_actions['resolved'] += actions['resolved']
        total_actions['flapped'] += actions['flapped']
        total_actions['stabilised'] += actions['stabilised']

    return total_actions


def run_cycle(hosts: list[dict[str, Any]], db_path: str, config: dict[str, Any]) -> None:
    """Run one complete monitoring cycle across all hosts.

    Args:
        hosts: List of host configuration dicts.
        db_path: Path to the SQLite database file.
        config: Full application configuration dict.
    """
    all_results = []
    probe_timeout = config.get('probe_timeout', 3)
    max_workers = config.get('max_workers', 20)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_checks_for_host, host, probe_timeout): host['label']
            for host in hosts
        }

        for future in as_completed(futures):
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"Check failed: {e}")

    save_results(db_path, all_results)

    up_count = sum(1 for r in all_results if r['status'] in ['UP', 'OPEN'])
    down_count = len(all_results) - up_count
    logger.info(f"Cycle complete: {len(all_results)} checks, {up_count} UP, {down_count} DOWN")

    # Evaluate alerts
    alert_actions = evaluate_alerts(db_path, all_results, config)
    if alert_actions['fired'] or alert_actions['escalated'] or alert_actions['resolved'] or alert_actions['flapped'] or alert_actions['stabilised']:
        logger.info(
            f"Alert summary: {len(alert_actions['fired'])} fired "
            f"({alert_actions['fired'].count('WARNING')} WARNING, {alert_actions['fired'].count('CRITICAL')} CRITICAL), "
            f"{alert_actions['escalated']} escalated, "
            f"{alert_actions['resolved']} resolved, "
            f"{alert_actions['flapped']} flapped, "
            f"{alert_actions['stabilised']} stabilised"
        )
