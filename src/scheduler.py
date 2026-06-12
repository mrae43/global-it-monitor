from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from monitor import run_cycle


def start_scheduler(config: dict[str, Any]) -> None:
    """Start the APScheduler monitoring loop.

    Fires an initial cycle immediately, then schedules recurring cycles at the given interval.

    Args:
        config: Full application configuration dict with keys interval, hosts, db_path,
                max_workers, probe_timeout, and alert thresholds.
    """
    interval = config['interval']
    hosts = config['hosts']
    db_path = config['db_path']

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_cycle,
        'interval',
        seconds=interval,
        args=(hosts, db_path, config),
        max_instances=1,
        misfire_grace_time=30
    )

    # Fire first cycle immediately
    logger.info("Running initial monitoring cycle...")
    try:
        run_cycle(hosts, db_path, config)
    except Exception as e:
        logger.error(f"Initial monitoring cycle failed: {e}")

    logger.info(f"Starting monitoring loop (interval: {interval}s)")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
    finally:
        scheduler.shutdown()
