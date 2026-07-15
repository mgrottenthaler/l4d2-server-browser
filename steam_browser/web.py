"""Web interface: fetches and probes the full candidate server list in the
background, and serves it as JSON for a browser-side UI that filters and
sorts instantly without re-querying (same behaviour as the Steam client's
own server browser).
"""

import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, jsonify, request, send_from_directory

from steam_browser import a2s
from steam_browser import geoip
from steam_browser.config import DEFAULT_CONFIG, get_steam_api_key
from steam_browser import steam_api
from steam_browser.browser import probe_server

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

_state_lock = threading.Lock()
_state = {
    "servers": [],
    "status": "idle",  # idle | refreshing | error
    "error": None,
    "last_updated": None,
    "candidate_count": 0,
}


def _fetch_all(cfg, api_key, not_empty, not_full):
    """Fetch every candidate server from the master list (up to
    max_servers_to_query) and probe them, publishing each result to _state
    as soon as it comes in rather than waiting for the whole batch - probing
    thousands of servers can take a while, and the UI polls _state so it can
    render results as they trickle in instead of showing nothing until the
    very end.
    """
    query_limit = cfg.get("max_servers_to_query", 10000)
    servers = steam_api.fetch_servers(
        api_key, cfg["appid"], cfg["gamedir"], query_limit,
        not_empty=not_empty, not_full=not_full,
    )
    # Only dedicated servers are worth showing (listen-server hosts come and
    # go with their owner's game session); secure/insecure is left to the
    # UI's Anti-cheat filter rather than excluded before probing.
    servers = [s for s in servers if s.get("dedicated")]

    with _state_lock:
        _state["servers"] = []
        _state["candidate_count"] = len(servers)

    with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
        futures = [executor.submit(probe_server, s, cfg["query_timeout_s"]) for s in servers]
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                with _state_lock:
                    _state["servers"].append(result)

    with _state_lock:
        results = list(_state["servers"])

    countries = geoip.lookup_countries({r["host"] for r in results})
    for r in results:
        code, name = countries.get(r["host"], ("", ""))
        r["country_code"] = code
        r["country_name"] = name

    with _state_lock:
        _state["servers"] = results


def _refresh(cfg, api_key, not_empty, not_full):
    with _state_lock:
        if _state["status"] == "refreshing":
            return
        _state["status"] = "refreshing"
        _state["error"] = None

    try:
        _fetch_all(cfg, api_key, not_empty, not_full)
        with _state_lock:
            _state["last_updated"] = time.time()
            _state["status"] = "idle"
    except Exception as e:
        with _state_lock:
            _state["status"] = "error"
            _state["error"] = str(e)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/servers")
def api_servers():
    with _state_lock:
        # Copy + sort under the lock: _fetch_all appends to this same list
        # from a background thread while a refresh is in progress, and
        # jsonify()-ing a list that's mutating concurrently can blow up.
        payload = dict(_state)
        payload["servers"] = sorted(_state["servers"], key=lambda r: r["latency_ms"])
        return jsonify(payload)


@app.route("/api/servers/<host>/<int:port>/players")
def api_server_players(host, port):
    # Live per-server query, run only when a user opens that server's
    # sidebar - querying A2S_PLAYER for every server on every poll would
    # multiply outbound UDP traffic by the whole server list for data
    # nobody's looking at.
    timeout = DEFAULT_CONFIG["query_timeout_s"]
    try:
        players = a2s.query_players(host, port, timeout=timeout)
        return jsonify({"players": players})
    except a2s.QueryError as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/servers/<host>/<int:port>/rules")
def api_server_rules(host, port):
    # Same on-demand, sidebar-only pattern as /players - rules can be a
    # sizeable cvar dump and most users never expand the section.
    timeout = DEFAULT_CONFIG["query_timeout_s"]
    try:
        rules = a2s.query_rules(host, port, timeout=timeout)
        return jsonify({"rules": rules})
    except a2s.QueryError as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    api_key = app.config["STEAM_BROWSER_API_KEY"]
    body = request.get_json(silent=True) or {}
    not_empty = bool(body.get("not_empty"))
    not_full = bool(body.get("not_full"))
    threading.Thread(target=_refresh, args=(DEFAULT_CONFIG, api_key, not_empty, not_full), daemon=True).start()
    with _state_lock:
        return jsonify({"status": _state["status"]})


def create_app():
    app.config["STEAM_BROWSER_API_KEY"] = get_steam_api_key(PROJECT_ROOT)
    return app


def main():
    parser = argparse.ArgumentParser(description="Left 4 Dead 2 web server browser")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000)")
    args = parser.parse_args()

    application = create_app()
    application.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
