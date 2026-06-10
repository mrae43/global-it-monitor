import socket
import time

from loguru import logger


def check_port(host: str, port: int, timeout: float = 3) -> dict:
    """
    Attempts a TCP connection to host:port using the built-in socket module.

    Args:
        host: The hostname or IP address to connect to.
        port: The TCP port to check.
        timeout: Timeout in seconds for the connection attempt.

    Returns:
        dict with keys:
            - status: 'OPEN' or 'CLOSED'
            - latency_ms: round-trip connection time in milliseconds (float), or None
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        start = time.time()
        result = sock.connect_ex((host, port))
        latency_ms = (time.time() - start) * 1000

        if result == 0:
            return {"status": "OPEN", "latency_ms": round(latency_ms, 2)}
        else:
            return {"status": "CLOSED", "latency_ms": None}

    except (socket.timeout, OSError) as e:
        logger.warning(f"TCP check to {host}:{port} failed: {e}")
        return {"status": "CLOSED", "latency_ms": None}
    except Exception as e:
        logger.error(f"Unexpected error during TCP check to {host}:{port}: {e}")
        return {"status": "CLOSED", "latency_ms": None}
    finally:
        sock.close()
