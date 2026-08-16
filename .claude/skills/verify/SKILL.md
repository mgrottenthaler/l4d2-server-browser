---
name: verify
description: Verify frontend/backend changes to l4d2-server-browser by driving the real web UI in a browser
---

# Running the app

```bash
source .venv/bin/activate   # flask already installed here
python3 webserver.py        # serves on http://127.0.0.1:5000, needs .env with STEAM-API-KEY (already present)
```

The live Steam master server list is **not reachable from this sandbox** (no
outbound network) — `/api/servers` will return an empty list forever, so the
table never gets rows and stays `hidden` (see `els.table.hidden = rows.length
=== 0` in `static/app.js`). Don't wait on real data.

# Driving it with Playwright

Use the Python `playwright` package, not Node/npx — npx only resolves to a
Windows binary in this WSL environment and can't reach `127.0.0.1` cleanly.
It's not always installed in `.venv` (check with `.venv/bin/pip show
playwright`); if missing, `.venv/bin/pip install playwright` then
`.venv/bin/python -m playwright install chromium` (no `--with-deps`, that
needs root/sudo which isn't available).

To get rows on screen, intercept `/api/servers` and fulfill with a fake
payload matching the real response shape (`{servers, status, error,
last_updated, candidate_count}` — servers is a bare array of server objects,
NOT the response itself):

```python
await page.route("**/api/servers", lambda route: route.fulfill(
    status=200, content_type="application/json",
    body=json.dumps({"servers": [...], "status": "ready", "error": None,
                      "last_updated": 1700000000, "candidate_count": N})
))
await page.goto("http://127.0.0.1:5000/")
await page.wait_for_selector("#server-rows tr")
```

Server object fields used by the UI: `host, port, name, mode, campaign,
stage, players, max_players, latency_ms, secure, password_protected,
country_code, country_name`.

# Gotchas already known (see also memory)

- Column resize/autofit and their localStorage persistence live in
  `static/app.js` around `initColumnWidths`/`persistColumnWidths` — key is
  `steamBrowser.columnWidths.v1`, keyed by `th.dataset.key` (falls back to
  the `th`'s first class name for columns without `data-key`, e.g.
  `col-ip`).
- Elements toggled via `.hidden`/`[hidden]` need `display:none` in CSS or JS
  toggles are a no-op visually (see project memory).
- Double-click-to-autofit is paired by time (450ms), not native `dblclick` —
  simulate with two `page.mouse.click()` calls ~100ms apart on the
  `.col-resizer` handle, not a single `dblclick`.
