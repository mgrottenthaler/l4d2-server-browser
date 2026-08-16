#!/usr/bin/env python3
"""Desktop-style entry point: starts the server and opens a browser tab to
it, for the PyInstaller-built single-file executable. This is an alternate
launch mechanism only - `python3 webserver.py` still works unchanged and
doesn't import this module.
"""
import socket
import sys
import threading
import time
import webbrowser


def _set_windows_console_branding():
    """Best-effort cosmetic touch for the console window Windows opens on
    double-click: classic conhost windows don't automatically pick up the
    icon build_executable.py bakes into the exe via --icon (that only
    guarantees Explorer/taskbar-pinning show the right icon for the file
    itself), so set it explicitly and give the window a real title instead
    of the raw exe path. No-ops silently if any Win32 call fails - Windows
    Terminal in particular renders its own tab/taskbar icon and ignores
    this entirely, which is a Windows-side limitation, not fixable here.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32

        kernel32.SetConsoleTitleW("L4D2 Server Browser")

        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        large = ctypes.c_void_p()
        small = ctypes.c_void_p()
        shell32.ExtractIconExW(sys.executable, 0, ctypes.byref(large), ctypes.byref(small), 1)
        WM_SETICON = 0x0080
        if large.value:
            user32.SendMessageW(hwnd, WM_SETICON, 1, large.value)
        if small.value:
            user32.SendMessageW(hwnd, WM_SETICON, 0, small.value)
    except (OSError, AttributeError):
        pass


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


def main():
    _set_windows_console_branding()

    from steam_browser.web import create_app

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
    print("Serving on {}".format(url), flush=True)
    if _wait_until_listening(host, port):
        webbrowser.open(url)
    else:
        print("Server didn't come up in time - open {} manually.".format(url))

    try:
        while server_thread.is_alive():
            server_thread.join(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
