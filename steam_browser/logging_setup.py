"""Logging setup: writes to CONFIG_DIR (the same per-user OS directory .env
lives in - see web.py's _config_dir), never next to the executable, for the
same reason .env can't live there either: a frozen --onefile build's
sys.executable location isn't reliably writable, and PyInstaller re-extracts
a fresh temp dir on every launch anyway.
"""
import logging
import logging.handlers
import os

LOG_FILENAME = "l4d2-server-browser.log"

_configured = False


def configure_logging(config_dir, level=logging.INFO):
    """Attach a rotating file handler + console handler to the root logger,
    so this also picks up libraries that log without any setup of their own
    (notably waitress, which otherwise logs its "Serving on ..." banner and
    any per-connection errors to a logger nobody configures).

    A no-op after the first call: web.py runs this at import time, and while
    a normal module import is only ever executed once per process, guarding
    here avoids doubled-up log lines (and, on Windows, a second
    RotatingFileHandler racing the first over the same file on rotation) if
    that ever stops being true - e.g. a module reload, or the same file
    imported under two different names.
    """
    global _configured
    if _configured:
        return
    _configured = True

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(config_dir, LOG_FILENAME), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
