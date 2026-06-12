import subprocess
import platform
import re
from typing import Any

from loguru import logger


def ping(host: str, timeout: int = 3) -> dict[str, Any]:
    """
    Send one ICMP echo request to the host using the OS ping binary.

    Args:
        host: The hostname or IP address to ping.
        timeout: Timeout in seconds for the ping command.

    Returns:
        dict with keys:
            - status: 'UP' or 'DOWN'
            - latency_ms: round-trip latency in milliseconds (float), or None
    """
    system = platform.system().lower()

    if system == 'windows':
        count_flag = '-n'
        timeout_flag = '-w'
        timeout_value = str(timeout * 1000)
    else:
        count_flag = '-c'
        timeout_flag = '-W'
        timeout_value = str(timeout)

    cmd = ['ping', count_flag, '1', timeout_flag, timeout_value, host]

    try:
        logger.debug(f"Pinging {host}...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )

        if result.returncode == 0:
            match = re.search(r'time[=<]([\d.]+)', result.stdout)
            latency = float(match.group(1)) if match else None
            return {'status': 'UP', 'latency_ms': latency}
        else:
            return {'status': 'DOWN', 'latency_ms': None}

    except subprocess.TimeoutExpired:
        logger.warning(f"ICMP ping to {host} timed out after {timeout + 2}s")
        return {'status': 'DOWN', 'latency_ms': None}
    except Exception as e:
        logger.error(f"ICMP ping to {host} failed: {e}")
        return {'status': 'DOWN', 'latency_ms': None}
