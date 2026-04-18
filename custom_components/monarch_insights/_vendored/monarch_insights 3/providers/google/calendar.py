"""Calendar sync: tax dates, RMD, vest schedule, recurring bills.

Uses ``extendedProperties.private`` to make events idempotent — if we already created an
event for a given source key, we update instead of duplicating.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Iterable

from monarch_insights.observability import get_logger
from monarch_insights.providers.google.auth import GoogleAuth

log = get_logger(__name__)

CALENDAR_NAME = "Monarch Insights"

ESTIMATED_TAX_DUE_DATES = [
    ("Q1 Estimated Tax", date(2026, 4, 15)),
    ("Q2 Estimated Tax", date(2026, 6, 15)),
    ("Q3 Estimated Tax", date(2026, 9, 15)),
    ("Q4 Estimated Tax", date(2027, 1, 15)),
]


@dataclass
class FinanceEvent:
    key: str  # idempotency key — anything stable per source
    title: str
    on_date: date
    description: str | None = None
    all_day: bool = True
    end_date: date | None = None


class CalendarSync:
    def __init__(self, auth: GoogleAuth) -> None:
        self.auth = auth
        self._service = None
        self._calendar_id: str | None = None

    def service(self):
        if self._service is None:
            self._service = self.auth.build("calendar", "v3")
        return self._service

    def _ensure_calendar(self) -> str:
        if self._calendar_id:
            return self._calendar_id
        svc = self.service()
        page_token = None
        while True:
            page = svc.calendarList().list(pageToken=page_token).execute()
            for c in page.get("items", []):
                if c.get("summary") == CALENDAR_NAME:
                    self._calendar_id = c["id"]
                    return self._calendar_id
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        created = svc.calendars().insert(body={"summary": CALENDAR_NAME}).execute()
        self._calendar_id = created["id"]
        return self._calendar_id

    async def upsert_event(self, event: FinanceEvent) -> dict:
        return await asyncio.to_thread(self._upsert_sync, event)

    def _upsert_sync(self, event: FinanceEvent) -> dict:
        svc = self.service()
        cal_id = self._ensure_calendar()
        existing = (
            svc.events()
            .list(
                calendarId=cal_id,
                privateExtendedProperty=f"finance_key={event.key}",
            )
            .execute()
        )
        body = {
            "summary": event.title,
            "description": event.description or "",
            "extendedProperties": {"private": {"finance_key": event.key}},
        }
        if event.all_day:
            body["start"] = {"date": event.on_date.isoformat()}
            body["end"] = {"date": (event.end_date or event.on_date).isoformat()}
        else:
            iso = datetime.combine(event.on_date, time(9, 0), tzinfo=timezone.utc).isoformat()
            body["start"] = {"dateTime": iso, "timeZone": "UTC"}
            body["end"] = {"dateTime": iso, "timeZone": "UTC"}
        if existing.get("items"):
            event_id = existing["items"][0]["id"]
            return svc.events().patch(calendarId=cal_id, eventId=event_id, body=body).execute()
        return svc.events().insert(calendarId=cal_id, body=body).execute()

    async def sync_tax_dates(self, dates: Iterable[tuple[str, date]] = ESTIMATED_TAX_DUE_DATES) -> list[dict]:
        results = []
        for label, due_date in dates:
            event = FinanceEvent(
                key=f"tax/{label}/{due_date.isoformat()}",
                title=f"💵 {label}",
                on_date=due_date,
                description="Auto-created by Monarch Insights",
            )
            results.append(await self.upsert_event(event))
        return results

    async def sync_rmd(self, birth_year: int) -> dict:
        rmd_year = birth_year + 73  # Secure 2.0
        return await self.upsert_event(
            FinanceEvent(
                key=f"rmd/{rmd_year}",
                title="🏦 RMD due",
                on_date=date(rmd_year, 12, 31),
                description="Required minimum distribution deadline.",
            )
        )

    async def sync_vest_dates(self, vests: Iterable[dict]) -> list[dict]:
        results = []
        for v in vests:
            results.append(
                await self.upsert_event(
                    FinanceEvent(
                        key=f"vest/{v.get('grant_id')}/{v.get('date')}",
                        title=f"📈 RSU vest: {v.get('shares')} sh",
                        on_date=date.fromisoformat(v["date"]),
                        description=f"Grant {v.get('grant_id')}",
                    )
                )
            )
        return results
