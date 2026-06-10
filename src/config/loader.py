import os
from dotenv import load_dotenv
import yaml

def load_env():
    load_dotenv()
    db_path = os.getenv('MONITOR_DB_PATH', 'data/monitor.db')
    interval = int(os.getenv('MONITOR_INTERVAL_SECONDS', '60'))
    log_level = os.getenv('MONITOR_LOG_LEVEL', 'INFO')
    max_workers = int(os.getenv('MONITOR_MAX_WORKERS', '20'))
    probe_timeout = int(os.getenv('MONITOR_PROBE_TIMEOUT', '3'))
    return {
        'db_path': db_path,
        'interval': interval,
        'log_level': log_level,
        'max_workers': max_workers,
        'probe_timeout': probe_timeout,
    }

def load_hosts(path='config/hosts.yaml'):
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

def load_config():
    config = load_env()
    config['hosts'] = load_hosts()
    return config
