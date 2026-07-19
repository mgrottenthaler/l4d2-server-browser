#!/usr/bin/env python3
"""Desktop-style entry point: starts the server and opens a browser tab to
it, for the PyInstaller-built single-file executable. This is an alternate
launch mechanism only - `python3 webserver.py` still works unchanged and
doesn't import this module.
"""
import socket
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


def main():
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
