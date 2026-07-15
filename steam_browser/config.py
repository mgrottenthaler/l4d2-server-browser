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
    env = load_env(os.path.join(project_root, ".env"))
    key = env.get("STEAM-API-KEY") or env.get("STEAM_API_KEY") or os.environ.get("STEAM_API_KEY")
    if not key:
        raise RuntimeError(
            "Steam Web API key not found. Add STEAM-API-KEY=... to .env"
        )
    return key
