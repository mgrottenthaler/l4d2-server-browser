"""Reads VERSION, the single source of truth for the app's release version -
bumped and tagged by release.py, bundled into the frozen build via
build_executable.py's --add-data, and served at GET /api/version for the UI
footer.
"""

import os
import sys


def _version_file():
    # Same frozen/unfrozen split as web.py's _static_dir(): under
    # PyInstaller, __file__ doesn't exist on disk, so VERSION has to be
    # bundled explicitly and read back from the onefile extraction dir.
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "VERSION")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")


def get_version():
    with open(_version_file(), "r") as f:
        return f.read().strip()
