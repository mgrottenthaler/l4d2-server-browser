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

Options:

- `--host HOST` — interface to bind (default: `127.0.0.1`)
- `--port PORT` — port to bind (default: `5000`)

Query tuning (appid, gamedir, worker count, timeouts) lives in
`steam_browser/config.py`'s `DEFAULT_CONFIG` — everything user-facing is a
filter in the web UI itself.
