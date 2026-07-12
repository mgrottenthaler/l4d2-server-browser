#!/usr/bin/env python3
"""Standalone A2S query tool: prints a server's difficulty plus raw info.

Difficulty isn't a standard A2S_INFO field. Games that expose it usually
stuff it into either the A2S_INFO "keywords" extra-data field or the
A2S_RULES key/value list, so this script pulls both, dumps everything it
gets, and picks out anything that looks difficulty-related.

Usage:
    python3 query_difficulty.py <ip> <port> [--timeout SECONDS]

Example:
    python3 query_difficulty.py 162.254.198.133 27284
"""

import argparse
import socket
import struct
import sys

A2S_INFO_REQUEST = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
A2S_RULES_HEADER = b"\xFF\xFF\xFF\xFFV"
HEADER_CHALLENGE = 0x41  # 'A'
HEADER_INFO = 0x49  # 'I'
HEADER_RULES = 0x45  # 'E'
HEADER_SPLIT = -2  # 0xFFFFFFFE as a signed int32, Source's split-packet marker


class QueryError(Exception):
    pass


def _read_cstring(data, offset):
    end = data.index(b"\x00", offset)
    return data[offset:end].decode("utf-8", errors="replace"), end + 1


def _recv_full(sock):
    """Receive one logical A2S response, transparently reassembling
    multi-packet replies. A2S_RULES in particular tends to blow past one
    UDP datagram once a server has more than a couple dozen cvars, so
    Source splits it across several packets marked with the 0xFFFFFFFE
    header (request id, total packet count, this packet's index, then
    for non-GoldSrc engines a 2-byte max-packet-size before the payload)."""
    packets = {}
    total = None
    while total is None or len(packets) < total:
        data, _ = sock.recvfrom(8192)
        header = struct.unpack_from("<i", data, 0)[0]
        if header == HEADER_SPLIT:
            request_id = struct.unpack_from("<I", data, 4)[0]
            if request_id & 0x80000000:
                raise QueryError("compressed split responses are not supported")
            total = data[8]
            index = data[9]
            # Modern (post-GoldSrc) Source servers always include a 2-byte
            # max-packet-size field here; GoldSrc is extinct in practice.
            packets[index] = data[12:]
        else:
            return data
    return b"".join(packets[i] for i in range(total))


def _send_recv(sock, host, port, payload):
    sock.sendto(payload, (host, port))
    return _recv_full(sock)


def query_info(host, port, timeout):
    """Full A2S_INFO, including the extra-data fields (EDF) games like
    7 Days to Die pack "keywords" into."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        data = _send_recv(sock, host, port, A2S_INFO_REQUEST)

        if len(data) > 5 and data[4] == HEADER_CHALLENGE:
            challenge = data[5:9]
            data = _send_recv(sock, host, port, A2S_INFO_REQUEST + challenge)

        if len(data) <= 5 or data[4] != HEADER_INFO:
            raise QueryError("unexpected A2S_INFO response header from {}:{}".format(host, port))

        body = data[5:]
        offset = 0
        info = {"_raw_bytes": data}

        info["protocol"] = body[offset]
        offset += 1
        info["name"], offset = _read_cstring(body, offset)
        info["map"], offset = _read_cstring(body, offset)
        info["folder"], offset = _read_cstring(body, offset)
        info["game"], offset = _read_cstring(body, offset)
        info["app_id"] = struct.unpack_from("<h", body, offset)[0]
        offset += 2
        info["players"] = body[offset]
        offset += 1
        info["max_players"] = body[offset]
        offset += 1
        info["bots"] = body[offset]
        offset += 1
        info["server_type"] = chr(body[offset])
        offset += 1
        info["environment"] = chr(body[offset])
        offset += 1
        info["password_protected"] = bool(body[offset])
        offset += 1
        info["vac_secured"] = bool(body[offset])
        offset += 1

        if info["app_id"] == 2400:  # "The Ship" has 3 extra bytes here.
            info["ship_mode"] = body[offset]
            info["ship_witnesses"] = body[offset + 1]
            info["ship_duration"] = body[offset + 2]
            offset += 3

        # Engine/game version string, e.g. "2.2.4.3". Always present.
        info["version"], offset = _read_cstring(body, offset)

        if offset < len(body):
            edf = body[offset]
            offset += 1
            info["edf"] = edf

            if edf & 0x80:
                info["port"] = struct.unpack_from("<h", body, offset)[0]
                offset += 2
            if edf & 0x10:
                info["steam_id"] = struct.unpack_from("<Q", body, offset)[0]
                offset += 8
            if edf & 0x40:
                info["sourcetv_port"] = struct.unpack_from("<h", body, offset)[0]
                offset += 2
                info["sourcetv_name"], offset = _read_cstring(body, offset)
            if edf & 0x20:
                info["keywords"], offset = _read_cstring(body, offset)
            if edf & 0x01:
                info["game_id"] = struct.unpack_from("<Q", body, offset)[0]
                offset += 8

        return info
    except socket.timeout:
        raise QueryError("timed out querying A2S_INFO {}:{}".format(host, port))
    finally:
        sock.close()


def query_rules(host, port, timeout):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        data = _send_recv(sock, host, port, A2S_RULES_HEADER + b"\xFF\xFF\xFF\xFF")

        if len(data) > 5 and data[4] == HEADER_CHALLENGE:
            challenge = data[5:9]
            data = _send_recv(sock, host, port, A2S_RULES_HEADER + challenge)

        if len(data) <= 5 or data[4] != HEADER_RULES:
            raise QueryError("unexpected A2S_RULES response header from {}:{}".format(host, port))

        body = data[5:]
        offset = 0
        num_rules = struct.unpack_from("<h", body, offset)[0]
        offset += 2

        rules = {}
        for _ in range(num_rules):
            name, offset = _read_cstring(body, offset)
            value, offset = _read_cstring(body, offset)
            rules[name] = value
        return rules
    except socket.timeout:
        raise QueryError("timed out querying A2S_RULES {}:{}".format(host, port))
    finally:
        sock.close()


def parse_keywords(keywords):
    """7 Days to Die (and some other games) cram a comma-separated
    key:value list into the A2S_INFO keywords field."""
    parsed = {}
    for token in keywords.split(","):
        if ":" in token:
            key, _, value = token.partition(":")
            parsed[key] = value
    return parsed


def find_difficulty(info, keyword_map, rules):
    candidates = {}
    for source_name, mapping in (("keywords", keyword_map), ("rules", rules)):
        for key, value in mapping.items():
            if "diff" in key.lower():
                candidates["{} [{}]".format(key, source_name)] = value
    return candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ip")
    parser.add_argument("port", type=int)
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()

    try:
        info = query_info(args.ip, args.port, args.timeout)
    except QueryError as exc:
        print("A2S_INFO failed: {}".format(exc), file=sys.stderr)
        info = {}

    try:
        rules = query_rules(args.ip, args.port, args.timeout)
    except QueryError as exc:
        print("A2S_RULES failed: {}".format(exc), file=sys.stderr)
        rules = {}

    keyword_map = {}
    if info.get("keywords"):
        keyword_map = parse_keywords(info["keywords"])

    print("=== A2S_INFO ===")
    for key, value in info.items():
        if key == "_raw_bytes":
            continue
        print("{:20s} {}".format(key, value))

    if keyword_map:
        print("\n=== keywords (parsed) ===")
        for key, value in keyword_map.items():
            print("{:30s} {}".format(key, value))

    if rules:
        print("\n=== A2S_RULES ===")
        for key, value in sorted(rules.items()):
            print("{:30s} {}".format(key, value))

    difficulty = find_difficulty(info, keyword_map, rules)
    print("\n=== difficulty guess ===")
    if difficulty:
        for key, value in difficulty.items():
            print("{:30s} {}".format(key, value))
    else:
        print("no field with 'diff' in its name found")

    if "_raw_bytes" in info:
        print("\n=== raw A2S_INFO bytes ===")
        print(info["_raw_bytes"])


if __name__ == "__main__":
    main()
