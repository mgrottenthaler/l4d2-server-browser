"""Config: .env (Steam API key) + in-code defaults (query tuning)."""

import os

DEFAULT_CONFIG = {
    "appid": 550,
    "gamedir": "left4dead2",
    "max_servers_to_query": 10000,  # Valve's GetServerList hard-caps a single response here regardless of limit
    "query_timeout_s": 1.5,
    "max_workers": 50,
}


def load_env(env_path):
    env = {}
    if not os.path.isfile(env_path):
        return env
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def get_steam_api_key(project_root):
    """Return the configured key, or None if none is set yet - callers decide
    how to react (web.py serves the UI regardless and lets the frontend's
    setup banner collect one via set_steam_api_key rather than failing here).
    """
    env = load_env(os.path.join(project_root, ".env"))
    return env.get("STEAM-API-KEY") or env.get("STEAM_API_KEY") or os.environ.get("STEAM_API_KEY")


def set_steam_api_key(project_root, key):
    """Persist a Steam Web API key to .env, replacing any existing
    STEAM-API-KEY/STEAM_API_KEY line rather than duplicating it. Used by the
    frontend's first-run setup banner (POST /api/setup/key) so a key entered
    in the browser survives process restarts the same way one hand-edited
    into .env would.
    """
    env_path = os.path.join(project_root, ".env")
    lines = []
    if os.path.isfile(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
    lines = [
        line for line in lines
        if line.split("=", 1)[0].strip() not in ("STEAM-API-KEY", "STEAM_API_KEY")
    ]
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append("STEAM-API-KEY={}\n".format(key))
    with open(env_path, "w") as f:
        f.writelines(lines)
