from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from monitor import run_cycle


def start_scheduler(interval: int, hosts: list[dict[str, Any]], db_path: str, max_workers: int = 20, probe_timeout: int = 3) -> None:
    """Start the APScheduler monitoring loop.

    Fires an initial cycle immediately, then schedules recurring cycles at the given interval.

    Args:
        interval: Seconds between cycles.
        hosts: List of host configuration dicts.
        db_path: Path to the SQLite database file.
        max_workers: Maximum thread pool workers.
        probe_timeout: Timeout in seconds per probe.
    """
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_cycle,
        'interval',
        seconds=interval,
        args=(hosts, db_path, max_workers, probe_timeout),
        max_instances=1,
        misfire_grace_time=30
    )

    # Fire first cycle immediately
    logger.info("Running initial monitoring cycle...")
    run_cycle(hosts, db_path, max_workers, probe_timeout)

    logger.info(f"Starting monitoring loop (interval: {interval}s)")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
    finally:
        scheduler.shutdown()
