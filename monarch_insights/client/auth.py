"""Authentication, MFA, and encrypted session storage for Monarch Money.

Monarch's auth flow (as of Jan 2026 endpoint move):

1. POST ``/auth/login/`` with email + password.
   - 200 → token in body.
   - 403 with ``error_code == 'MFA_REQUIRED'`` → call MFA endpoint.
2. POST ``/auth/login/`` again with ``totp`` (6-digit) when authenticator,
   or ``email_otp`` when email-based.
3. Use ``Authorization: Token <token>`` for all GraphQL calls.

We persist the token (and a device UUID we generate on first run) to disk under a
fernet-encrypted blob keyed by a per-host machine id, so leaking the file alone doesn't
hand over the token.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import platform
import socket
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp
from cryptography.fernet import Fernet, InvalidToken

from monarch_insights.client.exceptions import (
    MonarchAuthError,
    MonarchError,
    MonarchMFARequired,
)

DEFAULT_BASE_URL = "https://api.monarch.com"
LEGACY_BASE_URL = "https://api.monarchmoney.com"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://app.monarchmoney.com",
    "User-Agent": "MonarchInsights/0.1 (+home-assistant)",
    "x-cio-client-platform": "web",
    "x-cio-site-id": "monarch-money",
}

SESSION_FILENAME = "session.enc"


def _machine_secret() -> bytes:
    """A best-effort stable per-machine secret.

    Not a hardware key — just enough entropy that copying the encrypted blob to a
    different machine yields ``InvalidToken`` instead of silently working.
    """
    parts = [
        platform.node(),
        platform.system(),
        socket.gethostname(),
        str(uuid.getnode()),  # MAC-derived
    ]
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_machine_secret())


@dataclass
class Session:
    token: str
    device_uuid: str
    user_email: str | None = None
    expires_at: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "device_uuid": self.device_uuid,
            "user_email": self.user_email,
            "expires_at": self.expires_at,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            token=data["token"],
            device_uuid=data["device_uuid"],
            user_email=data.get("user_email"),
            expires_at=data.get("expires_at"),
            extra=data.get("extra", {}),
        )


class MonarchAuth:
    """High-level auth facade.

    Typical flow:
        auth = MonarchAuth()
        try:
            await auth.login(email, password)
        except MonarchMFARequired:
            await auth.submit_mfa(email, password, code)
        token = auth.session.token
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session_dir: Path | None = None,
        device_uuid: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_dir = (
            session_dir or Path.home() / ".config" / "monarch-insights"
        )
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_path = self.session_dir / SESSION_FILENAME
        self.device_uuid = device_uuid or str(uuid.uuid4())
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Session | None = None

    # ------------------------------------------------------------------ persistence

    def save(self) -> None:
        if self.session is None:
            raise MonarchError("No session to save")
        blob = json.dumps(self.session.to_dict()).encode()
        encrypted = _fernet().encrypt(blob)
        self.session_path.write_bytes(encrypted)
        os.chmod(self.session_path, 0o600)

    def load(self) -> Session | None:
        if not self.session_path.exists():
            return None
        try:
            decrypted = _fernet().decrypt(self.session_path.read_bytes())
        except InvalidToken as exc:
            raise MonarchAuthError(
                "Could not decrypt saved session — was it copied from another machine?"
            ) from exc
        self.session = Session.from_dict(json.loads(decrypted))
        return self.session

    def clear(self) -> None:
        self.session = None
        if self.session_path.exists():
            self.session_path.unlink()

    # ------------------------------------------------------------------ login

    def _request_headers(self) -> dict[str, str]:
        h = dict(DEFAULT_HEADERS)
        h["device-uuid"] = self.device_uuid
        return h

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with aiohttp.ClientSession(timeout=self.timeout) as http:
            async with http.post(url, json=body, headers=self._request_headers()) as resp:
                try:
                    payload = await resp.json()
                except aiohttp.ContentTypeError:
                    payload = {"raw": await resp.text()}
                if 200 <= resp.status < 300:
                    return payload
                if resp.status == 403 and self._is_mfa_required(payload):
                    raise MonarchMFARequired(payload=payload)
                if resp.status in (401, 403):
                    raise MonarchAuthError(
                        f"{resp.status} authenticating with Monarch", payload=payload
                    )
                raise MonarchError(
                    f"Monarch auth call failed: {resp.status}", payload=payload
                )

    @staticmethod
    def _is_mfa_required(payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        if payload.get("error_code") == "MFA_REQUIRED":
            return True
        detail = str(payload.get("detail", "")).lower()
        return "mfa" in detail or "multi-factor" in detail or "totp" in detail

    async def login(
        self,
        email: str,
        password: str,
        *,
        save: bool = True,
    ) -> Session:
        body = {
            "email": email,
            "password": password,
            "trusted_device": True,
            "supports_mfa": True,
            "supports_email_otp": True,
        }
        payload = await self._post("/auth/login/", body)
        token = payload.get("token") or payload.get("auth_token")
        if not token:
            raise MonarchAuthError(
                "Login succeeded but no token returned", payload=payload
            )
        self.session = Session(
            token=token,
            device_uuid=self.device_uuid,
            user_email=email,
            extra={"raw_login": {k: v for k, v in payload.items() if k != "token"}},
        )
        if save:
            self.save()
        return self.session

    async def submit_mfa(
        self,
        email: str,
        password: str,
        code: str,
        *,
        method: str = "totp",
        save: bool = True,
    ) -> Session:
        """Re-issue ``/auth/login/`` with the MFA code attached.

        ``method`` should be ``"totp"`` for authenticator apps or ``"email_otp"`` for
        email codes — the field name on the payload changes accordingly.
        """
        body = {
            "email": email,
            "password": password,
            "trusted_device": True,
            "supports_mfa": True,
            "supports_email_otp": True,
        }
        body[method] = code
        payload = await self._post("/auth/login/", body)
        token = payload.get("token") or payload.get("auth_token")
        if not token:
            raise MonarchAuthError(
                "MFA submitted but no token returned", payload=payload
            )
        self.session = Session(
            token=token,
            device_uuid=self.device_uuid,
            user_email=email,
        )
        if save:
            self.save()
        return self.session

    async def request_email_otp(self, email: str) -> None:
        """Trigger Monarch to email a one-time code."""
        await self._post("/auth/email-otp/", {"email": email})

    async def logout(self) -> None:
        if self.session is None:
            return
        try:
            url = f"{self.base_url}/auth/logout/"
            headers = self._request_headers()
            headers["Authorization"] = f"Token {self.session.token}"
            async with aiohttp.ClientSession(timeout=self.timeout) as http:
                with contextlib_suppress():
                    await http.post(url, headers=headers)
        finally:
            self.clear()


def contextlib_suppress():
    import contextlib

    return contextlib.suppress(Exception)


__all__ = ["MonarchAuth", "Session", "DEFAULT_BASE_URL", "LEGACY_BASE_URL"]


# Defensive: make sure the module is importable without aiohttp event loop running.
async def _smoke() -> None:
    auth = MonarchAuth()
    try:
        auth.load()
    except MonarchAuthError:
        pass


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_smoke())
