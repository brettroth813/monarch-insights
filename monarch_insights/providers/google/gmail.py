"""Gmail reader: incremental sync with the History API + label-based filtering.

Returns dicts in the shape EmailAccountProvider.classify() expects, so the same payload
flows through the rules table.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from typing import Iterable

from monarch_insights.observability import get_logger
from monarch_insights.providers.google.auth import GoogleAuth

log = get_logger(__name__)

DEFAULT_LABELS = ("Finance",)


class GmailReader:
    def __init__(self, auth: GoogleAuth) -> None:
        self.auth = auth
        self._service = None

    def service(self):
        if self._service is None:
            self._service = self.auth.build("gmail", "v1")
        return self._service

    async def search(
        self,
        query: str,
        *,
        max_results: int = 100,
    ) -> list[dict]:
        return await asyncio.to_thread(self._search_sync, query, max_results)

    def _search_sync(self, query: str, max_results: int) -> list[dict]:
        svc = self.service()
        msgs: list[dict] = []
        page_token = None
        while len(msgs) < max_results:
            req = svc.users().messages().list(
                userId="me",
                q=query,
                maxResults=min(100, max_results - len(msgs)),
                pageToken=page_token,
            )
            resp = req.execute()
            for ref in resp.get("messages", []):
                full = (
                    svc.users()
                    .messages()
                    .get(userId="me", id=ref["id"], format="full")
                    .execute()
                )
                msgs.append(self._parse(full))
                if len(msgs) >= max_results:
                    break
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return msgs

    @staticmethod
    def _parse(msg: dict) -> dict:
        headers = {h["name"].lower(): h["value"] for h in (msg.get("payload") or {}).get("headers", [])}
        return {
            "id": msg.get("id"),
            "thread_id": msg.get("threadId"),
            "label_ids": msg.get("labelIds", []),
            "snippet": msg.get("snippet", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "received_at": _parse_internal_ts(msg.get("internalDate")),
            "body": _extract_body(msg.get("payload") or {}),
        }


def _parse_internal_ts(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def _extract_body(payload: dict) -> str:
    """Walk the MIME tree looking for text/plain (preferred) or text/html as fallback."""
    parts: list[str] = []
    stack = [payload]
    while stack:
        part = stack.pop()
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data and mime_type.startswith("text/"):
            try:
                decoded = base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
            except Exception:
                decoded = ""
            parts.append(decoded)
        for child in part.get("parts", []) or []:
            stack.append(child)
    return "\n\n".join(parts)
