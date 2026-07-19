from steam_browser import maps


def test_resolve_unknown_map_returns_none_none():
    assert maps.resolve("ze_workshop_map_v3") == (None, None)


def test_resolve_first_stage_of_campaign():
    campaign, stage = maps.resolve("c1m1_hotel")
    assert campaign == "Dead Center"
    assert stage == "1/4 Hotel"


def test_resolve_last_stage_of_campaign():
    campaign, stage = maps.resolve("c1m4_atrium")
    assert campaign == "Dead Center"
    assert stage == "4/4 Atrium"


def test_resolve_middle_stage_uses_correct_total_and_position():
    campaign, stage = maps.resolve("c2m3_coaster")
    assert campaign == "Dark Carnival"
    assert stage == "3/5 Coaster"


def test_resolve_stage_label_replaces_underscores_and_title_cases():
    campaign, stage = maps.resolve("c4m2_sugarmill_a")
    assert campaign == "Hard Rain"
    assert stage == "2/5 Sugarmill A"


def test_every_campaign_map_resolves_to_a_known_campaign():
    for campaign, map_names in maps.CAMPAIGNS:
        for map_name in map_names:
            resolved_campaign, stage = maps.resolve(map_name)
            assert resolved_campaign == campaign
            assert stage is not None
