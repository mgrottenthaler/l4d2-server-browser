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
import sys
import tempfile

import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))

# Sizes baked into the .ico/.icns so Windows/macOS have a sharp icon at
# every spot they render it (taskbar, Explorer/Finder list vs. large icon
# view, alt-tab, ...).
ICON_SIZES = [16, 32, 48, 64, 128, 256, 512]


def _build_icon(build_dir):
    """Rasterizes the app icon (steam_browser/static/icon.svg, also used
    as the browser favicon - see index.html) into whatever format
    PyInstaller's --icon wants on this OS, at build time, so the SVG stays
    the single source instead of a checked-in binary icon per platform.

    Windows -> .ico, macOS -> .icns. Skipped on Linux: PyInstaller doesn't
    support embedding an icon into an ELF binary at all (onefile or not),
    so passing --icon there just produces a warning.
    """
    if sys.platform not in ("win32", "darwin"):
        return None

    import cairosvg
    from PIL import Image

    svg_path = os.path.join(HERE, "steam_browser", "static", "icon.svg")
    png_path = os.path.join(build_dir, "icon.png")
    cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=1024, output_height=1024)
    image = Image.open(png_path)

    if sys.platform == "win32":
        icon_path = os.path.join(build_dir, "icon.ico")
        image.save(icon_path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    else:
        icon_path = os.path.join(build_dir, "icon.icns")
        image.save(icon_path, format="ICNS", sizes=[(s, s) for s in ICON_SIZES if s <= 512])
    return icon_path


def main():
    static_dir = os.path.join(HERE, "steam_browser", "static")
    version_file = os.path.join(HERE, "VERSION")
    # PyInstaller's --add-data separator differs by OS (":" vs ";"); build
    # it with os.pathsep so this script itself doesn't need to differ.
    add_data = "{}{}{}".format(static_dir, os.pathsep, "static")
    # VERSION is bundled at the archive root, matching where
    # steam_browser/version.py looks for it (sys._MEIPASS/VERSION) once frozen.
    add_version = "{}{}{}".format(version_file, os.pathsep, ".")

    with tempfile.TemporaryDirectory() as build_dir:
        icon_path = _build_icon(build_dir)

        args = [
            os.path.join(HERE, "launcher.py"),
            "--name=l4d2-server-browser",
            "--onefile",
            "--add-data={}".format(add_data),
            "--add-data={}".format(add_version),
            "--noconfirm",
        ]
        if icon_path:
            args.append("--icon={}".format(icon_path))

        PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
