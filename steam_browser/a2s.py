"""Minimal Source Engine Query (A2S_INFO) client.

Used to measure real round-trip latency to a game server and pull its
live state (name, map, players). See:
https://developer.valvesoftware.com/wiki/Server_queries#A2S_INFO
"""

import socket
import struct
import time

A2S_INFO_REQUEST = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
A2S_PLAYER_REQUEST_HEADER = b"\xFF\xFF\xFF\xFFU"
A2S_RULES_REQUEST_HEADER = b"\xFF\xFF\xFF\xFFV"
HEADER_CHALLENGE = 0x41  # 'A'
HEADER_INFO = 0x49  # 'I'
HEADER_PLAYER = 0x44  # 'D'
HEADER_RULES = 0x45  # 'E'


class QueryError(Exception):
    pass


def _read_cstring(data, offset):
    end = data.index(b"\x00", offset)
    return data[offset:end].decode("utf-8", errors="replace"), end + 1


def _recv_response(sock):
    """Receive one A2S response, transparently reassembling it if the
    server split it across multiple UDP packets (common for A2S_RULES on
    servers with many cvars). Returns the payload after the single-packet
    0xFFFFFFFF prefix, i.e. starting at the header byte ('I'/'D'/'E'/'A').

    Bzip2-compressed multi-packet responses (rare - opt-in server side,
    not used by dedicated L4D2 servers in practice) are not supported.
    """
    data, _ = sock.recvfrom(65535)
    prefix = struct.unpack_from("<i", data, 0)[0]
    if prefix == -1:
        return data[4:]
    if prefix != -2:
        raise QueryError("malformed response")

    request_id, total, number, _max_size = struct.unpack_from("<iBBh", data, 4)
    if request_id < 0:
        raise QueryError("compressed multi-packet response not supported")

    parts = {number: data[12:]}
    while len(parts) < total:
        data, _ = sock.recvfrom(65535)
        prefix = struct.unpack_from("<i", data, 0)[0]
        if prefix != -2:
            raise QueryError("malformed multi-packet response")
        _, total, number, _max_size = struct.unpack_from("<iBBh", data, 4)
        parts[number] = data[12:]

    payload = b"".join(parts[i] for i in range(total))
    # Some engine versions prepend an extra 0xFFFFFFFF marker to the
    # reassembled payload (as if it were a single-packet response), others
    # don't - strip it only if present rather than assuming either way.
    if len(payload) >= 4 and struct.unpack_from("<i", payload, 0)[0] == -1:
        payload = payload[4:]
    return payload


def _parse_info_response(data):
    # data starts after the 4-byte 0xFFFFFFFF prefix and the 'I' header byte.
    offset = 0
    protocol = data[offset]
    offset += 1
    name, offset = _read_cstring(data, offset)
    map_name, offset = _read_cstring(data, offset)
    folder, offset = _read_cstring(data, offset)
    game, offset = _read_cstring(data, offset)
    app_id = struct.unpack_from("<h", data, offset)[0]
    offset += 2
    players = data[offset]
    offset += 1
    max_players = data[offset]
    offset += 1
    bots = data[offset]
    offset += 1
    offset += 1  # server type ('d'/'l'/'p')
    offset += 1  # environment ('l'/'w'/'m')
    visibility = data[offset]  # 0 = public, 1 = password-protected
    offset += 1

    # VAC status, version, and the EDF-gated extra fields (keywords among
    # them) are enrichment only - a handful of engine forks truncate the
    # response before them, so any failure here falls back to unknown rather
    # than invalidating the whole probe.
    secure = False
    gametype = ""
    try:
        secure = bool(data[offset])
        offset += 1
        if app_id == 2400:  # "The Ship" has 3 extra bytes here; unused by L4D2
            offset += 3
        _version, offset = _read_cstring(data, offset)
        if offset < len(data):
            edf = data[offset]
            offset += 1
            if edf & 0x80:
                offset += 2  # port
            if edf & 0x10:
                offset += 8  # SteamID
            if edf & 0x40:
                offset += 2  # SourceTV port
                _tv_name, offset = _read_cstring(data, offset)
            if edf & 0x20:
                # Keywords - the same sv_tags string the master list exposes
                # as "gametype", used here so a directly-probed server (not
                # sourced from the master list, e.g. a favorite) can still
                # resolve a game mode.
                gametype, offset = _read_cstring(data, offset)
    except (IndexError, struct.error, ValueError):
        pass

    return {
        "protocol": protocol,
        "name": name,
        "map": map_name,
        "folder": folder,
        "game": game,
        "app_id": app_id,
        "players": players,
        "max_players": max_players,
        "bots": bots,
        "password_protected": bool(visibility),
        "secure": secure,
        "gametype": gametype,
    }


def query_info(host, port, timeout=1.5):
    """Query a server for A2S_INFO, returning (info_dict, latency_ms).

    Raises QueryError if the server does not respond in time or the
    response is malformed.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        start = time.perf_counter()
        sock.sendto(A2S_INFO_REQUEST, (host, port))
        data = _recv_response(sock)

        if len(data) > 1 and data[0] == HEADER_CHALLENGE:
            challenge = data[1:5]
            sock.sendto(A2S_INFO_REQUEST + challenge, (host, port))
            data = _recv_response(sock)

        latency_ms = (time.perf_counter() - start) * 1000

        if len(data) < 1 or data[0] != HEADER_INFO:
            raise QueryError("unexpected response header from {}:{}".format(host, port))

        info = _parse_info_response(data[1:])
        return info, latency_ms
    except socket.timeout:
        raise QueryError("timed out querying {}:{}".format(host, port))
    except OSError as e:
        # sendto/recvfrom on an unroutable or otherwise bad address (e.g.
        # "Network is unreachable") - one bad candidate shouldn't be able to
        # take down the whole batch probe in web.py's _fetch_all.
        raise QueryError("network error querying {}:{}: {}".format(host, port, e))
    except (struct.error, IndexError, ValueError, UnicodeDecodeError) as e:
        raise QueryError("malformed response from {}:{}: {}".format(host, port, e))
    finally:
        sock.close()


def _parse_player_response(data):
    offset = 0
    num_players = data[offset]
    offset += 1

    players = []
    for _ in range(num_players):
        offset += 1  # player index - unused, servers always send 0
        name, offset = _read_cstring(data, offset)
        score = struct.unpack_from("<i", data, offset)[0]
        offset += 4
        duration = struct.unpack_from("<f", data, offset)[0]
        offset += 4
        players.append({"name": name, "score": score, "duration": duration})
    return players


def query_players(host, port, timeout=1.5):
    """Query a server for A2S_PLAYER, returning a list of connected players
    (name, score, seconds connected).

    Raises QueryError if the server does not respond in time or the
    response is malformed. A2S_PLAYER always requires the challenge
    handshake (unlike A2S_INFO, where some old servers skip it).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        challenge = b"\xFF\xFF\xFF\xFF"
        sock.sendto(A2S_PLAYER_REQUEST_HEADER + challenge, (host, port))
        data = _recv_response(sock)

        if len(data) > 1 and data[0] == HEADER_CHALLENGE:
            challenge = data[1:5]
            sock.sendto(A2S_PLAYER_REQUEST_HEADER + challenge, (host, port))
            data = _recv_response(sock)

        if len(data) < 1 or data[0] != HEADER_PLAYER:
            raise QueryError("unexpected response header from {}:{}".format(host, port))

        return _parse_player_response(data[1:])
    except socket.timeout:
        raise QueryError("timed out querying {}:{}".format(host, port))
    except OSError as e:
        raise QueryError("network error querying {}:{}: {}".format(host, port, e))
    except (struct.error, IndexError, ValueError, UnicodeDecodeError) as e:
        raise QueryError("malformed response from {}:{}: {}".format(host, port, e))
    finally:
        sock.close()


def _parse_rules_response(data):
    offset = 0
    num_rules = struct.unpack_from("<h", data, offset)[0]
    offset += 2

    rules = []
    for _ in range(num_rules):
        name, offset = _read_cstring(data, offset)
        value, offset = _read_cstring(data, offset)
        rules.append({"name": name, "value": value})
    return rules


def query_rules(host, port, timeout=1.5):
    """Query a server for A2S_RULES, returning its list of sv_* cvars as
    advertised to clients (name/value pairs, server admin controlled).

    Raises QueryError if the server does not respond in time, doesn't
    support A2S_RULES, or the response is malformed.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        challenge = b"\xFF\xFF\xFF\xFF"
        sock.sendto(A2S_RULES_REQUEST_HEADER + challenge, (host, port))
        data = _recv_response(sock)

        if len(data) > 1 and data[0] == HEADER_CHALLENGE:
            challenge = data[1:5]
            sock.sendto(A2S_RULES_REQUEST_HEADER + challenge, (host, port))
            data = _recv_response(sock)

        if len(data) < 1 or data[0] != HEADER_RULES:
            raise QueryError("unexpected response header from {}:{}".format(host, port))

        return _parse_rules_response(data[1:])
    except socket.timeout:
        raise QueryError("timed out querying {}:{}".format(host, port))
    except OSError as e:
        raise QueryError("network error querying {}:{}: {}".format(host, port, e))
    except (struct.error, IndexError, ValueError, UnicodeDecodeError) as e:
        raise QueryError("malformed response from {}:{}: {}".format(host, port, e))
    finally:
        sock.close()
