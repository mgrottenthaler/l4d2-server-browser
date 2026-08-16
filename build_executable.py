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


def _rasterize_icon(build_dir):
    """Rasterizes the app icon (steam_browser/static/icon.svg, also used
    as the browser favicon - see index.html) to PNG once at build time,
    the shared source for both the OS-native --icon below and the PNG
    bundled for launcher.py's own log window, so the SVG stays the single
    source instead of a checked-in binary per platform/purpose.
    """
    import resvg_py
    from PIL import Image

    svg_path = os.path.join(HERE, "steam_browser", "static", "icon.svg")
    png_path = os.path.join(build_dir, "icon.png")
    png_bytes = resvg_py.svg_to_bytes(svg_path=svg_path, width=1024, height=1024)
    with open(png_path, "wb") as f:
        f.write(png_bytes)
    return Image.open(png_path)


def _build_native_icon(build_dir, image):
    """Converts the rasterized icon into whatever format PyInstaller's
    --icon wants on this OS: Windows -> .ico, macOS -> .icns. Skipped on
    Linux: PyInstaller doesn't support embedding an icon into an ELF binary
    at all (onefile or not), so passing --icon there just produces a
    warning. This only brands the .exe/.app file itself (and, on Windows,
    whichever console host happens to be hosting it - which Windows
    Terminal ignores), not the actual window launcher.py opens.
    """
    if sys.platform == "win32":
        icon_path = os.path.join(build_dir, "icon.ico")
        # Pillow's ICO encoder silently drops any requested size over 256
        # (Windows .ico frames top out there), so 512 in ICON_SIZES would
        # otherwise be dead weight here.
        image.save(icon_path, format="ICO", sizes=[(s, s) for s in ICON_SIZES if s <= 256])
        return icon_path
    if sys.platform == "darwin":
        icon_path = os.path.join(build_dir, "icon.icns")
        # No sizes= here: Pillow's ICNS encoder ignores that argument and
        # always writes its own fixed table (32/64/128/256/512/1024),
        # capped by the source image's resolution - which the 1024x1024
        # raster above covers in full.
        image.save(icon_path, format="ICNS")
        return icon_path
    return None


def _build_window_icon(build_dir, image):
    """PNG bundled into the frozen app for launcher.py's _LogWindow to set
    as its own window/taskbar icon at runtime, on every OS - unlike
    _build_native_icon above, this is what actually shows up once the app
    is running, since _LogWindow is a real window we own rather than a
    console hosted by whatever terminal app the OS picks.
    """
    icon_path = os.path.join(build_dir, "window_icon.png")
    image.resize((256, 256)).save(icon_path, format="PNG")
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
        image = _rasterize_icon(build_dir)
        native_icon_path = _build_native_icon(build_dir, image)
        window_icon_path = _build_window_icon(build_dir, image)
        # Bundled at the archive root as window_icon.png, matching where
        # launcher.py's _window_icon_path() looks for it once frozen.
        add_window_icon = "{}{}{}".format(window_icon_path, os.pathsep, ".")

        args = [
            os.path.join(HERE, "launcher.py"),
            "--name=l4d2-server-browser",
            "--onefile",
            "--windowed",
            "--add-data={}".format(add_data),
            "--add-data={}".format(add_version),
            "--add-data={}".format(add_window_icon),
            "--noconfirm",
        ]
        if native_icon_path:
            args.append("--icon={}".format(native_icon_path))

        PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
