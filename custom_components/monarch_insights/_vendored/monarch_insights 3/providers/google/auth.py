"""Google OAuth Installed-App auth helper.

Bootstrap from a Mac (browser available), then move ``token.json`` to the Pi. The
``google-auth`` library handles refresh-token rotation automatically.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from monarch_insights.observability import get_logger

log = get_logger(__name__)

DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
)

DEFAULT_TOKEN_PATH = Path.home() / ".config" / "monarch-insights" / "google_token.json"
DEFAULT_CLIENT_PATH = Path.home() / ".config" / "monarch-insights" / "google_client.json"


class GoogleAuth:
    def __init__(
        self,
        *,
        client_secrets_path: Path = DEFAULT_CLIENT_PATH,
        token_path: Path = DEFAULT_TOKEN_PATH,
        scopes: Sequence[str] = DEFAULT_SCOPES,
    ) -> None:
        self.client_secrets_path = Path(client_secrets_path)
        self.token_path = Path(token_path)
        self.scopes = list(scopes)
        self._creds = None

    def credentials(self):
        if self._creds is not None:
            return self._creds
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Google libs missing. Install: google-api-python-client google-auth google-auth-oauthlib"
            ) from exc

        if not self.token_path.exists():
            raise RuntimeError(
                f"Google token not found at {self.token_path}. "
                "Run `monarch-insights google bootstrap` once on a machine with a browser."
            )

        creds = Credentials.from_authorized_user_file(str(self.token_path), self.scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.token_path.write_text(creds.to_json())
            # Google's library doesn't chmod on its own; enforce owner-only so the token
            # doesn't leak to other users on multi-tenant hosts.
            os.chmod(self.token_path, 0o600)
        self._creds = creds
        return creds

    def bootstrap(self) -> None:
        """Run the installed-app browser flow and persist a refresh token."""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("google-auth-oauthlib missing") from exc

        if not self.client_secrets_path.exists():
            raise RuntimeError(
                f"Client secrets file not found at {self.client_secrets_path}. "
                "Download from console.cloud.google.com → APIs & Services → Credentials."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secrets_path), self.scopes
        )
        creds = flow.run_local_server(port=0, open_browser=True)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json())
        os.chmod(self.token_path, 0o600)
        log.info(
            "google.bootstrap.completed",
            extra={"token_path": str(self.token_path)},
        )

    def build(self, service: str, version: str):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("google-api-python-client missing") from exc

        return build(service, version, credentials=self.credentials(), cache_discovery=False)
