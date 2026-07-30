"""Bounded rotating runtime log for the ``lockverity`` CLI.

The ``start`` command uses this module to wire a
:class:`logging.handlers.RotatingFileHandler` against the
``logs/lockverity.log`` file under the runtime home. The
handler is bounded: every rotated file is at most
``max_bytes`` (10 MiB by default) and at most
``backup_count`` (5 by default) generations are kept. The
total disk footprint is therefore at most
``max_bytes * (backup_count + 1)`` bytes.

The setup function is idempotent: re-invoking it with
the same ``log_path`` returns the existing handler so
``start`` can call it from both the foreground and
background code paths without double-attaching.

The handler never writes secrets: the log records
level, time, logger name, and message. The CLI does
not configure a ``logging.Filter`` for the LogRecord
``args`` or ``msg`` because the application log
messages never embed a token or password; the
boundary is enforced by the *application* code
that emits the log records, not by this handler.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
DEFAULT_BACKUP_COUNT = 5

# Log format: a single line per record with a UTC ISO
# timestamp, the level, the logger name, and the message.
# The format is intentionally short so each rotated file
# holds the maximum number of records.
LOG_FORMAT = "%(asctime)sZ %(levelname)s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%dT%H:%M:%S"

# Logger name used by the CLI for its own messages (start
# / stop / status output). The application loggers
# (``lockverity``, ``uvicorn``, ``alembic``, ...) keep
# their own names; the CLI logger is additive so the
# operator can filter the CLI messages out if needed.
CLI_LOGGER_NAME = "lockverity.cli"


def configure_logging(
    log_path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    level: int = logging.INFO,
) -> logging.Logger:
    """Attach a rotating file handler to the CLI logger.

    The function is idempotent: a second call with the
    same ``log_path`` returns the existing logger without
    attaching a second handler. The handler uses UTF-8
    encoding so the log file is portable across hosts.

    The function never configures the root logger; only
    the CLI logger and its descendants receive the
    rotating file handler. The application loggers keep
    their own configuration (or, in production, the
    default ``StreamHandler``).
    """
    logger = logging.getLogger(CLI_LOGGER_NAME)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    for existing in list(logger.handlers):
        if (
            isinstance(existing, RotatingFileHandler)
            and Path(getattr(existing, "baseFilename", "")) == log_path
        ):
            existing.setLevel(level)
            logger.setLevel(level)
            return logger
    handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_cli_logger() -> logging.Logger:
    """Return the CLI logger without attaching a handler.

    The function is used by callers that want to emit
    a structured log record through the same channel
    the ``start`` command configured, without re-running
    the handler configuration.
    """
    return logging.getLogger(CLI_LOGGER_NAME)


__all__ = [
    "CLI_LOGGER_NAME",
    "DEFAULT_BACKUP_COUNT",
    "DEFAULT_MAX_BYTES",
    "configure_logging",
    "get_cli_logger",
]
