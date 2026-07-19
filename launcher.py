#!/usr/bin/env python3
"""Desktop-style entry point: starts the server and opens a browser tab to
it, for the PyInstaller-built single-file executable. This is an alternate
launch mechanism only - `python3 webserver.py` still works unchanged and
doesn't import this module.
"""
import os
import socket
import sys
import threading
import time
import webbrowser


def _ensure_api_key(project_root):
    from steam_browser.config import load_env

    env_path = os.path.join(project_root, ".env")
    env = load_env(env_path)
    if env.get("STEAM-API-KEY") or env.get("STEAM_API_KEY") or os.environ.get("STEAM_API_KEY"):
        return

    print("No Steam Web API key found.")
    print("Get one at https://steamcommunity.com/dev/apikey")
    key = input("Enter your Steam Web API key: ").strip()
    if not key:
        print("No key entered, exiting.")
        sys.exit(1)
    with open(env_path, "a") as f:
        f.write("STEAM-API-KEY={}\n".format(key))


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
    from steam_browser.web import PROJECT_ROOT, create_app

    _ensure_api_key(PROJECT_ROOT)

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
