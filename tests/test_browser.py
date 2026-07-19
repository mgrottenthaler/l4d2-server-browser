import pytest

from steam_browser import a2s, browser


@pytest.mark.parametrize(
    "gametype,expected",
    [
        ("", "-"),
        ("coop", "Campaign"),
        ("versus", "Versus"),
        ("teamversus", "Team Versus"),
        ("scavenge", "Scavenge"),
        ("teamscavenge", "Team Scavenge"),
        ("survival", "Survival"),
        # Live servers tag both "survival" and "survivalversus" together.
        ("survival,empty,alltalk,survivalversus,secure", "Survival Versus"),
        ("coop,realism", "Campaign (Realism)"),
        ("versus,realism", "Versus (Realism)"),
        ("teamversus,realism", "Team Versus (Realism)"),
        # Realism servers often tag only "realism" and skip "coop".
        ("realism", "Campaign (Realism)"),
        # Realism collapses any non-campaign-family mode to "Campaign
        # (Realism)" rather than appending to it - only Campaign/Versus/Team
        # Versus get a plain "(Realism)" suffix.
        ("scavenge,realism", "Campaign (Realism)"),
        ("unknown_tag", "-"),
    ],
)
def test_parse_mode(gametype, expected):
    assert browser.parse_mode(gametype) == expected


def test_parse_mode_priority_prefers_more_specific_tag():
    # teamversus should win over versus when both are present.
    assert browser.parse_mode("versus,teamversus") == "Team Versus"


def test_parse_mode_is_case_and_whitespace_insensitive():
    assert browser.parse_mode(" COOP , Realism ") == "Campaign (Realism)"


def test_probe_server_enriches_master_list_entry(monkeypatch):
    def fake_query_info(host, port, timeout):
        assert (host, port) == ("1.2.3.4", 27015)
        return (
            {
                "protocol": 17,
                "name": "Live Server Name",
                "map": "c1m1_hotel",
                "folder": "left4dead2",
                "game": "Left 4 Dead 2",
                "app_id": 550,
                "players": 4,
                "max_players": 8,
                "bots": 0,
                "password_protected": False,
            },
            12.5,
        )

    monkeypatch.setattr(a2s, "query_info", fake_query_info)

    server = {
        "addr": "1.2.3.4:27015",
        "name": "Master List Name",
        "gametype": "coop,realism",
        "secure": True,
    }
    result = browser.probe_server(server, timeout=1.5)

    assert result["host"] == "1.2.3.4"
    assert result["port"] == 27015
    assert result["name"] == "Live Server Name"
    assert result["campaign"] == "Dead Center"
    assert result["stage"] == "1/4 Hotel"
    assert result["mode"] == "Campaign (Realism)"
    assert result["secure"] is True
    assert result["latency_ms"] == 12.5


def test_probe_server_falls_back_to_master_list_name_when_a2s_name_empty(monkeypatch):
    def fake_query_info(host, port, timeout):
        return (
            {
                "protocol": 17,
                "name": "",
                "map": "unknown_workshop_map",
                "folder": "left4dead2",
                "game": "Left 4 Dead 2",
                "app_id": 550,
                "players": 0,
                "max_players": 8,
                "bots": 0,
                "password_protected": False,
            },
            5.0,
        )

    monkeypatch.setattr(a2s, "query_info", fake_query_info)

    server = {"addr": "1.2.3.4:27015", "name": "Fallback Name", "gametype": ""}
    result = browser.probe_server(server, timeout=1.5)

    assert result["name"] == "Fallback Name"
    assert result["campaign"] == "-"
    assert result["stage"] == "-"


def test_probe_server_falls_back_to_a2s_info_when_not_from_master_list(monkeypatch):
    # A direct probe (e.g. a favorite pinged on its own, not sourced from
    # the master list) has no "secure"/"gametype" keys to draw on - fall
    # back to what A2S_INFO itself reports.
    def fake_query_info(host, port, timeout):
        return (
            {
                "protocol": 17,
                "name": "Direct Probe Server",
                "map": "c1m1_hotel",
                "folder": "left4dead2",
                "game": "Left 4 Dead 2",
                "app_id": 550,
                "players": 2,
                "max_players": 8,
                "bots": 0,
                "password_protected": False,
                "secure": True,
                "gametype": "coop,realism",
            },
            8.0,
        )

    monkeypatch.setattr(a2s, "query_info", fake_query_info)

    server = {"addr": "1.2.3.4:27015"}
    result = browser.probe_server(server, timeout=1.5)

    assert result["secure"] is True
    assert result["mode"] == "Campaign (Realism)"


def test_probe_server_returns_none_on_query_error(monkeypatch):
    def fake_query_info(host, port, timeout):
        raise a2s.QueryError("timed out")

    monkeypatch.setattr(a2s, "query_info", fake_query_info)

    server = {"addr": "1.2.3.4:27015", "gametype": ""}
    assert browser.probe_server(server, timeout=1.5) is None
