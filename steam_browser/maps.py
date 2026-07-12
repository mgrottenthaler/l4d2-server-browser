"""Resolve a Left 4 Dead 2 map codename (as reported by A2S_INFO) to its
campaign and stage.

Covers the official Valve campaigns, DLC campaigns, and the L4D1 campaigns
ported into L4D2. Custom/workshop maps aren't in this table and resolve to
(None, None).
"""

CAMPAIGNS = [
    ("Dead Center", ["c1m1_hotel", "c1m2_streets", "c1m3_mall", "c1m4_atrium"]),
    ("Dark Carnival", ["c2m1_highway", "c2m2_fairgrounds", "c2m3_coaster", "c2m4_barns", "c2m5_concert"]),
    ("Swamp Fever", ["c3m1_plankcountry", "c3m2_swamp", "c3m3_shantytown", "c3m4_plantation"]),
    ("Hard Rain", ["c4m1_milltown_a", "c4m2_sugarmill_a", "c4m3_sugarmill_b", "c4m4_milltown_b", "c4m5_milltown_escape"]),
    ("The Parish", ["c5m1_waterfront", "c5m2_park", "c5m3_cemetery", "c5m4_quarter", "c5m5_bridge"]),
    ("The Passing", ["c6m1_riverbank", "c6m2_bedlam", "c6m3_port"]),
    ("The Sacrifice", ["c7m1_docks", "c7m2_barge", "c7m3_port"]),
    ("No Mercy", ["c8m1_apartment", "c8m2_subway", "c8m3_sewers", "c8m4_interior", "c8m5_rooftop"]),
    ("Crash Course", ["c9m1_alleys", "c9m2_lots"]),
    ("Death Toll", ["c10m1_caves", "c10m2_drainage", "c10m3_ranchhouse", "c10m4_mainstreet", "c10m5_houseboat"]),
    ("Dead Air", ["c11m1_greenhouse", "c11m2_offices", "c11m3_garage", "c11m4_terminal", "c11m5_runway"]),
    ("Blood Harvest", ["c12m1_hilltop", "c12m2_traintunnel", "c12m3_bridge", "c12m4_barn", "c12m5_cornfield"]),
    ("Cold Stream", ["c13m1_alpinecreek", "c13m2_southpinestream", "c13m3_memorialbridge", "c13m4_cutthroatcreek"]),
    ("The Last Stand", ["c14m1_junkyard", "c14m2_lighthouse"]),
]

_MAP_INDEX = {
    map_name: (campaign, position, len(maps))
    for campaign, maps in CAMPAIGNS
    for position, map_name in enumerate(maps, start=1)
}


def _stage_label(map_name):
    suffix = map_name.split("_", 1)[1] if "_" in map_name else map_name
    return suffix.replace("_", " ").title()


def resolve(map_name):
    """Return (campaign, stage_label) for a known map, or (None, None)."""
    entry = _MAP_INDEX.get(map_name)
    if entry is None:
        return None, None
    campaign, position, total = entry
    return campaign, "{}/{} {}".format(position, total, _stage_label(map_name))
