import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord


def setup_logging(level: int = logging.INFO) -> None:
    """Set up the logging configuration.

    This configures the root logger to output to both the console (via discord.utils)
    and a unique timestamped log file in the 'logs/' directory.

    A separate telemetry log file captures all telemetry events at DEBUG level
    regardless of the root log level, so telemetry data can be analyzed independently.
    """
    # 1. Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # 2. Generate timestamped filename for this session
    timestamp = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"capy_{timestamp}.log"

    # 3. Setup Console Logging (Standard Discord format)
    # root=True ensures we capture logs from all libraries (discord, asyncio, etc.)
    discord.utils.setup_logging(level=level, root=True)

    # 4. Setup Consolidated File Logging
    # We use mode="w" (or "a", but timestamp ensures uniqueness)
    dt_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter("[{asctime}] [{levelname:<8}] {name}: {message}", dt_fmt, style="{")

    file_handler = logging.FileHandler(filename=log_file, encoding="utf-8", mode="w")
    file_handler.setFormatter(formatter)
    logging.getLogger().addHandler(file_handler)

    # 5. Setup Dedicated Telemetry Log File
    # Writes at DEBUG level so telemetry events are always captured even if root is INFO
    telemetry_log_file = log_dir / f"telemetry_{timestamp}.log"
    telemetry_handler = logging.FileHandler(filename=telemetry_log_file, encoding="utf-8", mode="w")
    telemetry_handler.setLevel(logging.DEBUG)
    telemetry_handler.setFormatter(formatter)
    telemetry_logger = logging.getLogger("capy_discord.exts.core.telemetry")
    telemetry_logger.addHandler(telemetry_handler)
    telemetry_logger.setLevel(logging.DEBUG)
    telemetry_logger.propagate = False
