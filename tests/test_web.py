import time

from steam_browser import a2s
from steam_browser import web as web_module


def _wait_until_not_refreshing(timeout=2.0):
    """api_refresh spawns a real daemon thread, so tests need to wait for it
    to finish rather than reading _state immediately. Everything the thread
    calls is monkeypatched to pure in-memory functions, so this settles in
    well under the timeout - it's just a bounded wait for the OS to schedule
    that thread, not a fixed sleep.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        with web_module._state_lock:
            if web_module._state["status"] != "refreshing":
                return
        time.sleep(0.01)
    raise AssertionError("refresh thread did not finish within {}s".format(timeout))


def _fake_server_entry():
    return {
        "host": "1.2.3.4",
        "port": 27015,
        "name": "Test Server",
        "map": "c1m1_hotel",
        "campaign": "Dead Center",
        "stage": "1/4 Hotel",
        "players": 1,
        "max_players": 8,
        "bots": 0,
        "protocol": 17,
        "folder": "left4dead2",
        "game": "Left 4 Dead 2",
        "latency_ms": 10.0,
        "password_protected": False,
        "secure": True,
        "mode": "Campaign",
    }


# ---------------------------------------------------------------------------
# GET /api/servers
# ---------------------------------------------------------------------------

def test_api_servers_initial_state_is_idle_and_empty(client):
    resp = client.get("/api/servers")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "idle"
    assert body["servers"] == []
    assert body["candidate_count"] == 0


def test_api_servers_sorts_by_latency(client):
    with web_module._state_lock:
        web_module._state["servers"] = [
            dict(_fake_server_entry(), host="slow", latency_ms=50.0),
            dict(_fake_server_entry(), host="fast", latency_ms=5.0),
        ]

    body = client.get("/api/servers").get_json()
    assert [s["host"] for s in body["servers"]] == ["fast", "slow"]


# ---------------------------------------------------------------------------
# GET /api/servers/<host>/<port>/players and /rules
# ---------------------------------------------------------------------------

def test_api_server_players_success(client, monkeypatch):
    monkeypatch.setattr(
        a2s, "query_players", lambda host, port, timeout: [{"name": "Alice", "score": 3, "duration": 120.0}]
    )
    resp = client.get("/api/servers/1.2.3.4/27015/players")
    assert resp.status_code == 200
    assert resp.get_json() == {"players": [{"name": "Alice", "score": 3, "duration": 120.0}]}


def test_api_server_players_query_error_returns_502(client, monkeypatch):
    def raise_error(host, port, timeout):
        raise a2s.QueryError("timed out")

    monkeypatch.setattr(a2s, "query_players", raise_error)
    resp = client.get("/api/servers/1.2.3.4/27015/players")
    assert resp.status_code == 502
    assert "error" in resp.get_json()


def test_api_server_rules_success(client, monkeypatch):
    monkeypatch.setattr(
        a2s, "query_rules", lambda host, port, timeout: [{"name": "sv_gametypes", "value": "coop"}]
    )
    resp = client.get("/api/servers/1.2.3.4/27015/rules")
    assert resp.status_code == 200
    assert resp.get_json() == {"rules": [{"name": "sv_gametypes", "value": "coop"}]}


def test_api_server_rules_query_error_returns_502(client, monkeypatch):
    def raise_error(host, port, timeout):
        raise a2s.QueryError("no response")

    monkeypatch.setattr(a2s, "query_rules", raise_error)
    resp = client.get("/api/servers/1.2.3.4/27015/rules")
    assert resp.status_code == 502
    assert "error" in resp.get_json()


# ---------------------------------------------------------------------------
# POST /api/refresh and /api/refresh/stop
# ---------------------------------------------------------------------------

def test_api_refresh_populates_servers_and_returns_to_idle(client, monkeypatch):
    monkeypatch.setattr(
        web_module.steam_api, "fetch_servers",
        lambda api_key, appid, gamedir, limit, not_empty=False, not_full=False: [
            {"addr": "1.2.3.4:27015", "dedicated": True, "gametype": "coop", "secure": True}
        ],
    )
    monkeypatch.setattr(web_module, "probe_server", lambda server, timeout: _fake_server_entry())
    monkeypatch.setattr(web_module.geoip, "lookup_countries", lambda ips: {})

    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    # Whether the spawned thread has flipped status to "refreshing" by the
    # time this handler reads it is a genuine race (see _refresh) - only
    # the eventual settled state is worth asserting on.
    assert resp.get_json()["status"] in ("idle", "refreshing")

    _wait_until_not_refreshing()

    body = client.get("/api/servers").get_json()
    assert body["status"] == "idle"
    assert body["candidate_count"] == 1
    assert len(body["servers"]) == 1
    assert body["servers"][0]["host"] == "1.2.3.4"
    assert body["last_updated"] is not None


def test_api_refresh_sets_error_status_on_exception(client, monkeypatch):
    def raise_error(*a, **kw):
        raise RuntimeError("master list unreachable")

    monkeypatch.setattr(web_module.steam_api, "fetch_servers", raise_error)

    client.post("/api/refresh")
    _wait_until_not_refreshing()

    body = client.get("/api/servers").get_json()
    assert body["status"] == "error"
    assert "master list unreachable" in body["error"]


def test_api_refresh_is_a_noop_while_already_refreshing(client):
    with web_module._state_lock:
        web_module._state["status"] = "refreshing"

    resp = client.post("/api/refresh")
    assert resp.get_json()["status"] == "refreshing"


def test_api_refresh_stop_sets_cancel_event(client):
    assert not web_module._cancel_event.is_set()
    resp = client.post("/api/refresh/stop")
    assert resp.status_code == 200
    assert web_module._cancel_event.is_set()


# ---------------------------------------------------------------------------
# POST /api/favorites/probe
# ---------------------------------------------------------------------------

def test_api_favorites_probe_returns_online_and_offline_servers(client, monkeypatch):
    def fake_probe_server(server, timeout):
        if server["addr"] == "1.2.3.4:27015":
            return _fake_server_entry()
        return None  # offline / no response

    monkeypatch.setattr(web_module, "probe_server", fake_probe_server)
    monkeypatch.setattr(web_module.geoip, "lookup_countries", lambda ips: {})

    resp = client.post(
        "/api/favorites/probe",
        json={"servers": ["1.2.3.4:27015", "5.6.7.8:27015"]},
    )
    assert resp.status_code == 200
    servers = {s["host"]: s for s in resp.get_json()["servers"]}

    assert servers["1.2.3.4"]["online"] is True
    assert servers["1.2.3.4"]["name"] == "Test Server"

    assert servers["5.6.7.8"] == {"host": "5.6.7.8", "port": 27015, "online": False}


def test_api_favorites_probe_empty_servers_list_returns_empty(client):
    resp = client.post("/api/favorites/probe", json={"servers": []})
    assert resp.status_code == 200
    assert resp.get_json() == {"servers": []}


def test_api_favorites_probe_missing_body_returns_empty(client):
    resp = client.post("/api/favorites/probe")
    assert resp.status_code == 200
    assert resp.get_json() == {"servers": []}


def test_api_favorites_probe_skips_malformed_addr(client, monkeypatch):
    monkeypatch.setattr(web_module, "probe_server", lambda server, timeout: _fake_server_entry())
    monkeypatch.setattr(web_module.geoip, "lookup_countries", lambda ips: {})

    resp = client.post("/api/favorites/probe", json={"servers": ["not-a-valid-addr"]})
    assert resp.status_code == 200
    assert resp.get_json() == {"servers": []}


# ---------------------------------------------------------------------------
# GET /api/docs - dev-mode gated
# ---------------------------------------------------------------------------

def test_api_docs_returns_404_when_dev_mode_disabled(client):
    web_module.app.config["DEV_MODE"] = False
    resp = client.get("/api/docs")
    assert resp.status_code == 404


def test_api_docs_lists_routes_with_their_docstrings_when_dev_mode_enabled(client):
    web_module.app.config["DEV_MODE"] = True
    try:
        resp = client.get("/api/docs")
        assert resp.status_code == 200
        assert resp.mimetype == "text/plain"
        text = resp.get_data(as_text=True)
        assert "GET /api/servers" in text
        assert "POST /api/refresh" in text
        assert "/api/docs" not in text  # doesn't list itself
    finally:
        web_module.app.config["DEV_MODE"] = False
