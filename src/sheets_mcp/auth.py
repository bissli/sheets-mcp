"""Google credentials from a key file, a stored OAuth token, or ADC.
"""
import json
import os
from pathlib import Path

import google.auth
from google.auth.credentials import Credentials
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
    ]


def token_path() -> Path:
    """Where `sheets-mcp login` stores the OAuth token: sheets-mcp/token.json
    under $XDG_CONFIG_HOME, else under ~/.config.
    """
    config_home = os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config'
    return Path(config_home) / 'sheets-mcp' / 'token.json'


def load_credentials(path: Path | None) -> Credentials:
    """Credentials for the Sheets and Drive scopes.

    Parameters
    ----------
    path : Path or None
        A service account key, or a Desktop app OAuth client whose token
        `sheets-mcp login` stored. None uses Application Default
        Credentials.

    Returns
    -------
    Credentials
        Refreshes its own access token on the first request.

    Raises
    ------
    SystemExit
        The file is neither kind, or the OAuth client has no stored token.
    """
    if path is None:
        credentials, _ = google.auth.default(scopes=SCOPES)
        return credentials
    info = json.loads(path.read_text())
    if info.get('type') == 'service_account':
        return service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES)
    if 'installed' not in info:
        raise SystemExit(
            f'{path} is neither a service account key nor a Desktop app '
            'OAuth client')
    if not token_path().exists():
        raise SystemExit(f'no stored token: run sheets-mcp login {path}')
    return UserCredentials.from_authorized_user_file(str(token_path()), SCOPES)


def login(path: Path) -> Path:
    """Run the browser consent for the OAuth client at path and store the
    token, readable by the owner only. Returns the token's path.
    """
    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    credentials = flow.run_local_server(port=0)
    stored = token_path()
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.touch(mode=0o600, exist_ok=True)
    stored.chmod(0o600)
    stored.write_text(credentials.to_json())
    return stored
