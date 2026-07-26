"""Professional logging configuration.

Provides structured logging with support for JSON format and multiple handlers.
"""

import logging
import logging.handlers
import sys
import json
from pathlib import Path
from typing import Optional
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        return json.dumps(log_data, ensure_ascii=False)


class Logger:
    """Centralized logger factory."""

    _instance: Optional[logging.Logger] = None
    _configured: bool = False

    @classmethod
    def setup(
        cls,
        name: str = "livescores_betting",
        level: int = logging.INFO,
        log_file: Optional[Path] = None,
        use_json: bool = False,
    ) -> logging.Logger:
        """Configure and return the logger.

        Args:
            name: Logger name
            level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Optional file path for file logging
            use_json: Whether to use JSON format for logging

        Returns:
            Configured logger instance
        """
        if cls._configured and cls._instance is not None:
            return cls._instance

        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False

        # Console handler with color support
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)

        if use_json:
            formatter = JSONFormatter()
        else:
            formatter = logging.Formatter(
                fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File handler if specified
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                filename=log_file,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        cls._instance = logger
        cls._configured = True

        return logger

    @classmethod
    def get_logger(cls, name: str = "livescores_betting") -> logging.Logger:
        """Get configured logger instance.

        Returns:
            Logger instance
        """
        if cls._instance is None:
            return cls.setup(name=name)
        return cls._instance
