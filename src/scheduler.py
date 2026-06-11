from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from monitor import run_cycle


def start_scheduler(interval, hosts, db_path, max_workers=20, probe_timeout=3):
    """Start the monitoring loop with APScheduler"""
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
