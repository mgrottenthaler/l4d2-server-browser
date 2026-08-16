#!/usr/bin/env python3
"""Builds the single-file desktop executable (launcher.py + waitress + the
static UI, frozen with PyInstaller). PyInstaller doesn't cross-compile, so
this has to run once per target OS - see
.github/workflows/build-executables.yml, which does exactly that across
Linux/Windows/macOS runners and uploads each result as a build artifact.

Usage: python3 build_executable.py   (after `pip install -r requirements-build.txt`)
Output: dist/l4d2-server-browser(.exe)
"""
import os

import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    static_dir = os.path.join(HERE, "steam_browser", "static")
    version_file = os.path.join(HERE, "VERSION")
    # PyInstaller's --add-data separator differs by OS (":" vs ";"); build
    # it with os.pathsep so this script itself doesn't need to differ.
    add_data = "{}{}{}".format(static_dir, os.pathsep, "static")
    # VERSION is bundled at the archive root, matching where
    # steam_browser/version.py looks for it (sys._MEIPASS/VERSION) once frozen.
    add_version = "{}{}{}".format(version_file, os.pathsep, ".")

    PyInstaller.__main__.run([
        os.path.join(HERE, "launcher.py"),
        "--name=l4d2-server-browser",
        "--onefile",
        "--add-data={}".format(add_data),
        "--add-data={}".format(add_version),
        "--noconfirm",
    ])


if __name__ == "__main__":
    main()
