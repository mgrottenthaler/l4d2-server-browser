from steam_browser import steam_api


def test_build_filter_base_fields_only():
    assert steam_api.build_filter(550, "left4dead2") == "\\appid\\550\\gamedir\\left4dead2"


def test_build_filter_includes_name_match_when_given():
    result = steam_api.build_filter(550, "left4dead2", name_filter="coop")
    assert result == "\\appid\\550\\gamedir\\left4dead2\\name_match\\*coop*"


def test_build_filter_not_empty_and_not_full_flags():
    result = steam_api.build_filter(550, "left4dead2", not_empty=True, not_full=True)
    assert result == "\\appid\\550\\gamedir\\left4dead2\\empty\\1\\full\\1"


def test_build_filter_combines_all_options_in_order():
    result = steam_api.build_filter(
        550, "left4dead2", name_filter="my server", not_empty=True, not_full=True
    )
    assert result == (
        "\\appid\\550\\gamedir\\left4dead2"
        "\\name_match\\*my server*"
        "\\empty\\1\\full\\1"
    )


def test_build_filter_omits_empty_name_filter():
    result = steam_api.build_filter(550, "left4dead2", name_filter="")
    assert "name_match" not in result


def test_fetch_servers_returns_server_list(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": {"servers": [{"addr": "1.2.3.4:27015"}]}}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(steam_api.requests, "get", fake_get)

    servers = steam_api.fetch_servers("api-key", 550, "left4dead2", 100)

    assert servers == [{"addr": "1.2.3.4:27015"}]
    assert captured["url"] == steam_api.GET_SERVER_LIST_URL
    assert captured["params"]["key"] == "api-key"
    assert captured["params"]["limit"] == 100


def test_fetch_servers_defaults_to_empty_list_when_response_missing_servers(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": {}}

    monkeypatch.setattr(steam_api.requests, "get", lambda *a, **kw: FakeResponse())

    assert steam_api.fetch_servers("api-key", 550, "left4dead2", 100) == []
