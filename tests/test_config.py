from steam_browser.config import get_steam_api_key, set_steam_api_key


def test_get_steam_api_key_returns_none_when_missing(tmp_path):
    assert get_steam_api_key(str(tmp_path)) is None


def test_get_steam_api_key_reads_existing_env(tmp_path):
    (tmp_path / ".env").write_text("STEAM-API-KEY=EXISTING\n")
    assert get_steam_api_key(str(tmp_path)) == "EXISTING"


def test_set_steam_api_key_creates_env_when_absent(tmp_path):
    set_steam_api_key(str(tmp_path), "NEWKEY")
    assert get_steam_api_key(str(tmp_path)) == "NEWKEY"


def test_set_steam_api_key_replaces_existing_line_without_duplicating(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER_VAR=keep-me\nSTEAM-API-KEY=OLDKEY\n")

    set_steam_api_key(str(tmp_path), "NEWKEY")

    contents = env_path.read_text()
    assert contents.count("STEAM-API-KEY=") == 1
    assert "OTHER_VAR=keep-me" in contents
    assert get_steam_api_key(str(tmp_path)) == "NEWKEY"
