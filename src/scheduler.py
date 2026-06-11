from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from src.monitor import run_cycle


def start_scheduler(interval, hosts, db_path):
    """Start the monitoring loop with APScheduler"""
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_cycle,
        'interval',
        seconds=interval,
        args=(hosts, db_path),
        max_instances=1,
        misfire_grace_time=30
    )

    logger.info(f"Starting monitoring loop (interval: {interval}s)")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
    finally:
        scheduler.shutdown()
