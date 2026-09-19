import pytest
import requests

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


def test_fetch_servers_redacts_the_api_key_from_request_failures(monkeypatch):
    """requests puts the whole request URL - `key` query parameter included -
    in the message of a connect timeout, and web.py shows that message in the
    UI's error banner and writes it to the log file verbatim.
    """
    secret = "0123456789ABCDEF0123456789ABCDEF"

    def fake_get(url, params, timeout):
        raise requests.ConnectTimeout(
            "HTTPSConnectionPool(host='api.steampowered.com', port=443): Max retries "
            "exceeded with url: /IGameServersService/GetServerList/v1/?key={}"
            "&filter=x (Caused by ConnectTimeoutError(...))".format(secret)
        )

    monkeypatch.setattr(steam_api.requests, "get", fake_get)

    with pytest.raises(steam_api.SteamApiError) as excinfo:
        steam_api.fetch_servers(secret, 550, "left4dead2", 100)

    assert secret not in str(excinfo.value)
    assert "<redacted>" in str(excinfo.value)
    assert "api.steampowered.com" in str(excinfo.value)  # still diagnosable
    # No chained original either - logger.exception would print its message
    # (key and all) right below this one.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None or excinfo.value.__suppress_context__


def test_fetch_servers_redacts_a_key_query_param_it_doesnt_know_the_value_of(monkeypatch):
    def fake_get(url, params, timeout):
        raise requests.ConnectionError("failed: https://api.steampowered.com/x?key=abc123&limit=1")

    monkeypatch.setattr(steam_api.requests, "get", fake_get)

    with pytest.raises(steam_api.SteamApiError) as excinfo:
        steam_api.fetch_servers("", 550, "left4dead2", 100)

    assert "abc123" not in str(excinfo.value)


def test_fetch_servers_defaults_to_empty_list_when_response_missing_servers(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": {}}

    monkeypatch.setattr(steam_api.requests, "get", lambda *a, **kw: FakeResponse())

    assert steam_api.fetch_servers("api-key", 550, "left4dead2", 100) == []
