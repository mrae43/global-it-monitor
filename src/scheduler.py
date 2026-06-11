from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from src.monitor import run_cycle
from src.config.loader import load_config


def start_scheduler():
    """Start the monitoring loop with APScheduler"""
    config = load_config()

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_cycle,
        'interval',
        seconds=config['interval'],
        args=(config['hosts'], config['db_path']),
        max_instances=1,
        misfire_grace_time=30
    )

    logger.info(f"Starting monitoring loop (interval: {config['interval']}s)")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
    finally:
        scheduler.shutdown()
