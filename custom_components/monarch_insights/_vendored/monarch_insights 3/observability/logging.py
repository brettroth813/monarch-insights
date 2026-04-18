"""Structured logging configuration.

We pick stdlib ``logging`` over ``structlog`` to keep the dependency footprint small
and to interop with Home Assistant, which already configures the root logger. The cost
is about thirty extra lines here to make every call structured-by-default.

Design notes
------------

*   **One file per day, retained ~365 days by default.** ``TimedRotatingFileHandler``
    rolls at midnight UTC. Brett wants long history; storage is cheap on the Pi.
*   **Stdout stays human-friendly only when no file handler is attached.** When the file
    sink is on (the normal case), stdout becomes JSON too so external collectors get a
    consistent stream.
*   **Every record carries ``app=monarch-insights``.** Filterable in HA logs and Loki.
*   **``extra`` dicts are flattened** into the top-level JSON object. Reserved fields
    (``message``, ``level``, ``logger``, ``ts``, ``module``, ``function``) cannot be
    overwritten by callers so logs stay parseable.

Public surface
--------------

``configure_logging(level=..., log_dir=..., json_to_stdout=...)`` is idempotent — call
it as early as possible from CLI / daemon / HA component bootstrap. Subsequent calls
update level/handlers without duplicating outputs.

``get_logger(name)`` is a thin wrapper around ``logging.getLogger`` that exists so
modules don't need to import ``logging`` directly.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_LOG_DIR = Path.home() / ".local" / "share" / "monarch-insights" / "logs"
DEFAULT_LOG_LEVEL = logging.INFO
APP_NAME = "monarch-insights"

# These keys are stamped onto every record by ``JsonFormatter`` and may not be shadowed
# by user-supplied ``extra`` dicts — preserving them keeps every log line parseable.
_RESERVED_FIELDS = frozenset(
    {"message", "level", "logger", "ts", "module", "function", "line", "app", "pid"}
)

# Tracks whether ``configure_logging`` has been called so subsequent calls are idempotent
# (they update level + handlers in place rather than stacking duplicates).
_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    """Render ``logging.LogRecord`` as a single JSON object per line.

    The formatter pulls a small fixed set of LogRecord attributes (level, logger name,
    timestamp, source location) and merges in any extra fields the caller attached via
    ``logger.info("msg", extra={...})``. Non-serialisable values fall back to their
    string representation so a bad ``extra`` doesn't crash the logger.
    """

    def __init__(self, *, app: str = APP_NAME) -> None:
        super().__init__()
        self.app = app

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - imperative is fine
        payload: dict[str, Any] = {
            "ts": _iso_utc(record.created),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "app": self.app,
            "pid": record.process,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # Pull caller-supplied extras (anything not in the standard attribute set).
        for key, value in record.__dict__.items():
            if key in _LOGRECORD_BUILTINS:
                continue
            if key in _RESERVED_FIELDS:
                # Reserved — caller doesn't get to overwrite parseable structure.
                continue
            payload[key] = _coerce(value)

        return json.dumps(payload, default=_coerce, separators=(",", ":"))


def configure_logging(
    *,
    level: int | str = DEFAULT_LOG_LEVEL,
    log_dir: Path | None = DEFAULT_LOG_DIR,
    json_to_stdout: bool = True,
    rotation_when: str = "midnight",
    rotation_backup_count: int = 365,
) -> None:
    """Set up structured logging once per process.

    Args:
        level: Numeric logging level (``logging.INFO``) or string (``"DEBUG"``).
        log_dir: Directory for the rotating JSON log file. Set to ``None`` to disable
            file output (useful in tests).
        json_to_stdout: If ``True`` (default) stdout receives JSON so external log
            collectors can parse it. Set to ``False`` for interactive CLI use where
            human-readable output is preferable.
        rotation_when: Pass-through to :class:`TimedRotatingFileHandler` (default
            ``"midnight"`` rotates daily).
        rotation_backup_count: How many rolled files to keep. Defaults to 365 (one year)
            because the user prefers long history.
    """

    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level)

    # Strip any handlers we previously attached so configure_logging is safe to call
    # repeatedly (e.g. from both CLI bootstrap and daemon startup).
    for handler in [h for h in root.handlers if getattr(h, "_monarch_insights", False)]:
        root.removeHandler(handler)

    formatter = JsonFormatter()

    stdout_handler = logging.StreamHandler(sys.stdout)
    if json_to_stdout:
        stdout_handler.setFormatter(formatter)
    else:
        stdout_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
    stdout_handler._monarch_insights = True  # type: ignore[attr-defined]
    root.addHandler(stdout_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_dir / "monarch-insights.log"),
            when=rotation_when,
            backupCount=rotation_backup_count,
            utc=True,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._monarch_insights = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger; first call ensures :func:`configure_logging` has run.

    A library should not configure global state on import, but interactive callers
    routinely forget to set up logging — this helper makes sure something useful happens
    on first ``get_logger`` call so we never silently drop messages.
    """

    if not _CONFIGURED and not _has_handlers_outside_pytest():
        configure_logging()
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _iso_utc(ts: float) -> str:
    """Render a Unix timestamp as ``YYYY-MM-DDTHH:MM:SS.sssZ`` (UTC, ms precision)."""
    millis = int((ts - int(ts)) * 1000)
    return f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(ts))}.{millis:03d}Z"


def _coerce(value: Any) -> Any:
    """Best-effort serialiser for ``json.dumps``.

    Pydantic BaseModels and dataclasses get their dict form; Decimal becomes float;
    sets become lists; anything else falls back to its repr so the log line stays
    valid JSON.
    """
    from decimal import Decimal

    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, set):
        return sorted(value, key=str)
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            return repr(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return {k: _coerce(v) for k, v in vars(value).items() if not k.startswith("_")}
    return repr(value)


def _has_handlers_outside_pytest() -> bool:
    """Pytest installs its own handlers; don't override those during test runs."""
    if "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST"):
        return True
    root = logging.getLogger()
    return any(not getattr(h, "_monarch_insights", False) for h in root.handlers)


# Cache the standard LogRecord attribute names so the formatter knows which keys belong
# to ``extra`` and which are part of every record. Calling ``LogRecord.__dict__`` here
# would only see the class attrs; using ``vars()`` on a dummy record gives the full set.
_LOGRECORD_BUILTINS = frozenset(
    vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)).keys()
) | {"asctime", "message"}
