"""Shared server-probing logic used by both the CLI and web interfaces."""

from steam_browser import a2s
from steam_browser import maps

# Priority-ordered game-mode tags as advertised in the master server list's
# "gametype" field (populated from the server's sv_tags cvar). Checked in
# order so a server tagged both "coop" and "versus" (shouldn't happen, but
# tags are admin-set and not validated) resolves to the more specific one.
MODE_TAG_PRIORITY = [
    ("teamversus", "Team Versus"),
    ("versus", "Versus"),
    ("teamscavenge", "Team Scavenge"),
    ("scavenge", "Scavenge"),
    ("survival", "Survival"),
    ("coop", "Campaign"),
]
CAMPAIGN_MODE_LABELS = {"Campaign", "Versus", "Team Versus"}


def parse_mode(gametype):
    """Derive a mode display string from a server's gametype tags."""
    tag_set = {t.strip().lower() for t in gametype.split(",") if t.strip()}

    mode = next((label for key, label in MODE_TAG_PRIORITY if key in tag_set), "-")
    if "realism" in tag_set:
        # Realism servers often tag only "realism" and skip "coop".
        mode = mode + " (Realism)" if mode in CAMPAIGN_MODE_LABELS else "Campaign (Realism)"

    return mode


def probe_server(server, timeout):
    """Query a master-list server entry over A2S_INFO and enrich it with
    resolved campaign/stage/mode. Returns None if the server didn't respond.
    """
    host, port_str = server["addr"].rsplit(":", 1)
    port = int(port_str)
    try:
        info, latency_ms = a2s.query_info(host, port, timeout=timeout)
        campaign, stage = maps.resolve(info["map"])
        return {
            "host": host,
            "port": port,
            "name": info["name"] or server.get("name", ""),
            "map": info["map"],
            "campaign": campaign or "-",
            "stage": stage or "-",
            "players": info["players"],
            "max_players": info["max_players"],
            "bots": info["bots"],
            "protocol": info["protocol"],
            "folder": info["folder"],
            "game": info["game"],
            "latency_ms": latency_ms,
            "password_protected": info["password_protected"],
            "secure": bool(server.get("secure")),
            "mode": parse_mode(server.get("gametype", "")),
        }
    except a2s.QueryError:
        return None
