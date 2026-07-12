#!/usr/bin/env python3
"""Standalone Steam login tool: logs in via the modern IAuthenticationService
flow and caches a refresh token to disk, so other scripts (e.g. a future
query_difficulty.py) can start a Steam session without a password or 2FA
prompt every time.

Why not the simple SteamClient.login()? Steam has deprecated plain
password-based CM login for accounts with Steam Guard enabled -- it now
generically rejects it as "invalid password" regardless of whether the
password is actually correct. Real clients instead go through this REST
flow: RSA-encrypt the password, start an auth session, satisfy whatever
Steam Guard confirmation it asks for (mobile authenticator code, email
code, or just approving in the Steam mobile app), then trade the session
for a refresh token. That refresh token is handed to the CM connection
directly (CMsgClientLogon.access_token) instead of a password.

Usage:
    python3 scripts/steam_login.py

Credentials: put STEAM_USERNAME / STEAM_PASSWORD in a .env file next to
this script's project root, or you'll be prompted for them. Whatever
Steam Guard confirmation your account needs is also prompted for here,
interactively.

Output: writes {account_name, refresh_token} to .steam_refresh_token.json
in the project root (gitignored, chmod 600). Delete that file (or just
rerun this script) to force a fresh login.
"""

import base64
import getpass
import json
import os
import sys
import time

# The installed `steam` package's generated _pb2.py files predate the
# installed protobuf package's C++ backend requirements; the pure-Python
# implementation is the only one that can load them. Must be set before
# `steam.client` (and therefore google.protobuf) is imported anywhere.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import requests
from Cryptodome.Cipher import PKCS1_v1_5
from Cryptodome.PublicKey import RSA
from steam.client import SteamClient
from steam.core.msg import MsgProto
from steam.enums import EOSType, EResult
from steam.enums.emsg import EMsg
from steam.steamid import SteamID
from steam.utils import ip4_to_int

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
SESSION_CACHE_PATH = os.path.join(PROJECT_ROOT, ".steam_refresh_token.json")

API_BASE = "https://api.steampowered.com"

PLATFORM_TYPE_STEAM_CLIENT = 1  # k_EAuthTokenPlatformType_SteamClient
SESSION_PERSISTENCE_PERSISTENT = 1  # k_ESessionPersistence_Persistent

GUARD_TYPE_NONE = 1  # k_EAuthSessionGuardType_None
GUARD_TYPE_EMAIL_CODE = 2  # k_EAuthSessionGuardType_EmailCode
GUARD_TYPE_DEVICE_CODE = 3  # k_EAuthSessionGuardType_DeviceCode
GUARD_TYPE_DEVICE_CONFIRMATION = 4  # k_EAuthSessionGuardType_DeviceConfirmation


class SteamAuthError(Exception):
    pass


def load_env(path):
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def save_cached_session(account_name, steamid, refresh_token):
    with open(SESSION_CACHE_PATH, "w") as f:
        json.dump(
            {"account_name": account_name, "steamid": steamid, "refresh_token": refresh_token}, f
        )
    os.chmod(SESSION_CACHE_PATH, 0o600)


def _api_call(method_path, params, http_method="post"):
    url = "{}/{}".format(API_BASE, method_path)
    if http_method == "get":
        resp = requests.get(url, params=params, timeout=15)
    else:
        resp = requests.post(url, data=params, timeout=15)
    if resp.status_code != 200:
        detail = resp.headers.get("X-Error_Message") or resp.text[:200]
        raise SteamAuthError(
            "{} failed: HTTP {} ({})".format(method_path, resp.status_code, detail)
        )
    return resp.json().get("response", {})


def get_rsa_key(account_name):
    return _api_call(
        "IAuthenticationService/GetPasswordRSAPublicKey/v1/",
        {"account_name": account_name},
        http_method="get",
    )


def encrypt_password(password, mod_hex, exp_hex):
    key = RSA.construct((int(mod_hex, 16), int(exp_hex, 16)))
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(password.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")


def begin_auth_session(account_name, password):
    rsa = get_rsa_key(account_name)
    encrypted_password = encrypt_password(password, rsa["publickey_mod"], rsa["publickey_exp"])
    return _api_call(
        "IAuthenticationService/BeginAuthSessionViaCredentials/v1/",
        {
            "account_name": account_name,
            "encrypted_password": encrypted_password,
            "encryption_timestamp": rsa["timestamp"],
            "remember_login": True,
            "platform_type": PLATFORM_TYPE_STEAM_CLIENT,
            "persistence": SESSION_PERSISTENCE_PERSISTENT,
            "website_id": "Client",
            "device_friendly_name": "l4d2-steam-browser",
        },
    )


def submit_guard_code(client_id, steamid, code, code_type):
    _api_call(
        "IAuthenticationService/UpdateAuthSessionWithSteamGuardCode/v1/",
        {"client_id": client_id, "steamid": steamid, "code": code, "code_type": code_type},
    )


def poll_auth_session(client_id, request_id, interval, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _api_call(
            "IAuthenticationService/PollAuthSessionStatus/v1/",
            {"client_id": client_id, "request_id": request_id},
        )
        if result.get("refresh_token"):
            return result
        time.sleep(interval)
    raise SteamAuthError("Timed out waiting for Steam Guard confirmation")


def resolve_guard_confirmation(session):
    confirmations = session.get("allowed_confirmations", [])
    types = {c["confirmation_type"] for c in confirmations}

    if not types or GUARD_TYPE_NONE in types:
        return  # nothing to satisfy

    if GUARD_TYPE_DEVICE_CONFIRMATION in types:
        print("Approve the login request in your Steam Mobile app, then wait...")
        return  # PollAuthSessionStatus will pick up the approval, no code needed

    if GUARD_TYPE_DEVICE_CODE in types:
        code = input("Enter your Steam Mobile Authenticator (2FA) code: ").strip()
        submit_guard_code(session["client_id"], session["steamid"], code, GUARD_TYPE_DEVICE_CODE)
        return

    if GUARD_TYPE_EMAIL_CODE in types:
        code = input("Enter the Steam Guard code emailed to you: ").strip()
        submit_guard_code(session["client_id"], session["steamid"], code, GUARD_TYPE_EMAIL_CODE)
        return

    raise SteamAuthError("Unsupported Steam Guard confirmation type(s): {}".format(types))


def client_logon_with_refresh_token(client, steamid, refresh_token, timeout=30):
    """Log in to the Steam CM network with a refresh token obtained from
    IAuthenticationService, instead of a password or the old login_key.
    SteamClient.login() doesn't support this, so this replicates its
    internals with `access_token` in place of `password`/`login_key`.

    Unlike a fresh password login (where CM doesn't know who you are yet
    and a placeholder SteamID is fine), a token identifies a specific
    account already -- the header must carry that real SteamID or the
    logon is rejected as an invalid credential."""
    eresult = client._pre_login()
    if eresult != EResult.OK:
        return eresult

    message = MsgProto(EMsg.ClientLogon)
    message.header.steamid = SteamID(steamid)
    message.body.protocol_version = 65580
    message.body.client_package_version = 1561159470
    message.body.client_os_type = EOSType.Windows10
    message.body.client_language = "english"
    message.body.should_remember_password = True
    message.body.supports_rate_limit_response = True
    message.body.chat_mode = client.chat_mode
    message.body.obfuscated_private_ip.v4 = ip4_to_int(client.connection.local_address) ^ 0xF00DBAAD
    message.body.access_token = refresh_token

    client.send(message)
    resp = client.wait_msg(EMsg.ClientLogOnResponse, timeout=timeout)

    if resp and resp.body.eresult == EResult.OK:
        client.sleep(0.5)

    return EResult(resp.body.eresult) if resp else EResult.Fail


def main():
    env = load_env(ENV_PATH)
    account_name = env.get("STEAM_USERNAME") or input("Steam username: ").strip()
    password = env.get("STEAM_PASSWORD") or getpass.getpass("Steam password: ")

    print("Starting Steam auth session for {}...".format(account_name))
    session = begin_auth_session(account_name, password)
    resolve_guard_confirmation(session)

    print("Waiting for Steam to confirm login...")
    result = poll_auth_session(session["client_id"], session["request_id"], session.get("interval", 5))
    refresh_token = result["refresh_token"]

    print("Verifying refresh token against the Steam CM network...")
    client = SteamClient()
    eresult = client_logon_with_refresh_token(client, session["steamid"], refresh_token)
    if eresult != EResult.OK:
        raise SteamAuthError("CM logon with fresh refresh token failed: {}".format(eresult))

    save_cached_session(account_name, session["steamid"], refresh_token)
    print("Logged in as {} ({}).".format(client.username or account_name, client.steam_id))
    print("Session cached to {}".format(SESSION_CACHE_PATH))
    client.logout()


if __name__ == "__main__":
    try:
        main()
    except SteamAuthError as exc:
        print("Login failed: {}".format(exc), file=sys.stderr)
        sys.exit(1)
