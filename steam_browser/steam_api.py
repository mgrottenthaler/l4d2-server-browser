"""Steam Web API client: fetch candidate servers via IGameServersService/GetServerList."""

import re

import requests

GET_SERVER_LIST_URL = "https://api.steampowered.com/IGameServersService/GetServerList/v1/"
# (connect, read). The connect half is what a mid-session network change
# (laptop switching from wifi to a hotspot, VPN coming up) hangs on, and the
# refresh thread can't notice a Stop until it returns - see web.py's
# _fetch_all. 5s is already generous for reaching api.steampowered.com; the
# read half stays long because a 10k-server list is a big response.
DEFAULT_TIMEOUT = (5, 15)

_KEY_PARAM_RE = re.compile(r"(key=)[^&\s]+")


class SteamApiError(RuntimeError):
    """A master-list request failed. Its message has the API key redacted -
    requests puts the full request URL (`key` query parameter and all) into
    the message of every connection/timeout error, and web.py surfaces that
    message verbatim in the UI's error banner and writes it to the log file.
    """


def _redact(text, api_key):
    if api_key:
        text = text.replace(api_key, "<redacted>")
    return _KEY_PARAM_RE.sub(r"\1<redacted>", text)


def build_filter(appid, gamedir, name_filter="", not_empty=False, not_full=False):
    # NOTE: \dedicated\1\secure\1 is silently ignored by this endpoint (verified
    # empirically), and \password\0 makes it return zero results outright. Those
    # two are filtered client-side instead: dedicated/secure from the fields
    # already present on each returned server, password from the live A2S_INFO
    # visibility byte (see web.py's _fetch_all and browser.probe_server).
    filter_str = "\\appid\\{}\\gamedir\\{}".format(appid, gamedir)
    if name_filter:
        filter_str += "\\name_match\\*{}*".format(name_filter)
    if not_empty:
        filter_str += "\\empty\\1"
    if not_full:
        filter_str += "\\full\\1"
    return filter_str


def fetch_servers(api_key, appid, gamedir, limit, name_filter="", not_empty=False, not_full=False, timeout=DEFAULT_TIMEOUT):
    """Return a list of dicts as provided by the Steam master server list.

    Raises SteamApiError (never a raw requests exception) on any network or
    HTTP failure, so the key can't leak out through the error message.
    """
    params = {
        "key": api_key,
        "filter": build_filter(appid, gamedir, name_filter, not_empty=not_empty, not_full=not_full),
        "limit": limit,
    }
    try:
        resp = requests.get(GET_SERVER_LIST_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        # `from None`: the chained original would be printed right alongside
        # this one by logger.exception, key included, defeating the redaction.
        raise SteamApiError(_redact(str(e), api_key)) from None
    return data.get("response", {}).get("servers", [])
