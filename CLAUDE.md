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
pip install -r requirements.txt      # requests, flask — that's the entire dependency set

python3 webserver.py                 # serves on http://127.0.0.1:5000
python3 webserver.py --host 0.0.0.0 --port 8080
python3 webserver.py --dev           # also enables GET /api/docs

pip install -r requirements-dev.txt  # adds pytest on top of requirements.txt
pytest                               # tests/, no network — a2s/steam_api/geoip are monkeypatched
```

Requires a `.env` file in the project root with `STEAM-API-KEY=...` (get one
at https://steamcommunity.com/dev/apikey).

There is no linter or build step in this repo. `pytest` is the test suite
(see `tests/conftest.py` for the fixtures that reset `web.py`'s shared
in-process state between tests). `.venv` may also carry a `playwright`
install (Python bindings + chromium) usable for driving the UI in a real
browser — see the `verify` skill.

Query tuning (appid, gamedir, worker count, per-request timeout) lives in
`steam_browser/config.py`'s `DEFAULT_CONFIG`; everything user-facing is a
filter in the web UI itself, not a config value.

## Architecture

**Backend is Flask + a single background-thread refresh cycle, no database.**
All server state lives in one in-process dict, `_state`, in
`steam_browser/web.py`, guarded by `_state_lock` (a plain `threading.Lock`)
since it's written from a background thread while being read from Flask's
request-handling threads.

- `POST /api/refresh` spawns a **daemon thread** running `_refresh()`, which
  calls `steam_api.fetch_servers()` (Valve's `GetServerList` master-list API,
  up to `max_servers_to_query` candidates) and then fans out A2S_INFO probes
  across a `ThreadPoolExecutor` (`browser.probe_server`, one call per
  candidate, `max_workers` concurrent). Results are appended to
  `_state["servers"]` **as they arrive**, not batched at the end, so a client
  polling mid-refresh sees partial results.
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

## Domain logic

`maps.py` is a static table (`CAMPAIGNS`) mapping known map codenames to
(campaign, stage) — covers official Valve + DLC + ported L4D1 campaigns.
Unknown/workshop maps resolve to `(None, None)` → displayed as `"-"`.

`browser.parse_mode()` derives a display mode ("Campaign", "Versus", "Team
Scavenge", etc.) from the server's `gametype` tag string (the `sv_tags`
cvar), checked in priority order since a server can carry multiple
overlapping tags.

`a2s.py` implements the raw Source A2S UDP protocol (A2S_INFO, A2S_PLAYER,
A2S_RULES) from scratch — no third-party Source-query library.
