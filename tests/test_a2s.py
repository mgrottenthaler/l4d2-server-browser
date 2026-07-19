import socket
import struct

import pytest

from steam_browser import a2s


# ---------------------------------------------------------------------------
# Payload builders (mirror what a real Source engine server sends, minus the
# leading 0xFFFFFFFF prefix and header byte - the parse functions are called
# on the payload after those are stripped off).
# ---------------------------------------------------------------------------

def _cstring(s):
    return s.encode("utf-8") + b"\x00"


def build_info_payload(
    protocol=17,
    name="Test Server",
    map_name="c1m1_hotel",
    folder="left4dead2",
    game="Left 4 Dead 2",
    app_id=550,
    players=3,
    max_players=8,
    bots=1,
    password_protected=False,
    include_extra_fields=False,
    secure=False,
    version="1.0.0.0",
    keywords=None,
):
    data = struct.pack("<B", protocol)
    data += _cstring(name)
    data += _cstring(map_name)
    data += _cstring(folder)
    data += _cstring(game)
    data += struct.pack("<h", app_id)
    data += struct.pack("<BBB", players, max_players, bots)
    data += b"d"  # server type
    data += b"l"  # environment
    data += struct.pack("<B", int(password_protected))
    if not include_extra_fields:
        return data

    data += struct.pack("<B", int(secure))
    data += _cstring(version)
    edf = 0x20 if keywords is not None else 0
    data += struct.pack("<B", edf)
    if keywords is not None:
        data += _cstring(keywords)
    return data


def build_player_payload(players):
    data = struct.pack("<B", len(players))
    for p in players:
        data += struct.pack("<B", 0)  # player index, unused
        data += _cstring(p["name"])
        data += struct.pack("<i", p["score"])
        data += struct.pack("<f", p["duration"])
    return data


def build_rules_payload(rules):
    data = struct.pack("<h", len(rules))
    for r in rules:
        data += _cstring(r["name"])
        data += _cstring(r["value"])
    return data


# ---------------------------------------------------------------------------
# _read_cstring
# ---------------------------------------------------------------------------

def test_read_cstring_reads_up_to_null_and_advances_offset():
    data = b"hello\x00world\x00"
    value, offset = a2s._read_cstring(data, 0)
    assert value == "hello"
    assert offset == 6

    value, offset = a2s._read_cstring(data, offset)
    assert value == "world"
    assert offset == 12


# ---------------------------------------------------------------------------
# _parse_info_response
# ---------------------------------------------------------------------------

def test_parse_info_response_extracts_all_fields():
    payload = build_info_payload(
        name="Coop Server", map_name="c2m1_highway", players=4, max_players=8, bots=2
    )
    info = a2s._parse_info_response(payload)

    assert info == {
        "protocol": 17,
        "name": "Coop Server",
        "map": "c2m1_highway",
        "folder": "left4dead2",
        "game": "Left 4 Dead 2",
        "app_id": 550,
        "players": 4,
        "max_players": 8,
        "bots": 2,
        "password_protected": False,
        "secure": False,
        "gametype": "",
    }


def test_parse_info_response_password_protected_flag():
    payload = build_info_payload(password_protected=True)
    info = a2s._parse_info_response(payload)
    assert info["password_protected"] is True


def test_parse_info_response_missing_vac_and_edf_defaults_to_unknown():
    # Payload truncated right after visibility (no VAC/version/EDF at all) -
    # some engine forks omit these; they're enrichment only, not required.
    payload = build_info_payload(include_extra_fields=False)
    info = a2s._parse_info_response(payload)
    assert info["secure"] is False
    assert info["gametype"] == ""


def test_parse_info_response_extracts_vac_status():
    payload = build_info_payload(include_extra_fields=True, secure=True)
    info = a2s._parse_info_response(payload)
    assert info["secure"] is True


def test_parse_info_response_extracts_keywords_as_gametype():
    payload = build_info_payload(include_extra_fields=True, secure=True, keywords="coop,realism")
    info = a2s._parse_info_response(payload)
    assert info["gametype"] == "coop,realism"


def test_parse_info_response_no_edf_flags_set_leaves_gametype_empty():
    payload = build_info_payload(include_extra_fields=True, secure=True, keywords=None)
    info = a2s._parse_info_response(payload)
    assert info["secure"] is True
    assert info["gametype"] == ""


# ---------------------------------------------------------------------------
# _parse_player_response
# ---------------------------------------------------------------------------

def test_parse_player_response_empty():
    assert a2s._parse_player_response(build_player_payload([])) == []


def test_parse_player_response_multiple_players():
    players = [
        {"name": "Alice", "score": 12, "duration": 305.5},
        {"name": "Bob", "score": 0, "duration": 10.0},
    ]
    payload = build_player_payload(players)
    parsed = a2s._parse_player_response(payload)

    assert len(parsed) == 2
    assert parsed[0]["name"] == "Alice"
    assert parsed[0]["score"] == 12
    assert parsed[0]["duration"] == pytest.approx(305.5)
    assert parsed[1]["name"] == "Bob"
    assert parsed[1]["duration"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# _parse_rules_response
# ---------------------------------------------------------------------------

def test_parse_rules_response_empty():
    assert a2s._parse_rules_response(build_rules_payload([])) == []


def test_parse_rules_response_name_value_pairs():
    rules = [
        {"name": "sv_gametypes", "value": "coop"},
        {"name": "mp_gamemode", "value": "coop"},
    ]
    payload = build_rules_payload(rules)
    parsed = a2s._parse_rules_response(payload)
    assert parsed == rules


# ---------------------------------------------------------------------------
# _recv_response - single packet and multi-packet reassembly
# ---------------------------------------------------------------------------

class FakeSocket:
    """Stand-in for socket.socket: recvfrom() replays a fixed sequence of
    packets instead of hitting the network, so protocol tests don't need a
    real UDP endpoint.
    """

    def __init__(self, packets):
        self._packets = list(packets)
        self.sent = []

    def settimeout(self, timeout):
        pass

    def sendto(self, data, addr):
        self.sent.append(data)

    def recvfrom(self, bufsize):
        if not self._packets:
            raise socket.timeout()
        return self._packets.pop(0), ("127.0.0.1", 27015)

    def close(self):
        pass


def test_recv_response_single_packet():
    payload = b"I" + build_info_payload()
    packet = struct.pack("<i", -1) + payload
    sock = FakeSocket([packet])

    assert a2s._recv_response(sock) == payload


def build_multipacket(request_id, total, number, max_size, chunk):
    return struct.pack("<i", -2) + struct.pack("<iBBh", request_id, total, number, max_size) + chunk


def test_recv_response_reassembles_multi_packet():
    payload = b"E" + build_rules_payload([{"name": "a", "value": "1"}])
    half = len(payload) // 2

    packet0 = build_multipacket(1, 2, 0, 1400, payload[:half])
    packet1 = build_multipacket(1, 2, 1, 1400, payload[half:])
    # Delivered out of order to prove reassembly sorts by packet number, not
    # arrival order.
    sock = FakeSocket([packet1, packet0])

    assert a2s._recv_response(sock) == payload


def test_recv_response_raises_on_compressed_multi_packet():
    packet = build_multipacket(-1, 2, 0, 1400, b"stub")
    sock = FakeSocket([packet])

    with pytest.raises(a2s.QueryError):
        a2s._recv_response(sock)


def test_recv_response_raises_on_malformed_prefix():
    packet = struct.pack("<i", 0) + b"garbage"
    sock = FakeSocket([packet])

    with pytest.raises(a2s.QueryError):
        a2s._recv_response(sock)


# ---------------------------------------------------------------------------
# query_info - challenge/retry handshake and error paths, via a monkeypatched
# socket.socket so no real network traffic happens.
# ---------------------------------------------------------------------------

def test_query_info_follows_challenge_then_returns_info(monkeypatch):
    challenge_bytes = b"\x01\x02\x03\x04"
    challenge_packet = struct.pack("<i", -1) + bytes([a2s.HEADER_CHALLENGE]) + challenge_bytes
    info_packet = struct.pack("<i", -1) + b"I" + build_info_payload(name="After Challenge")

    sock = FakeSocket([challenge_packet, info_packet])
    monkeypatch.setattr(a2s.socket, "socket", lambda *a, **kw: sock)

    info, latency_ms = a2s.query_info("127.0.0.1", 27015)

    assert info["name"] == "After Challenge"
    assert latency_ms >= 0
    # First request has no challenge suffix, retry appends the one the
    # server handed back.
    assert sock.sent[0] == a2s.A2S_INFO_REQUEST
    assert sock.sent[1] == a2s.A2S_INFO_REQUEST + challenge_bytes


def test_query_info_raises_on_timeout(monkeypatch):
    sock = FakeSocket([])  # recvfrom immediately raises socket.timeout
    monkeypatch.setattr(a2s.socket, "socket", lambda *a, **kw: sock)

    with pytest.raises(a2s.QueryError):
        a2s.query_info("127.0.0.1", 27015)


def test_query_info_raises_on_unexpected_header(monkeypatch):
    bogus_packet = struct.pack("<i", -1) + b"X" + b"stub"
    sock = FakeSocket([bogus_packet])
    monkeypatch.setattr(a2s.socket, "socket", lambda *a, **kw: sock)

    with pytest.raises(a2s.QueryError):
        a2s.query_info("127.0.0.1", 27015)
