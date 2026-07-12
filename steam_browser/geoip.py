"""Best-effort IP -> country lookup, used to show a flag + country name next
to each server. Uses ip-api.com's free batch endpoint; results are cached in
memory for the life of the process since an IP's country essentially never
changes.
"""

import requests

BATCH_URL = "http://ip-api.com/batch"
BATCH_SIZE = 100  # ip-api.com's max per batch request
REQUEST_TIMEOUT_S = 5

_cache = {}  # ip -> (country_code, country_name), ("", "") if unknown/failed


def _fetch_batch(ips):
    payload = [{"query": ip, "fields": "countryCode,country,query"} for ip in ips]
    try:
        resp = requests.post(BATCH_URL, json=payload, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        for entry in resp.json():
            _cache[entry.get("query")] = (entry.get("countryCode") or "", entry.get("country") or "")
    except (requests.RequestException, ValueError):
        # Geolocation is a nice-to-have; leave the misses uncached so a
        # later refresh can retry once the network/API recovers.
        pass


def lookup_countries(ips):
    """Return {ip: (country_code, country_name)} for the given IPs,
    resolving any not already cached. Values are ("", "") when unknown or
    the lookup failed.
    """
    missing = sorted({ip for ip in ips if ip not in _cache})
    for i in range(0, len(missing), BATCH_SIZE):
        _fetch_batch(missing[i:i + BATCH_SIZE])

    return {ip: _cache.get(ip, ("", "")) for ip in ips}
