"""Day-by-day cashflow projection from recurring streams + manual events."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from monarch_insights.models import RecurringStream
from monarch_insights.models.recurring import RecurrenceFrequency


@dataclass
class ProjectedDay:
    on_date: date
    starting_balance: Decimal
    inflows: list[tuple[str, Decimal]] = field(default_factory=list)
    outflows: list[tuple[str, Decimal]] = field(default_factory=list)
    ending_balance: Decimal = Decimal(0)

    @property
    def net(self) -> Decimal:
        return sum((a for _, a in self.inflows), Decimal(0)) - sum((a for _, a in self.outflows), Decimal(0))


_FREQUENCY_DAYS = {
    RecurrenceFrequency.DAILY: 1,
    RecurrenceFrequency.WEEKLY: 7,
    RecurrenceFrequency.BIWEEKLY: 14,
    RecurrenceFrequency.SEMI_MONTHLY: 15,
    RecurrenceFrequency.MONTHLY: 30,
    RecurrenceFrequency.QUARTERLY: 91,
    RecurrenceFrequency.SEMI_ANNUAL: 182,
    RecurrenceFrequency.ANNUAL: 365,
}


class CashflowForecaster:
    """Projects daily checking-account balance over a horizon.

    For each recurring stream, expand its hits within the horizon. Add manual events
    (paycheck timing tweaks, anticipated large bills) on top.
    """

    def __init__(self, *, low_balance_floor: Decimal | None = None) -> None:
        self.low_balance_floor = low_balance_floor

    def project(
        self,
        starting_balance: Decimal,
        recurring: Iterable[RecurringStream],
        horizon_days: int = 60,
        extra_events: Iterable[tuple[date, str, Decimal]] | None = None,
    ) -> list[ProjectedDay]:
        today = date.today()
        events: dict[date, list[tuple[str, Decimal]]] = defaultdict(list)
        for stream in recurring:
            amount = stream.next_amount or stream.average_amount
            if amount is None:
                continue
            step_days = _FREQUENCY_DAYS.get(stream.frequency, 30)
            cursor = stream.next_date or today
            end = today + timedelta(days=horizon_days)
            while cursor <= end:
                if cursor >= today:
                    events[cursor].append((stream.name or "Recurring", amount))
                cursor += timedelta(days=step_days)

        for d, label, amt in extra_events or []:
            events[d].append((label, amt))

        balance = starting_balance
        days: list[ProjectedDay] = []
        for offset in range(horizon_days + 1):
            day_date = today + timedelta(days=offset)
            entries = events.get(day_date, [])
            inflows = [(label, abs(amt)) for label, amt in entries if amt > 0]
            outflows = [(label, abs(amt)) for label, amt in entries if amt < 0]
            net = sum((a for _, a in inflows), Decimal(0)) - sum((a for _, a in outflows), Decimal(0))
            ending = balance + net
            days.append(
                ProjectedDay(
                    on_date=day_date,
                    starting_balance=balance,
                    inflows=inflows,
                    outflows=outflows,
                    ending_balance=ending,
                )
            )
            balance = ending
        return days

    def low_balance_dates(self, days: list[ProjectedDay], floor: Decimal | None = None) -> list[ProjectedDay]:
        floor = floor or self.low_balance_floor or Decimal(0)
        return [d for d in days if d.ending_balance < floor]
