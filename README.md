# steam-browser

A Left 4 Dead 2 server browser. Queries the Steam master server list, pings
candidates with A2S, and resolves each server's map to its campaign/stage
and game mode. Available as a CLI and as a web UI styled after Steam's own
server browser.

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

### CLI

```bash
python3 main.py
```

Options:

- `--config PATH` — path to a JSON config file (default: `config.json`)
- `--max-latency MS` — override `max_latency_ms` from the config
- `--name-filter TEXT` — override `name_filter` (case-insensitive substring match)

### Web UI

```bash
python3 webserver.py
```

Then open http://127.0.0.1:5000 in a browser. It fetches and pings every
candidate server matching the config's `appid`/`gamedir`/`dedicated_secure`
settings in the background, and the page filters/sorts them live — by name,
game mode, max ping, and empty/full/password state — without re-querying,
the same way Steam's own server browser works. Click column headers to sort,
and use the Refresh button to re-query the master list.

Options:

- `--config PATH` — path to a JSON config file (default: `config.json`)
- `--host HOST` — interface to bind (default: `127.0.0.1`)
- `--port PORT` — port to bind (default: `5000`)

## Configuration

`config.json` controls query behavior, e.g.:

```json
{
  "appid": 550,
  "gamedir": "left4dead2",
  "max_latency_ms": 150,
  "max_servers_to_query": 500,
  "query_timeout_s": 1.5,
  "max_workers": 50,
  "name_filter": "Valve",
  "not_empty": true,
  "not_full": true,
  "no_password": true,
  "dedicated_secure": true
}
```

See `steam_browser/config.py` for the full list of defaults.
