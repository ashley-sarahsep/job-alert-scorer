"""One-time manual OAuth helper for environments without a reachable browser.

The normal Gmail flow (gmail_client.run_local_server) needs Google to redirect
to localhost on the *same machine* running the code. That doesn't work when the
code runs in a remote/cloud container, because the container's localhost isn't
reachable from your browser.

This helper does the desktop-app flow by hand in two steps:

    python src/remote_auth.py url
        -> prints an authorization URL. Open it, approve access, and copy the
           code Google gives you (or the full localhost URL it redirects to).

    python src/remote_auth.py exchange "<code-or-redirect-url>"
        -> exchanges that code for a token and writes token.json.

After this, the rest of the tool (src/main.py) uses token.json normally.

Note: on your own laptop you don't need this. There, `python src/main.py`
opens a browser and finishes the flow automatically.
"""

import json
import os
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Allow the http://localhost redirect and any scope drift Google adds.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google_auth_oauthlib.flow import Flow  # noqa: E402

from config_loader import load_config  # noqa: E402
from gmail_reader import SCOPES  # noqa: E402

REDIRECT_URI = "http://localhost"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".auth_state.json")


def _config_from_argv(argv):
    """Pull an optional --config PATH out of argv; return (config, rest)."""
    config_path = None
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--config" and i + 1 < len(argv):
            config_path = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    return load_config(config_path), rest


def _make_flow(credentials_file):
    return Flow.from_client_secrets_file(
        credentials_file, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )


def cmd_url(config):
    flow = _make_flow(config["credentials_file"])
    auth_url, _state = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump({"code_verifier": flow.code_verifier}, fh)
    print("\n1. Open this URL in your browser and approve access:\n")
    print(auth_url)
    print(
        "\n2. After approving, your browser will try to open a 'http://localhost/...'\n"
        "   page that fails to load -- that's expected. Copy the FULL address from\n"
        "   the address bar (it contains '?code=...'), or just the code value, and\n"
        "   run:\n\n"
        '   python src/remote_auth.py exchange "<paste-it-here>"\n'
    )


def _extract_code(value):
    value = value.strip().strip('"').strip("'")
    if value.startswith("http"):
        params = parse_qs(urlparse(value).query)
        if "code" not in params:
            raise ValueError("No 'code' parameter found in that URL.")
        return params["code"][0]
    return value


def cmd_exchange(config, raw_value):
    code = _extract_code(raw_value)
    code_verifier = None
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            code_verifier = json.load(fh).get("code_verifier")

    flow = _make_flow(config["credentials_file"])
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)

    creds = flow.credentials
    with open(config["token_file"], "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    print(f"\nSuccess. Token written to {config['token_file']}.")
    print("You can now run: python src/main.py --score --email")


def main(argv):
    config, rest = _config_from_argv(argv)
    if len(rest) >= 1 and rest[0] == "url":
        cmd_url(config)
    elif len(rest) >= 2 and rest[0] == "exchange":
        cmd_exchange(config, rest[1])
    else:
        print(__doc__)
        print("Usage:\n  python src/remote_auth.py [--config PATH] url\n"
              '  python src/remote_auth.py [--config PATH] exchange "<code-or-redirect-url>"')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
