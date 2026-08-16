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


def configure_logging(config_dir, level=logging.INFO):
    """Attach a rotating file handler + console handler to the root logger,
    so this also picks up libraries that log without any setup of their own
    (notably waitress, which otherwise logs its "Serving on ..." banner and
    any per-connection errors to a logger nobody configures).
    """
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
