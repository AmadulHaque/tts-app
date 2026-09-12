"""Logging to a file plus stderr, configured once at startup."""

from __future__ import annotations

import logging
import sys

from .paths import log_path

_LOGGER_NAME = "kokoro_studio"


def _configure_file_handler(root: logging.Logger, level: int) -> None:
    for h in root.handlers:
        if isinstance(h, logging.FileHandler) and getattr(h, "_kokoro_file", False):
            h.setLevel(level)
            return
    try:
        fp = log_path()
        handler = logging.FileHandler(fp, encoding="utf-8")
        handler._kokoro_file = True  # type: ignore[attr-defined]
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
        root.addHandler(handler)
    except OSError:
        pass


def setup_logger(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(fmt="%(levelname)-7s %(message)s"))
        logger.addHandler(handler)

    _configure_file_handler(logging.getLogger(), getattr(logging, level.upper(), logging.INFO))
    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{_LOGGER_NAME}.{name}" if name else _LOGGER_NAME)
