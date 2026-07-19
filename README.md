# steam-browser

A Left 4 Dead 2 server browser. Queries the Steam master server list, pings
candidates with A2S, and resolves each server's map to its campaign/stage
and game mode. A web UI styled after Steam's own server browser.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root with your Steam Web API key
([get one here](https://steamcommunity.com/dev/apikey)):

```
STEAM-API-KEY=your_key_here
```

## Usage

```bash
python3 webserver.py
```

Then open http://127.0.0.1:5000 in a browser. It fetches and pings every
candidate L4D2 server in the background, and the page filters/sorts them
live — by name, game mode, max ping, secure/empty/full/password state —
without re-querying, the same way Steam's own server browser works. Click
column headers to sort, and use the Refresh button to re-query the master
list.

By default this serves via [waitress](https://github.com/Pylons/waitress),
a production-ready WSGI server, so it's fine to bind beyond `127.0.0.1` if
you want to reach it from another device on your network. The routes that
query an arbitrary `host:port` on request (the per-server sidebar queries
and favorites probing) are rate-limited and reject private/loopback/reserved
addresses as targets, so they can't be used to probe your own LAN.

Options:

- `--host HOST` — interface to bind (default: `127.0.0.1`)
- `--port PORT` — port to bind (default: `5000`)
- `--dev` — serve via Flask's own dev server instead of waitress, and enable
  developer-only endpoints (currently `GET /api/docs`, a human-readable
  listing of every `/api/*` route generated from the docstrings on their
  view functions — always in sync with the code since it's rendered from
  source at request time, not a checked-in file)

Query tuning (appid, gamedir, worker count, timeouts) lives in
`steam_browser/config.py`'s `DEFAULT_CONFIG` — everything user-facing is a
filter in the web UI itself.

## Standalone executable

If you'd rather not set up Python/a venv, grab the prebuilt single-file
executable for your OS instead (built by
`.github/workflows/build-executables.yml`, or run
`python3 build_executable.py` yourself after
`pip install -r requirements-build.txt`). Double-click it (or run it from a
terminal) and it starts the server and opens your browser to it — no
`python3 webserver.py` needed. On first run it asks for your Steam Web API
key and saves it to a `.env` file next to the executable, so later runs
don't ask again. This is purely an alternate launch mechanism — the
`python3 webserver.py` flow above still works exactly as documented.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

Unit tests cover the A2S protocol parsers (`a2s.py`), the master-list
filter builder (`steam_api.py`), mode/map resolution (`browser.py`,
`maps.py`), and the Flask routes in `web.py` (via `app.test_client()`,
with `a2s`/`steam_api`/`geoip` calls monkeypatched — no real network
traffic). See `tests/conftest.py` for the fixtures that reset `web.py`'s
shared in-process state between tests.

## License

MIT — see [LICENSE](LICENSE).
