import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

# Standard format: [Time] [Level] [Logger Name]: Message
LOG_FORMAT: Final[str] = "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"


class ColoredFormatter(logging.Formatter):
    """A custom logging formatter that adds colors to the output."""

    def __init__(self, fmt: str, datefmt: str) -> None:
        """Initialize the ColoredFormatter."""
        super().__init__(fmt, datefmt)
        self.level_colors = {
            logging.INFO: "\033[92m",  # Green
            logging.WARNING: "\033[93m",  # Yellow
            logging.ERROR: "\033[91m",  # Red
            logging.CRITICAL: "\033[91m",  # Red
            logging.DEBUG: "\033[94m",  # Blue
        }
        self.name_color = "\033[96m"  # Cyan
        self.reset = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record."""
        # Get the color for the level
        level_color = self.level_colors.get(record.levelno, "")

        # Temporarily add color to the levelname and name
        original_levelname = record.levelname
        original_name = record.name

        record.levelname = f"{level_color}{original_levelname}{self.reset}"
        record.name = f"{self.name_color}{original_name}{self.reset}"

        # Format the message
        formatted_message = super().format(record)

        # Restore the original values
        record.levelname = original_levelname
        record.name = original_name

        return formatted_message


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name."""
    return logging.getLogger(name)


def setup_logging(level: int | str = logging.INFO) -> None:
    """Set up the logging configuration with the specified level."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Create a handler that writes to stdout
    stream_handler = logging.StreamHandler(sys.stdout)
    colored_formatter = ColoredFormatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    stream_handler.setFormatter(colored_formatter)

    # Create a log directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Create a timestamped filename
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = log_dir / f"capy-discord_{timestamp}.log"

    # Create a handler that writes to a file with rotation
    file_handler = RotatingFileHandler(
        filename=log_filename,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    file_handler.setFormatter(file_formatter)

    # Removing previous handlers to avoid duplicate logs from discord after setup_logging invokation
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)
