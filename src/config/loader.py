import os
from typing import Any

from dotenv import load_dotenv
import yaml


def load_env() -> dict[str, Any]:
    """Load configuration from environment variables with defaults.

    Returns:
        Dict with keys: db_path, interval, log_level, max_workers, probe_timeout,
        warning_threshold, critical_threshold, flap_transitions, flap_window_minutes,
        stabilisation_threshold.
    """
    load_dotenv()
    db_path = os.getenv('MONITOR_DB_PATH', 'data/monitor.db')
    interval = int(os.getenv('MONITOR_INTERVAL_SECONDS', '60'))
    log_level = os.getenv('MONITOR_LOG_LEVEL', 'INFO')
    max_workers = int(os.getenv('MONITOR_MAX_WORKERS', '20'))
    probe_timeout = int(os.getenv('MONITOR_PROBE_TIMEOUT', '3'))
    warning_threshold = int(os.getenv('MONITOR_WARNING_THRESHOLD', '3'))
    critical_threshold = int(os.getenv('MONITOR_CRITICAL_THRESHOLD', '5'))
    flap_transitions = int(os.getenv('MONITOR_FLAP_TRANSITIONS', '3'))
    flap_window_minutes = int(os.getenv('MONITOR_FLAP_WINDOW_MINUTES', '10'))
    stabilisation_threshold = int(os.getenv('MONITOR_STABILISATION_THRESHOLD', '3'))
    return {
        'db_path': db_path,
        'interval': interval,
        'log_level': log_level,
        'max_workers': max_workers,
        'probe_timeout': probe_timeout,
        'warning_threshold': warning_threshold,
        'critical_threshold': critical_threshold,
        'flap_transitions': flap_transitions,
        'flap_window_minutes': flap_window_minutes,
        'stabilisation_threshold': stabilisation_threshold,
    }


def validate_alert_config(config: dict[str, Any]) -> None:
    """Validate alert threshold configuration.

    Raises:
        ValueError: If thresholds are invalid.
    """
    if config['warning_threshold'] < 1:
        raise ValueError(f"WARNING_THRESHOLD ({config['warning_threshold']}) must be >= 1")
    if config['critical_threshold'] < 1:
        raise ValueError(f"CRITICAL_THRESHOLD ({config['critical_threshold']}) must be >= 1")
    if config['critical_threshold'] <= config['warning_threshold']:
        raise ValueError(
            f"CRITICAL_THRESHOLD ({config['critical_threshold']}) must be greater than "
            f"WARNING_THRESHOLD ({config['warning_threshold']})"
        )
    if config['flap_transitions'] < 2:
        raise ValueError(f"FLAP_TRANSITIONS ({config['flap_transitions']}) must be >= 2")
    if config['flap_window_minutes'] <= 0:
        raise ValueError(f"FLAP_WINDOW_MINUTES ({config['flap_window_minutes']}) must be > 0")
    if config['stabilisation_threshold'] < 1:
        raise ValueError(f"STABILISATION_THRESHOLD ({config['stabilisation_threshold']}) must be >= 1")


def load_hosts(path: str = 'config/hosts.yaml') -> list[dict[str, Any]]:
    """Load and validate host configuration from a YAML file.

    Invalid entries are logged and skipped.

    Args:
        path: Path to the hosts YAML file.

    Returns:
        List of valid host config dicts with keys label, host, ports.
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ERROR: Host config not found at {path}")
        return []
    except yaml.YAMLError as e:
        print(f"ERROR: Malformed YAML in {path}: {e}")
        return []

    if data is None:
        print(f"WARNING: {path} is empty — no hosts configured")
        return []

    hosts_raw = data.get('hosts', [])
    if not hosts_raw:
        print(f"WARNING: No hosts defined in {path}")
        return []

    valid_hosts = []
    for i, entry in enumerate(hosts_raw):
        label = entry.get('label')
        host = entry.get('host')
        ports = entry.get('ports')

        if not label or not isinstance(label, str):
            print(f"WARNING: host entry {i} missing or invalid 'label' — skipping")
            continue
        if not host or not isinstance(host, str):
            print(f"WARNING: host entry {i} ('{label}') missing or invalid 'host' — skipping")
            continue
        if not ports or not isinstance(ports, list) or not all(isinstance(p, int) for p in ports):
            print(f"WARNING: host entry {i} ('{label}') missing or invalid 'ports' — skipping")
            continue

        valid_hosts.append({'label': label, 'host': host, 'ports': ports})

    return valid_hosts


def load_config() -> dict[str, Any]:
    """Load full application configuration from environment and YAML.

    Returns:
        Combined config dict including env settings and hosts list.
    """
    config = load_env()
    config['hosts'] = load_hosts()
    return config
