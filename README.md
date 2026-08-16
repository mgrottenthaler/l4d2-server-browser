# l4d2-server-browser

An unofficial Left 4 Dead 2 server browser, not affiliated with or endorsed
by Valve. Queries the Steam master server list, pings candidates with A2S,
and resolves each server's map to its campaign/stage and game mode. A web
UI styled after Steam's own server browser.

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
executable for your OS from the
[Releases page](../../releases) instead. Double-click it (or run it from a
terminal) and it starts the server and opens your browser to it — no
`python3 webserver.py` needed. If no Steam Web API key is configured yet,
the page itself shows a setup banner to paste one into; it's saved to your
OS's per-user config directory (not next to the executable, since
PyInstaller's `--onefile` mode re-extracts everything to a fresh temp dir on
every launch), so later runs don't ask again. This is purely an alternate
launch mechanism — the `python3 webserver.py` flow above still works
exactly as documented.

To build it yourself instead of using a prebuilt binary:

```bash
pip install -r requirements-build.txt
python3 build_executable.py
```

This produces `dist/l4d2-server-browser` (or `.exe` on Windows) by freezing
`launcher.py` with PyInstaller. PyInstaller doesn't cross-compile, so the
output only runs on the OS you built it on — building all three platforms
means running this on each one, which is what
`.github/workflows/build-executables.yml` does on a runner matrix (manually
triggered, or automatically on a `v*` tag push).

## Releasing

Cutting a release is a version bump plus a tag push, done via:

```bash
python3 release.py minor   # 1.1 -> 1.2
python3 release.py major   # 1.1 -> 2.0
```

This requires a clean working tree on `main`. It bumps `VERSION` (the single
source of truth for the app's version, also served at `GET /api/version`),
commits it, tags it `vX.Y`, and — after confirming, since it's public
(`-y`/`--yes` skips the prompt) — pushes both to `origin`. The pushed tag
triggers `.github/workflows/build-executables.yml`, which builds the three
platform executables and publishes them as assets on a new GitHub Release
for that tag.

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
