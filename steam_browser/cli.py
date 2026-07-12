"""CLI entry point: fetch L4D2 servers, measure latency, filter, print."""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from steam_browser import config as config_mod
from steam_browser import steam_api
from steam_browser.browser import probe_server

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args():
    parser = argparse.ArgumentParser(description="Left 4 Dead 2 CLI server browser")
    parser.add_argument(
        "--config",
        default=os.path.join(PROJECT_ROOT, "config.json"),
        help="Path to JSON config file (default: config.json)",
    )
    parser.add_argument(
        "--max-latency",
        type=int,
        default=None,
        help="Override max_latency_ms from config",
    )
    parser.add_argument(
        "--name-filter",
        default=None,
        help="Override name_filter from config (case-insensitive substring match)",
    )
    return parser.parse_args()


def print_table(rows):
    if not rows:
        print("No servers found matching your criteria.")
        return

    headers = ["Latency", "Players", "Mode", "Map", "Campaign", "Stage", "Name", "Address"]
    table_rows = []
    for r in rows:
        table_rows.append(
            [
                "{:.0f} ms".format(r["latency_ms"]),
                "{}/{}".format(r["players"], r["max_players"]),
                r["mode"],
                r["map"],
                r["campaign"],
                r["stage"],
                r["name"],
                "{}:{}".format(r["host"], r["port"]),
            ]
        )

    widths = [len(h) for h in headers]
    for row in table_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    print(fmt_row(headers))
    print("  ".join("-" * w for w in widths))
    for row in table_rows:
        print(fmt_row(row))


def main():
    args = parse_args()
    cfg = config_mod.load_config(args.config)
    if args.max_latency is not None:
        cfg["max_latency_ms"] = args.max_latency
    if args.name_filter is not None:
        cfg["name_filter"] = args.name_filter

    try:
        api_key = config_mod.get_steam_api_key(PROJECT_ROOT)
    except RuntimeError as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)

    target_matches = cfg.get("target_matches", 20)
    query_limit = cfg.get("initial_servers_to_query", 100)
    max_servers_to_query = cfg["max_servers_to_query"]
    max_latency_ms = cfg["max_latency_ms"]
    name_filter = cfg.get("name_filter", "")
    name_filter_lower = name_filter.lower()

    print("Fetching the full {} server list...".format(cfg["gamedir"]))

    seen_addrs = set()
    results = []
    filtered = []
    candidate_count = 0

    while True:
        servers = steam_api.fetch_servers(
            api_key,
            cfg["appid"],
            cfg["gamedir"],
            query_limit,
            name_filter=name_filter,
            not_empty=cfg.get("not_empty", False),
            not_full=cfg.get("not_full", False),
        )
        if cfg.get("dedicated_secure", False):
            servers = [s for s in servers if s.get("dedicated") and s.get("secure")]

        new_servers = [s for s in servers if s["addr"] not in seen_addrs]
        for s in new_servers:
            seen_addrs.add(s["addr"])
        candidate_count = len(seen_addrs)

        print(
            "  requested {} candidates, {} new ({} total so far), {} matches so far. Pinging...".format(
                query_limit, len(new_servers), candidate_count, len(filtered)
            )
        )

        with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
            futures = [executor.submit(probe_server, s, cfg["query_timeout_s"]) for s in new_servers]
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    continue
                results.append(result)
                if result["latency_ms"] > max_latency_ms:
                    continue
                if name_filter and name_filter_lower not in result["name"].lower():
                    continue
                if cfg.get("no_password", False) and result["password_protected"]:
                    continue
                filtered.append(result)

        exhausted_master_list = len(servers) < query_limit
        if query_limit >= max_servers_to_query or exhausted_master_list:
            break
        query_limit = min(query_limit * 2, max_servers_to_query)

    filtered.sort(key=lambda r: r["latency_ms"])
    filtered = filtered[:target_matches]

    print(
        "\n{} of {} servers responded; {} within {} ms{} (showing up to {}).\n".format(
            len(results),
            candidate_count,
            len(filtered),
            max_latency_ms,
            " and matching name filter '{}'".format(name_filter) if name_filter else "",
            target_matches,
        )
    )
    print_table(filtered)


if __name__ == "__main__":
    main()
