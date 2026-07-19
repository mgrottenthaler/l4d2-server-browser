"""Web interface: fetches and probes the full candidate server list in the
background, and serves it as JSON for a browser-side UI that filters and
sorts instantly without re-querying (same behaviour as the Steam client's
own server browser).
"""

import argparse
import inspect
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, Response, jsonify, request, send_from_directory

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
_cancel_event = threading.Event()


def _fetch_all(cfg, api_key, not_empty, not_full, cancel_event):
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
            if cancel_event.is_set():
                # Drop futures that haven't started yet; ones already running
                # are still bounded by query_timeout_s so this returns quickly.
                for f in futures:
                    f.cancel()
                break

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
    _cancel_event.clear()

    try:
        _fetch_all(cfg, api_key, not_empty, not_full, _cancel_event)
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
    """Snapshot of the current server list and background-refresh status.
    Call this on a ~1.5s interval while status == "refreshing"; stop
    polling once it flips to "idle" or "error".

    200 response JSON:
        {
          "servers": [server, ...],   # sorted by latency_ms ascending
          "status": "idle" | "refreshing" | "error",
          "error": string | null,     # set when status == "error"
          "last_updated": number | null,  # unix timestamp of last completed refresh
          "candidate_count": integer  # dedicated servers returned by the master list this refresh
        }

    Each `server` object:
        {
          "host": string, "port": integer,
          "name": string, "map": string,
          "campaign": string, "stage": string,   # "-" if map isn't a known L4D2 campaign map
          "players": integer, "max_players": integer, "bots": integer,
          "protocol": integer, "folder": string, "game": string,
          "latency_ms": number,
          "password_protected": boolean, "secure": boolean,
          "mode": string,   # e.g. "Campaign", "Versus", "Team Scavenge (Realism)"
          "country_code": string, "country_name": string  # "" if geoip lookup failed
        }
    """
    with _state_lock:
        # Copy + sort under the lock: _fetch_all appends to this same list
        # from a background thread while a refresh is in progress, and
        # jsonify()-ing a list that's mutating concurrently can blow up.
        payload = dict(_state)
        payload["servers"] = sorted(_state["servers"], key=lambda r: r["latency_ms"])
        return jsonify(payload)


@app.route("/api/servers/<host>/<int:port>/players")
def api_server_players(host, port):
    """Synchronous, on-demand A2S_PLAYER query against one server - not part
    of the background refresh, run only when a user opens that server's
    sidebar (querying every server on every poll would multiply outbound
    UDP traffic for data nobody's looking at).

    200 response JSON:
        {"players": [{"name": string, "score": integer, "duration": number}, ...]}
        # duration is seconds connected to the server

    502 response JSON (server didn't respond or sent a malformed reply):
        {"error": string}
    """
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
    """Synchronous, on-demand A2S_RULES query against one server - same
    sidebar-only pattern as .../players.

    200 response JSON:
        {"rules": [{"name": string, "value": string}, ...]}
        # the server's sv_* cvars as advertised to clients, admin-controlled

    502 response JSON (server didn't respond, doesn't support A2S_RULES,
    or sent a malformed reply):
        {"error": string}
    """
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
    """Start a background refresh: re-fetch the master server list and
    re-probe every candidate over A2S. Returns immediately - poll
    GET /api/servers for progress. No-op (just returns the current status)
    if a refresh is already running.

    Request JSON body (all fields optional):
        {"not_empty": boolean, "not_full": boolean}
        # the only two filters Valve's master list honors server-side,
        # see steam_api.build_filter

    200 response JSON:
        {"status": "idle" | "refreshing"}
    """
    api_key = app.config["STEAM_BROWSER_API_KEY"]
    body = request.get_json(silent=True) or {}
    not_empty = bool(body.get("not_empty"))
    not_full = bool(body.get("not_full"))
    threading.Thread(target=_refresh, args=(DEFAULT_CONFIG, api_key, not_empty, not_full), daemon=True).start()
    with _state_lock:
        return jsonify({"status": _state["status"]})


@app.route("/api/refresh/stop", methods=["POST"])
def api_refresh_stop():
    """Cancel an in-progress refresh. Servers already probed are kept in the
    result set; probes that hadn't started yet are dropped. No-op if no
    refresh is running.

    200 response JSON:
        {"status": "idle" | "refreshing"}
    """
    # Leaves whatever servers were already probed in place; _fetch_all just
    # stops appending more and flips status back to idle on its own.
    _cancel_event.set()
    with _state_lock:
        return jsonify({"status": _state["status"]})


@app.route("/api/docs")
def api_docs():
    """Human-readable listing of every /api/* route, generated at request
    time from the docstrings on the view functions above - always in sync
    with the code since it reads directly from source rather than a
    checked-in file. Disabled unless the server was started with --dev,
    since it's a developer convenience, not something to expose publicly.

    200 response: text/plain listing.
    404 response: dev mode isn't enabled.
    """
    if not app.config.get("DEV_MODE"):
        return jsonify({"error": "not found"}), 404

    lines = ["L4D2 Server Browser API", "=" * 24, ""]
    rules = sorted(
        (r for r in app.url_map.iter_rules() if r.rule.startswith("/api/") and r.rule != "/api/docs"),
        key=lambda r: r.rule,
    )
    for rule in rules:
        methods = sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
        view_func = app.view_functions[rule.endpoint]
        doc = inspect.getdoc(view_func) or "(undocumented)"
        lines.append("{} {}".format(" & ".join(methods), rule.rule))
        lines.append("")
        lines.extend(("    " + line if line else "") for line in doc.splitlines())
        lines.append("")
    return Response("\n".join(lines), mimetype="text/plain")


def create_app():
    app.config["STEAM_BROWSER_API_KEY"] = get_steam_api_key(PROJECT_ROOT)
    return app


def main():
    parser = argparse.ArgumentParser(description="Left 4 Dead 2 web server browser")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000)")
    parser.add_argument(
        "--dev", action="store_true",
        help="Enable developer-only endpoints (currently: GET /api/docs)",
    )
    args = parser.parse_args()

    application = create_app()
    application.config["DEV_MODE"] = args.dev
    application.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
