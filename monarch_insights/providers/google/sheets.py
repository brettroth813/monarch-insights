"""Sheets exporter: writes tax-prep packets and budget snapshots to a Google Sheet."""

from __future__ import annotations

import asyncio
from typing import Iterable, Sequence

from monarch_insights.observability import get_logger
from monarch_insights.providers.google.auth import GoogleAuth

log = get_logger(__name__)


class SheetsExporter:
    def __init__(self, auth: GoogleAuth) -> None:
        self.auth = auth
        self._service = None

    def service(self):
        if self._service is None:
            self._service = self.auth.build("sheets", "v4")
        return self._service

    async def create_or_open(self, title: str) -> str:
        return await asyncio.to_thread(self._create_or_open_sync, title)

    def _create_or_open_sync(self, title: str) -> str:
        svc = self.service()
        result = svc.spreadsheets().create(
            body={"properties": {"title": title}}, fields="spreadsheetId"
        ).execute()
        return result["spreadsheetId"]

    async def overwrite_tab(
        self,
        spreadsheet_id: str,
        tab_name: str,
        rows: Sequence[Sequence],
    ) -> dict:
        return await asyncio.to_thread(self._overwrite_sync, spreadsheet_id, tab_name, rows)

    def _overwrite_sync(self, spreadsheet_id: str, tab_name: str, rows: Sequence[Sequence]) -> dict:
        svc = self.service()
        # Best-effort tab create
        try:
            svc.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
            ).execute()
        except Exception:
            pass
        svc.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=f"{tab_name}!A:Z", body={}
        ).execute()
        return (
            svc.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=f"{tab_name}!A1",
                valueInputOption="USER_ENTERED",
                body={"values": list(rows)},
            )
            .execute()
        )
