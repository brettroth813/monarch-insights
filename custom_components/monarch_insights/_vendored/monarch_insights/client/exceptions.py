"""Custom exception hierarchy for the Monarch client."""

from __future__ import annotations

from typing import Any


class MonarchError(Exception):
    """Base for every error this library raises."""

    def __init__(self, message: str, *, payload: Any | None = None) -> None:
        super().__init__(message)
        self.payload = payload


class MonarchAuthError(MonarchError):
    """Raised when authentication fails — bad credentials, revoked token, expired session."""


class MonarchMFARequired(MonarchAuthError):
    """Login succeeded up to MFA. Caller must collect the code and call ``submit_mfa``."""

    def __init__(self, message: str = "Multi-factor authentication required", *, payload: Any | None = None) -> None:
        super().__init__(message, payload=payload)


class MonarchNotFound(MonarchError):
    """Resource (account, transaction, holding, etc.) was not found."""


class MonarchRateLimited(MonarchError):
    """Backend asked us to slow down. ``retry_after`` is seconds, when known."""

    def __init__(
        self,
        message: str = "Monarch rate-limited the request",
        *,
        retry_after: float | None = None,
        payload: Any | None = None,
    ) -> None:
        super().__init__(message, payload=payload)
        self.retry_after = retry_after


class MonarchTimeout(MonarchError):
    """Request exceeded its deadline."""


class MonarchSchemaDrift(MonarchError):
    """A response shape didn't match what we expected — Monarch likely changed their schema.

    We catch this above the model layer so we can keep partial functionality going while
    surfacing exactly which query/field broke for fast triage.
    """

    def __init__(self, operation: str, message: str, *, payload: Any | None = None) -> None:
        super().__init__(f"[{operation}] {message}", payload=payload)
        self.operation = operation
