#!/usr/bin/env python3
"""Desktop-style entry point: starts the server and opens a browser tab to
it, for the PyInstaller-built single-file executable. This is an alternate
launch mechanism only - `python3 webserver.py` still works unchanged and
doesn't import this module.

Built with PyInstaller's --windowed (see build_executable.py), so there's no
console at all. _LogWindow stands in for one: a small Tk window with our own
icon and title, regardless of whichever terminal host the OS would otherwise
pick - notably Windows Terminal, which (when set as the Windows default)
hosts console apps in its own window and ignores the launched exe's icon and
window title entirely, which is why a real console here can't be branded
from inside the app.
"""
import logging
import os
import queue
import socket
import sys
import threading
import time
import webbrowser


def _free_port(host, preferred):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, preferred))
    except OSError:
        s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_until_listening(host, port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _window_icon_path():
    # Bundled by build_executable.py (--add-data) as window_icon.png at the
    # onefile archive root, same convention as VERSION - see version.py.
    # Not present when running unfrozen (`python3 launcher.py` directly);
    # that's not an officially supported entry point (see module docstring),
    # so just skip the icon rather than rasterizing the SVG at runtime too.
    if not getattr(sys, "frozen", False):
        return None
    candidate = os.path.join(sys._MEIPASS, "window_icon.png")
    return candidate if os.path.exists(candidate) else None


class _LogWindow:
    """Stands in for the console window a normal PyInstaller build would
    open: our own small Tk window with the app logo, a scrolling log pane
    mirroring stdout/stderr, and closing it exits the process - the server
    thread is a daemon, so nothing keeps the process alive once Tk's
    mainloop returns.

    Writes arrive via a Queue rather than touching the Text widget directly:
    Tk is only safe to touch from its own mainloop thread, but the redirected
    stdout/stderr get written to from the waitress server thread too.
    """

    def __init__(self, title):
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText

        self._tk = tk
        self._queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("640x360")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        icon_path = _window_icon_path()
        if icon_path:
            self._icon_image = tk.PhotoImage(file=icon_path)
            self.root.iconphoto(True, self._icon_image)

        header = tk.Frame(self.root)
        header.pack(fill=tk.X, padx=8, pady=(8, 0))
        if icon_path:
            self._header_icon = self._icon_image.subsample(4, 4)
            tk.Label(header, image=self._header_icon).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(header, text=title, font=("TkDefaultFont", 12, "bold")).pack(side=tk.LEFT)

        self.text = ScrolledText(self.root, state="disabled", wrap="word")
        self.text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.root.after(50, self._drain_queue)

    def _on_close(self):
        self.root.destroy()

    def _drain_queue(self):
        try:
            while True:
                chunk = self._queue.get_nowait()
                self.text.configure(state="normal")
                self.text.insert("end", chunk)
                self.text.see("end")
                self.text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(50, self._drain_queue)

    def write(self, chunk):
        if chunk:
            self._queue.put(chunk)

    def flush(self):
        pass

    def mainloop(self):
        self.root.mainloop()


def main():
    log_window = _LogWindow("L4D2 Server Browser")
    sys.stdout = log_window
    sys.stderr = log_window

    # Importing this configures logging (steam_browser.logging_setup, called
    # from web.py at module load) to write to CONFIG_DIR *and* to
    # sys.stderr - which by now points at log_window above, so log output
    # ends up in both the persisted log file and this window.
    from steam_browser.web import create_app

    logger = logging.getLogger(__name__)

    # No API-key preflight here: create_app() starts regardless, and the UI
    # itself shows a setup banner (POST /api/setup/key) when one isn't
    # configured yet - see web.py's _config_dir()/api_setup_key.
    application = create_app()

    host = "127.0.0.1"
    port = _free_port(host, 5000)

    from waitress import serve

    server_thread = threading.Thread(
        target=serve, args=(application,), kwargs={"host": host, "port": port}, daemon=True
    )
    server_thread.start()

    url = "http://{}:{}".format(host, port)
    logger.info("Serving on %s", url)

    def _open_browser_when_ready():
        if _wait_until_listening(host, port):
            webbrowser.open(url)
        else:
            logger.warning("Server didn't come up in time - open %s manually.", url)

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    log_window.mainloop()


if __name__ == "__main__":
    main()
