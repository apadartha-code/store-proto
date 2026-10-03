from __future__ import annotations

from __future__ import annotations

import logging
import logging.handlers
import sys

from app.config import Config

SYSLOG_APP_NAME = "image-store"


def _parse_syslog_address(address: str):
    if address.startswith("/"):
        return address
    if ":" in address:
        host, port_str = address.rsplit(":", 1)
        return (host, int(port_str))
    return (address, 514)


def _attach_syslog(level: int) -> None:
    app_logger = logging.getLogger("app")
    for handler in app_logger.handlers:
        if isinstance(handler, logging.handlers.SysLogHandler):
            return

    address = _parse_syslog_address(Config.LOG_SYSLOG_ADDRESS)
    try:
        handler = logging.handlers.SysLogHandler(address=address)
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).error(
            "Failed to open syslog at %s: %s", Config.LOG_SYSLOG_ADDRESS, exc
        )
        return

    handler.ident = f"{SYSLOG_APP_NAME}"
    handler.setFormatter(
        logging.Formatter("%(name)s %(levelname)s %(message)s")
    )
    handler.setLevel(level)
    app_logger.addHandler(handler)
    app_logger.setLevel(level)


def setup_logging() -> None:
    level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)

    root = logging.getLogger()
    if not root.handlers:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        root.addHandler(stderr_handler)

    root.setLevel(level)
    logging.getLogger("werkzeug").setLevel(logging.INFO)

    if Config.LOG_SYSLOG:
        _attach_syslog(level)
