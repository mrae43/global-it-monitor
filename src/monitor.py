from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from src.probes.icmp import ping
from src.probes.tcp import check_port
from src.storage.database import save_results, init_database


def run_checks_for_host(host_config):
    """Run ICMP + all TCP checks for one host"""
    results = []

    # ICMP check
    ping_result = ping(host_config['host'])
    results.append({
        'host_label': host_config['label'],
        'host_ip': host_config['host'],
        'check_type': 'ICMP',
        'status': ping_result['status'],
        'latency_ms': ping_result['latency_ms']
    })

    # TCP checks (one per port)
    for port in host_config.get('ports', []):
        tcp_result = check_port(host_config['host'], port)
        results.append({
            'host_label': host_config['label'],
            'host_ip': host_config['host'],
            'check_type': 'TCP',
            'port': port,
            'status': tcp_result['status'],
            'latency_ms': tcp_result['latency_ms']
        })

    return results


def run_cycle(hosts, db_path, max_workers=20):
    """Run one complete monitoring cycle"""
    all_results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_checks_for_host, host): host['label']
            for host in hosts
        }

        for future in as_completed(futures):
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"Check failed: {e}")

    init_database(db_path)
    save_results(db_path, all_results)

    up_count = sum(1 for r in all_results if r['status'] in ['UP', 'OPEN'])
    down_count = len(all_results) - up_count
    logger.info(f"Cycle complete: {len(all_results)} checks, {up_count} UP, {down_count} DOWN")
