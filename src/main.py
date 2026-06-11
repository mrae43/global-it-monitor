import os
import sys
from loguru import logger
from src.scheduler import start_scheduler
from src.config.loader import load_config
from src.storage.database import init_database

def main():
  """Entry point"""
  try:
    config = load_config()
  except Exception as e:
    logger.error(f"Failed to load config: {e}")
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

  # Start the scheduler (blocking)
  start_scheduler(config['interval'], config['hosts'], config['db_path'])

if __name__ == "__main__":
  main()
