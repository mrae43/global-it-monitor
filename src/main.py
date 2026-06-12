import os
import sys
from loguru import logger
from scheduler import start_scheduler
from config.loader import load_config, validate_alert_config
from storage.database import init_database


def main() -> None:
    """Application entry point.

    Loads configuration, initialises the database, configures logging,
    and starts the blocking scheduler loop.
    """
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)

    # Validate alert configuration
    try:
        validate_alert_config(config)
    except ValueError as e:
        logger.error(f"Invalid alert configuration: {e}")
        sys.exit(1)

    # Initialize database
    try:
        init_database(config['db_path'])
    except Exception as e:
        logger.error(f"Failed to initialize database {e}")
        sys.exit(1)

    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    # Configure logging
    logger.add(
        "logs/monitor.log",
        rotation="5 MB",
        retention=3,
        level=config['log_level']
    )

    logger.info("Global IT Infrastructure Monitor starting...")
    logger.info(f"Loaded {len(config['hosts'])} hosts, interval={config['interval']}s")

    # Start the scheduler (blocking)
    start_scheduler(config)


if __name__ == "__main__":
    main()
