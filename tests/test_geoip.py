import pytest
import requests

from steam_browser import geoip


@pytest.fixture(autouse=True)
def reset_cache():
    """geoip._cache is a module-level global that persists for the process
    lifetime by design (see geoip.py docstring), so tests must reset it or
    bleed cached entries into each other.
    """
    geoip._cache.clear()
    yield


def test_lookup_countries_fetches_and_caches_new_ips(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"query": "1.2.3.4", "countryCode": "US", "country": "United States"}]

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(geoip.requests, "post", fake_post)

    result = geoip.lookup_countries({"1.2.3.4"})

    assert result == {"1.2.3.4": ("US", "United States")}
    assert captured["url"] == geoip.BATCH_URL
    assert captured["json"] == [{"query": "1.2.3.4", "fields": "countryCode,country,query"}]
    assert geoip._cache["1.2.3.4"] == ("US", "United States")


def test_lookup_countries_uses_cache_and_skips_fetch_for_known_ips(monkeypatch):
    geoip._cache["1.2.3.4"] = ("DE", "Germany")

    def fake_post(*args, **kwargs):
        raise AssertionError("should not fetch already-cached IPs")

    monkeypatch.setattr(geoip.requests, "post", fake_post)

    result = geoip.lookup_countries({"1.2.3.4"})

    assert result == {"1.2.3.4": ("DE", "Germany")}


def test_lookup_countries_batches_by_batch_size(monkeypatch):
    monkeypatch.setattr(geoip, "BATCH_SIZE", 2)
    ips = {"1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5"}
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    def fake_post(url, json, timeout):
        calls.append(json)
        return FakeResponse()

    monkeypatch.setattr(geoip.requests, "post", fake_post)

    geoip.lookup_countries(ips)

    assert len(calls) == 3  # ceil(5 / 2)
    assert sum(len(c) for c in calls) == 5
    assert all(len(c) <= 2 for c in calls)


def test_lookup_countries_returns_empty_tuple_on_request_exception(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(geoip.requests, "post", fake_post)

    result = geoip.lookup_countries({"1.2.3.4"})

    assert result == {"1.2.3.4": ("", "")}
    assert "1.2.3.4" not in geoip._cache  # left uncached so a later refresh can retry


def test_lookup_countries_returns_empty_tuple_on_malformed_json(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(geoip.requests, "post", lambda *a, **kw: FakeResponse())

    result = geoip.lookup_countries({"1.2.3.4"})

    assert result == {"1.2.3.4": ("", "")}
    assert "1.2.3.4" not in geoip._cache


def test_lookup_countries_defaults_missing_fields_to_empty_string(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"query": "1.2.3.4"}]

    monkeypatch.setattr(geoip.requests, "post", lambda *a, **kw: FakeResponse())

    result = geoip.lookup_countries({"1.2.3.4"})

    assert result == {"1.2.3.4": ("", "")}


def test_lookup_countries_only_fetches_missing_ips(monkeypatch):
    geoip._cache["1.1.1.1"] = ("US", "United States")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"query": "2.2.2.2", "countryCode": "DE", "country": "Germany"}]

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(geoip.requests, "post", fake_post)

    result = geoip.lookup_countries({"1.1.1.1", "2.2.2.2"})

    assert captured["json"] == [{"query": "2.2.2.2", "fields": "countryCode,country,query"}]
    assert result == {
        "1.1.1.1": ("US", "United States"),
        "2.2.2.2": ("DE", "Germany"),
    }
