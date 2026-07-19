"""Shared server-probing logic used by both the CLI and web interfaces."""

from steam_browser import a2s
from steam_browser import maps

# Priority-ordered game-mode tags as advertised in the master server list's
# "gametype" field (populated from the server's sv_tags cvar). Checked in
# order so a server tagged both "coop" and "versus" (shouldn't happen, but
# tags are admin-set and not validated) resolves to the more specific one.
# "survivalversus" must precede "survival": live servers tag both
# ("survival,empty,alltalk,survivalversus,secure" observed in the wild),
# since the mutation runs on top of the base Survival mode.
MODE_TAG_PRIORITY = [
    ("teamversus", "Team Versus"),
    ("versus", "Versus"),
    ("teamscavenge", "Team Scavenge"),
    ("scavenge", "Scavenge"),
    ("survivalversus", "Survival Versus"),
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

    `server` only strictly needs an "addr" key ("host:port") - this also
    doubles as a direct-probe path for servers that didn't come from the
    master list at all (e.g. a favorite pinged on its own), in which case
    "secure"/"gametype" are absent and fall back to the VAC/keywords fields
    A2S_INFO itself reports instead of the master list's.
    """
    host, port_str = server["addr"].rsplit(":", 1)
    port = int(port_str)
    try:
        info, latency_ms = a2s.query_info(host, port, timeout=timeout)
        campaign, stage = maps.resolve(info["map"])
        secure = server["secure"] if "secure" in server else info.get("secure", False)
        gametype = server["gametype"] if "gametype" in server else info.get("gametype", "")
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
            "secure": bool(secure),
            "mode": parse_mode(gametype),
        }
    except a2s.QueryError:
        return None
