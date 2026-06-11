from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from loguru import logger

from probes.icmp import ping
from probes.tcp import check_port
from storage.database import save_results


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
        'host_ip': host_config['host'],
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
            'host_ip': host_config['host'],
            'check_type': 'TCP',
            'port': port,
            'status': tcp_result['status'],
            'latency_ms': tcp_result['latency_ms']
        })

    return results


def run_cycle(hosts: list[dict[str, Any]], db_path: str, max_workers: int = 20, probe_timeout: int = 3) -> None:
    """Run one complete monitoring cycle across all hosts.

    Args:
        hosts: List of host configuration dicts.
        db_path: Path to the SQLite database file.
        max_workers: Maximum thread pool workers.
        probe_timeout: Timeout in seconds per probe.
    """
    all_results = []

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
