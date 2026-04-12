# -*- encoding: utf-8 -*-
"""
Structured logging configuration for the WMS API.

Usage in any module:
    from .core.logging import get_logger
    logger = get_logger(__name__)

    logger.info("Order created", extra={'order_id': 42})
    logger.exception("Upload failed")   # auto-captures stack trace

Production (APP_ENV=production): one JSON object per line — compatible
with Datadog, CloudWatch, Splunk, etc.

Development / staging: human-readable coloured output.
"""

import json
import logging
import sys
from datetime import datetime, timezone


class _JSONFormatter(logging.Formatter):
    """One JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        obj = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level':     record.levelname,
            'logger':    record.name,
            'message':   record.getMessage(),
            'module':    record.module,
            'function':  record.funcName,
            'line':      record.lineno,
        }
        if record.exc_info:
            obj['exception'] = self.formatException(record.exc_info)
        # Allow callers to attach arbitrary extra keys via extra={} kwarg
        for key, val in record.__dict__.items():
            if key not in (
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                'thread', 'threadName', 'processName', 'process', 'message',
                'taskName',
            ):
                obj[key] = val
        return json.dumps(obj, default=str)


class _DevFormatter(logging.Formatter):
    """Readable single-line format for development."""

    _COLOURS = {
        'DEBUG':    '\033[36m',   # cyan
        'INFO':     '\033[32m',   # green
        'WARNING':  '\033[33m',   # yellow
        'ERROR':    '\033[31m',   # red
        'CRITICAL': '\033[35m',   # magenta
    }
    _RESET = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:
        colour = self._COLOURS.get(record.levelname, '')
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        base = (
            f"{ts} {colour}[{record.levelname}]{self._RESET} "
            f"{record.name}: {record.getMessage()}"
        )
        if record.exc_info:
            base += '\n' + self.formatException(record.exc_info)
        return base


def configure_logging(app) -> None:
    """
    Call once inside create_app() after loading config.
    Sets the root logger level and formatter based on APP_ENV.
    """
    is_production = app.config.get('APP_ENV', 'development') == 'production'
    level = logging.INFO if is_production else logging.DEBUG

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter() if is_production else _DevFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Drop-in replacement for logging.getLogger().
    Preferred over direct getLogger() so all loggers go through this module.
    """
    return logging.getLogger(name)
