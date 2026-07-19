"""Web interface: fetches and probes the full candidate server list in the
background, and serves it as JSON for a browser-side UI that filters and
sorts instantly without re-querying (same behaviour as the Steam client's
own server browser).
"""

import argparse
import inspect
import ipaddress
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from steam_browser import a2s
from steam_browser import geoip
from steam_browser.config import DEFAULT_CONFIG, get_steam_api_key
from steam_browser import steam_api
from steam_browser.browser import probe_server

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Bounds request volume on the on-demand probe routes below: sized to absorb
# one sidebar click (players + info + rules fire together, see app.js's row
# click handler) plus fast browsing, while still capping a script hammering
# these endpoints - each one makes this server send UDP packets to a
# caller-chosen address, so unlike /api/servers this is abusable regardless
# of the master-list data behind it.
PROBE_RATE_LIMIT = "10/second;150/minute"
# A real favorites list is never more than a few dozen servers; this just
# stops a single request from fanning out an unbounded number of probes.
MAX_FAVORITES_PROBE_BATCH = 200
# A human clicks Refresh (or toggles the not_empty/not_full checkboxes,
# which also trigger one) a handful of times a minute at most. The refresh
# itself is deduplicated by the status guard in api_refresh, so this only
# caps the cost of the requests themselves - thread spawns and master-list
# refresh cycles an anonymous caller could otherwise keep perpetually hot.
REFRESH_RATE_LIMIT = "3/second;30/minute"

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
# In-memory storage is correct here, not just a default left unconfigured:
# this app is single-process (one daemon thread does the background refresh,
# no multi-worker deployment model), so there's no other process a shared
# store would need to coordinate with.
limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")

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
    # Build fresh dicts rather than mutating r in place: these are still the
    # same objects sitting in _state["servers"], which a concurrent
    # GET /api/servers reads under _state_lock - mutating them here without
    # the lock would violate that contract.
    enriched = []
    for r in results:
        code, name = countries.get(r["host"], ("", ""))
        enriched.append(dict(r, country_code=code, country_name=name))

    with _state_lock:
        _state["servers"] = enriched


def _resolve_probeable_host(host):
    """Resolve a probe target and return its IP as a string, or None if it
    isn't a public address. The on-demand probe routes below send a UDP
    packet to whatever host:port a caller supplies, so two properties matter:
    only globally routable addresses are allowed (not localhost, internal
    networks, CGNAT, etc. - real L4D2 servers live on the public internet),
    and callers must probe the *returned* IP, not the original name.
    Re-resolving at send time would let a DNS name pass this check with one
    (public) answer and deliver the actual packet somewhere else entirely
    (DNS rebinding).
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            addr = ipaddress.ip_address(socket.gethostbyname(host))
        except (socket.gaierror, ValueError):
            return None
    return str(addr) if addr.is_global else None


def _refresh(cfg, api_key, not_empty, not_full):
    """Background-thread body of a refresh. api_refresh has already flipped
    status to "refreshing" (synchronously, so its own response and any
    immediately-following poll observe it) and cleared the cancel event;
    this just does the work and records the outcome.
    """
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
@limiter.limit(PROBE_RATE_LIMIT)
def api_server_players(host, port):
    """Synchronous, on-demand A2S_PLAYER query against one server - not part
    of the background refresh, run only when a user opens that server's
    sidebar (querying every server on every poll would multiply outbound
    UDP traffic for data nobody's looking at).

    200 response JSON:
        {"players": [{"name": string, "score": integer, "duration": number}, ...]}
        # duration is seconds connected to the server

    400 response JSON (host doesn't resolve to a public address):
        {"error": string}

    502 response JSON (server didn't respond or sent a malformed reply):
        {"error": string}
    """
    # Live per-server query, run only when a user opens that server's
    # sidebar - querying A2S_PLAYER for every server on every poll would
    # multiply outbound UDP traffic by the whole server list for data
    # nobody's looking at.
    ip = _resolve_probeable_host(host)
    if ip is None:
        return jsonify({"error": "host not allowed"}), 400
    timeout = DEFAULT_CONFIG["query_timeout_s"]
    try:
        players = a2s.query_players(ip, port, timeout=timeout)
        return jsonify({"players": players})
    except a2s.QueryError as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/servers/<host>/<int:port>/rules")
@limiter.limit(PROBE_RATE_LIMIT)
def api_server_rules(host, port):
    """Synchronous, on-demand A2S_RULES query against one server - same
    sidebar-only pattern as .../players.

    200 response JSON:
        {"rules": [{"name": string, "value": string}, ...]}
        # the server's sv_* cvars as advertised to clients, admin-controlled

    400 response JSON (host doesn't resolve to a public address):
        {"error": string}

    502 response JSON (server didn't respond, doesn't support A2S_RULES,
    or sent a malformed reply):
        {"error": string}
    """
    # Same on-demand, sidebar-only pattern as /players - rules can be a
    # sizeable cvar dump and most users never expand the section.
    ip = _resolve_probeable_host(host)
    if ip is None:
        return jsonify({"error": "host not allowed"}), 400
    timeout = DEFAULT_CONFIG["query_timeout_s"]
    try:
        rules = a2s.query_rules(ip, port, timeout=timeout)
        return jsonify({"rules": rules})
    except a2s.QueryError as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/servers/<host>/<int:port>/info")
@limiter.limit(PROBE_RATE_LIMIT)
def api_server_info(host, port):
    """Synchronous, on-demand A2S_INFO query against one server - same
    sidebar-only pattern as .../players and .../rules. Lets the sidebar
    refresh map/mode/name/player-count etc. with a live reading instead of
    the possibly-stale values from the last full /api/refresh.

    200 response JSON: a server object, same shape as GET /api/servers's
    entries (see that route's docstring), plus "country_code"/"country_name"
    filled in via geoip.

    400 response JSON (host doesn't resolve to a public address):
        {"error": string}

    502 response JSON (server didn't respond or sent a malformed reply):
        {"error": string}
    """
    ip = _resolve_probeable_host(host)
    if ip is None:
        return jsonify({"error": "host not allowed"}), 400
    timeout = DEFAULT_CONFIG["query_timeout_s"]
    result = probe_server({"addr": "{}:{}".format(ip, port)}, timeout)
    if result is None:
        return jsonify({"error": "no response"}), 502
    code, name = geoip.lookup_countries({ip}).get(ip, ("", ""))
    # Report the host the caller asked about, not the resolved IP - the
    # frontend matches this response back to its table row by host:port.
    result["host"] = host
    result["country_code"] = code
    result["country_name"] = name
    return jsonify(result)


@app.route("/api/favorites/probe", methods=["POST"])
@limiter.limit(PROBE_RATE_LIMIT)
def api_favorites_probe():
    """Directly probe a specific set of servers over A2S_INFO, independent of
    the master-list-driven background refresh. Used by the Favorites tab so
    a favorited server still shows - as online or offline - even if it
    wasn't in the last /api/refresh result (empty/full filters excluded it,
    it's a listen server, or a refresh just hasn't run yet this session).

    Request JSON body:
        {"servers": ["host:port", ...]}   # max 200 entries

    200 response JSON:
        {"servers": [server, ...]}
        # same shape as GET /api/servers's server objects, each with an
        # added "online" boolean. Entries for servers that didn't respond
        # or don't resolve to a public address only carry
        # {"host", "port", "online": false}.

    413 response JSON (more than 200 servers in one request):
        {"error": string}
    """
    body = request.get_json(silent=True) or {}
    addrs = [a for a in (body.get("servers") or []) if isinstance(a, str)]
    if not addrs:
        return jsonify({"servers": []})
    if len(addrs) > MAX_FAVORITES_PROBE_BATCH:
        return jsonify({"error": "too many servers (max {})".format(MAX_FAVORITES_PROBE_BATCH)}), 413

    timeout = DEFAULT_CONFIG["query_timeout_s"]

    def probe(addr):
        try:
            host, port_str = addr.rsplit(":", 1)
            port = int(port_str)
        except ValueError:
            return None
        ip = _resolve_probeable_host(host)
        if ip is None:
            return {"host": host, "port": port, "online": False}
        result = probe_server({"addr": "{}:{}".format(ip, port)}, timeout)
        if result is None:
            return {"host": host, "port": port, "online": False}
        # Key the result by the address the caller asked about, not the
        # resolved IP - the frontend matches it back to a favorite by
        # host:port.
        result["host"] = host
        result["online"] = True
        return result

    with ThreadPoolExecutor(max_workers=min(50, len(addrs))) as executor:
        results = [r for r in executor.map(probe, addrs) if r is not None]

    online_hosts = {r["host"] for r in results if r["online"]}
    countries = geoip.lookup_countries(online_hosts)
    for r in results:
        if r["online"]:
            code, name = countries.get(r["host"], ("", ""))
            r["country_code"] = code
            r["country_name"] = name

    return jsonify({"servers": results})


@app.route("/api/refresh", methods=["POST"])
@limiter.limit(REFRESH_RATE_LIMIT)
def api_refresh():
    """Start a background refresh: re-fetch the master server list and
    re-probe every candidate over A2S. Returns immediately - poll
    GET /api/servers for progress. No-op if a refresh is already running.

    Request JSON body (all fields optional):
        {"not_empty": boolean, "not_full": boolean}
        # the only two filters Valve's master list honors server-side,
        # see steam_api.build_filter

    200 response JSON:
        {"status": "refreshing"}
    """
    api_key = app.config["STEAM_BROWSER_API_KEY"]
    body = request.get_json(silent=True) or {}
    not_empty = bool(body.get("not_empty"))
    not_full = bool(body.get("not_full"))
    with _state_lock:
        if _state["status"] == "refreshing":
            return jsonify({"status": "refreshing"})
        # Flip status here, synchronously, rather than inside the thread:
        # the frontend only starts polling when it observes "refreshing", so
        # a response (or an immediate GET /api/servers) racing the thread's
        # first instructions could otherwise see "idle" and never poll.
        _state["status"] = "refreshing"
        _state["error"] = None
    _cancel_event.clear()
    threading.Thread(target=_refresh, args=(DEFAULT_CONFIG, api_key, not_empty, not_full), daemon=True).start()
    return jsonify({"status": "refreshing"})


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
        help="Enable developer-only endpoints (currently: GET /api/docs) and serve "
             "via Flask's own dev server instead of waitress",
    )
    args = parser.parse_args()

    application = create_app()
    application.config["DEV_MODE"] = args.dev

    # Flask's dev server announces its listen address itself; waitress only
    # logs it to a logger nothing configures, so print it in both cases.
    # flush: under a pipe/log redirect stdout is block-buffered, and serve()
    # below never returns to flush it.
    print("Serving on http://{}:{}".format(args.host, args.port), flush=True)
    if args.dev:
        application.run(host=args.host, port=args.port)
    else:
        # Flask's built-in server isn't meant to take real request volume -
        # waitress is a pure-Python WSGI server with no compiled deps, so it
        # doesn't cost anything beyond requirements.txt to use it by default.
        from waitress import serve
        serve(application, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
