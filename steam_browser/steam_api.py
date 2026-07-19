"""Steam Web API client: fetch candidate servers via IGameServersService/GetServerList."""

import requests

GET_SERVER_LIST_URL = "https://api.steampowered.com/IGameServersService/GetServerList/v1/"


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


def fetch_servers(api_key, appid, gamedir, limit, name_filter="", not_empty=False, not_full=False, timeout=15):
    """Return a list of dicts as provided by the Steam master server list."""
    params = {
        "key": api_key,
        "filter": build_filter(appid, gamedir, name_filter, not_empty=not_empty, not_full=not_full),
        "limit": limit,
    }
    resp = requests.get(GET_SERVER_LIST_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", {}).get("servers", [])
