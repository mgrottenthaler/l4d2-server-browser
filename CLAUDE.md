# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Left 4 Dead 2 server browser: queries the Steam master server list, pings
candidates with the Source A2S protocol, resolves each server's map to a
campaign/stage, and serves a web UI styled after Steam's own in-game server
browser. Web-only — there is no CLI entry point.

## Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt      # requests, flask, flask-limiter, waitress

python3 webserver.py                 # serves on http://127.0.0.1:5000 via waitress
python3 webserver.py --host 0.0.0.0 --port 8080
python3 webserver.py --dev           # Flask's own dev server instead of waitress, also enables GET /api/docs

pip install -r requirements-dev.txt  # adds pytest on top of requirements.txt
pytest                               # tests/, no network — a2s/steam_api/geoip are monkeypatched

pip install -r requirements-build.txt  # adds pyinstaller on top of requirements.txt
python3 build_executable.py          # -> dist/l4d2-server-browser(.exe), see "Standalone executable" below
```

Requires a `.env` file in the project root with `STEAM-API-KEY=...` (get one
at https://steamcommunity.com/dev/apikey).

There is no linter in this repo. `pytest` is the test suite (see
`tests/conftest.py` for the fixtures that reset `web.py`'s shared in-process
state between tests). `.venv` may also carry a `playwright` install (Python
bindings + chromium) usable for driving the UI in a real browser — see the
`verify` skill.

### Standalone executable

`launcher.py` is an alternate entry point (alongside `webserver.py`, not a
replacement for it) built into a single-file executable via
`build_executable.py` (PyInstaller). It starts waitress in a background
thread on the first free port starting at 5000 and opens the system browser
to it, so a downloaded binary is double-click-to-run with no venv/`.env`
setup — on first run it prompts for the Steam Web API key on stdin and
appends it to a `.env` file next to the executable (not the source tree's
`.env`, and not baked into the binary, since it's a secret).

Two path-resolution branches in `web.py` (`_project_root()`/`_static_dir()`,
gated on `sys.frozen`) exist only for this: PyInstaller's `--onefile` mode
re-extracts bundled data (the `static/` folder, added via `--add-data` in
`build_executable.py`) to a fresh temp dir (`sys._MEIPASS`) on every launch,
so anything meant to persist across runs — namely `.env` — has to live next
to `sys.executable` instead. Neither branch is exercised by `python3
webserver.py` or the test suite; both only trigger when actually frozen.

PyInstaller doesn't cross-compile, so producing all three (Linux/Windows/
macOS) executables means running `build_executable.py` on each OS —
`.github/workflows/build-executables.yml` does this via a runner matrix,
manually triggered or on a `v*` tag push, and uploads each as a build
artifact. When triggered by a tag push, a second `release` job (gated on
`github.ref` being a tag, since `workflow_dispatch` runs have none) then
downloads all three matrix artifacts and publishes them as assets on a
GitHub Release for that tag via `softprops/action-gh-release`.

Query tuning (appid, gamedir, worker count, per-request timeout) lives in
`steam_browser/config.py`'s `DEFAULT_CONFIG`; everything user-facing is a
filter in the web UI itself, not a config value.

## Architecture

**Backend is Flask + a single background-thread refresh cycle, no database.**
All server state lives in one in-process dict, `_state`, in
`steam_browser/web.py`, guarded by `_state_lock` (a plain `threading.Lock`)
since it's written from a background thread while being read from Flask's
request-handling threads.

- `POST /api/refresh` flips `_state["status"]` to `"refreshing"`
  **synchronously in the route** (the frontend only starts polling when it
  observes that status, so it must never race the worker thread), then
  spawns a **daemon thread** running `_refresh()`, which calls
  `steam_api.fetch_servers()` (Valve's `GetServerList` master-list API, up
  to `max_servers_to_query` candidates) and then fans out A2S_INFO probes
  across a `ThreadPoolExecutor` (`browser.probe_server`, one call per
  candidate, `max_workers` concurrent). Results are appended to
  `_state["servers"]` **as they arrive**, not batched at the end, so a client
  polling mid-refresh sees partial results. Rate-limited
  (`REFRESH_RATE_LIMIT`, `"3/second;30/minute"`) purely as anti-abuse — the
  status guard already dedupes overlapping refreshes.
- `GET /api/servers` just returns a snapshot of `_state` (sorted by latency).
  The frontend polls this every 1.5s (`scheduleNextPoll` in `app.js`) while
  `status == "refreshing"` and stops polling once it flips to `idle`/`error`.
- `POST /api/refresh/stop` sets a module-level `threading.Event`
  (`_cancel_event`) that `_fetch_all`'s probe loop checks after each
  completed future; on cancel it drops not-yet-started futures and returns
  early, keeping whatever was already probed. This is the only
  cancellation mechanism in the codebase — nothing else uses
  `AbortController`/cancel tokens (per-row sidebar queries below use a
  simpler "ignore stale response" pattern instead of a true abort).
- `GET /api/servers/<host>/<port>/players` and `.../rules` are synchronous,
  on-demand A2S_PLAYER/A2S_RULES queries for a single server, run only when
  a user opens that server's sidebar — not part of the background refresh.
- `POST /api/favorites/probe` probes specific `host:port` addresses over
  A2S_INFO directly, bypassing `_state`/the master list entirely. This is
  what makes the Favorites tab show a favorite even when it isn't in the
  last `/api/refresh` result (offline, a listen server excluded by the
  `dedicated` filter in `_fetch_all`, or a refresh just hasn't run yet). It
  reuses `browser.probe_server`, passing it `{"addr": addr}` with no
  `secure`/`gametype` keys — `probe_server` falls back to the VAC/keywords
  fields `a2s._parse_info_response` parses from A2S_INFO itself when those
  keys aren't present, since there's no master-list entry to draw them from.
  Servers that don't respond come back as `{"host", "port", "online": false}`
  rather than being omitted, so the frontend can render them as offline
  instead of them just vanishing. Capped at `MAX_FAVORITES_PROBE_BATCH`
  (200) addresses per request — 413 above that.
- These four on-demand probe routes (`.../players`, `.../rules`, `.../info`,
  `/api/favorites/probe`) are the only ones that make this server send a UDP
  packet to a caller-chosen address, so unlike everything else in the API
  they're abusable independent of the master-list data behind them. Two
  guards, both in `web.py`: `_resolve_probeable_host()` resolves the target
  once and rejects anything that isn't a globally routable IP (`is_global`;
  400 on the single-host routes, silently marked `online: false` in
  `/api/favorites/probe` — consistent with how it already treats malformed
  addresses) — callers then probe the **returned resolved IP**, never the
  original hostname, so a rebinding DNS name can't pass the check with one
  answer and receive the UDP packet at another (`a2s.py` likewise
  `connect()`s its socket, resolving once and ignoring datagrams from other
  sources) — and `@limiter.limit(PROBE_RATE_LIMIT)` (flask-limiter,
  `"10/second;150/minute"` per source IP, in-memory storage since this is a
  single-process app) caps request volume. The rate is sized to absorb one
  sidebar click, which fires players+info+rules simultaneously (see
  `app.js`'s row click handler) plus fast manual browsing — see it as
  anti-abuse, not a UX-facing limit that normal use should ever hit.
- `GET /api/docs` renders a plain-text listing of every `/api/*` route by
  introspecting `app.url_map` and pulling `inspect.getdoc()` off each view
  function at request time — the docstring on a route *is* its
  documentation, there's no separate file to keep in sync. Gated behind
  `app.config["DEV_MODE"]` (set by `--dev`) and 404s otherwise, since it's a
  developer convenience, not something to expose on a public deployment.
  When adding or changing a route, update its docstring, not a separate doc.

Country flags come from `geoip.py`, a best-effort ip-api.com batch lookup
cached in memory for the process lifetime (never invalidated — an IP's
country doesn't change).

**Frontend is a single vanilla ES5 IIFE (`static/app.js`, ~900 lines), no
framework, no build step, no bundler.** It owns a `state` object and a
`render()` that fully re-renders the server table from `state` + the live
filter-form values on every change — there's no virtual DOM or diffing, just
`innerHTML` rebuilding of `#server-rows` each time. `els` is a flat lookup of
every DOM node by id, populated once at load. Filters, column widths, and
favorites persist to `localStorage` under three separate keys (see the
`*_KEY` constants at the top of the file) and are restored before first
render.

A few non-obvious frontend behaviors worth knowing before touching them:
- `els.notEmpty`/`els.notFull` are the only filters Valve's master list
  actually honors server-side (see `steam_api.build_filter`'s docstring
  notes — secure/password filters are silently ignored or broken there), so
  toggling those two checkboxes triggers a full `/api/refresh`, not just a
  client-side re-render like every other filter.
- A single server row's live player count (`patchPlayerCount`) is patched
  directly into the DOM rather than going through `render()`, specifically
  to avoid the full-table re-filter yanking the just-clicked row out of view
  if a filter like "not full" would now exclude it.
- Column resize/autofit drag handles pair clicks by elapsed time (450ms
  window in `lastClick`), not the native `dblclick` event — the resize
  drag's own mousedown/mouseup listeners on the same handle interfere with
  the browser's native double-click distance/timing detection.
- Elements toggled via `.hidden`/`[hidden]` need the corresponding
  `display:none` present in `style.css` — the JS-side attribute toggle is a
  no-op if the CSS override for `[hidden]` isn't there for that element.
- The Favorites tab's rows don't come only from `state.servers` —
  `buildFavoritesRows()` prefers a matching entry there (fresher, from the
  last master-list refresh) and falls back to `state.favoriteServers`, which
  `probeFavorites()` populates by calling `POST /api/favorites/probe` for
  whichever favorites aren't already in `state.servers`. This runs on
  switching to the Favorites tab, and again (unconditionally, `forceAll`)
  when Refresh is clicked while that tab is active — the Refresh button's
  meaning is tab-dependent. A favorite that doesn't respond is kept in the
  list with `online: false` and rendered as a distinct "Offline" row
  (`.offline` in `style.css`) rather than disappearing; those rows are
  exempt from every other filter (name/map/ping/etc.) since there's no data
  to filter on, and are sorted to the bottom regardless of the active sort.

## Domain logic

`maps.py` is a static table (`CAMPAIGNS`) mapping known map codenames to
(campaign, stage) — covers official Valve + DLC + ported L4D1 campaigns.
Unknown/workshop maps resolve to `(None, None)` → displayed as `"-"`.

`browser.parse_mode()` derives a display mode ("Campaign", "Versus", "Team
Scavenge", etc.) from the server's `gametype` tag string (the `sv_tags`
cvar), checked in priority order since a server can carry multiple
overlapping tags.

`a2s.py` implements the raw Source A2S UDP protocol (A2S_INFO, A2S_PLAYER,
A2S_RULES) from scratch — no third-party Source-query library. Two
non-obvious behaviors: multi-packet reassembly is bounded by an **overall**
deadline (per-recv timeouts alone would let a server drip-feeding junk
fragments pin a thread forever), and `latency_ms` times only the final
request/response pair — the timer restarts after the A2S_INFO challenge
handshake, which would otherwise double the reported ping on modern servers.
