"""Goal forecasting — when does each goal hit its target?"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from monarch_insights.models import Goal


@dataclass
class GoalProjection:
    goal_id: str
    goal_name: str
    target_amount: Decimal
    current_amount: Decimal
    monthly_contribution: Decimal | None
    months_to_target: int | None
    expected_completion: date | None
    on_track: bool
    target_date: date | None = None
    shortfall_per_month: Decimal | None = None


class GoalForecaster:
    @staticmethod
    def project(goals: Iterable[Goal], today: date | None = None) -> list[GoalProjection]:
        today = today or date.today()
        out: list[GoalProjection] = []
        for g in goals:
            months = g.months_to_goal()
            expected = today + timedelta(days=months * 30) if months is not None else None
            on_track = True
            shortfall = None
            if g.target_date and months is not None:
                allowed_months = max((g.target_date.year - today.year) * 12 + (g.target_date.month - today.month), 0)
                on_track = months <= allowed_months
                if allowed_months > 0:
                    needed_per_month = (g.target_amount - g.current_amount) / Decimal(allowed_months)
                    if g.monthly_contribution:
                        shortfall = needed_per_month - g.monthly_contribution
            out.append(
                GoalProjection(
                    goal_id=g.id,
                    goal_name=g.name,
                    target_amount=g.target_amount,
                    current_amount=g.current_amount,
                    monthly_contribution=g.monthly_contribution,
                    months_to_target=months,
                    expected_completion=expected,
                    on_track=on_track,
                    target_date=g.target_date,
                    shortfall_per_month=shortfall,
                )
            )
        return out
