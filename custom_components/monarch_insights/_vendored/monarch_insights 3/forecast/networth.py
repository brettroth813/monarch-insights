"""Net worth deterministic projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal


@dataclass
class NetWorthProjection:
    starting_value: Decimal
    monthly_savings: Decimal
    expected_real_return: Decimal
    months: int
    points: list[tuple[date, Decimal]] = field(default_factory=list)

    def summary(self) -> dict:
        if not self.points:
            return {}
        end = self.points[-1]
        return {
            "starting_value": float(self.starting_value),
            "ending_value": float(end[1]),
            "ending_date": end[0].isoformat(),
            "monthly_savings": float(self.monthly_savings),
            "expected_real_return": float(self.expected_real_return),
            "horizon_months": self.months,
        }


class NetWorthForecaster:
    @staticmethod
    def project(
        starting_value: Decimal,
        monthly_savings: Decimal,
        expected_annual_real_return: Decimal,
        months: int,
        as_of: date | None = None,
    ) -> NetWorthProjection:
        as_of = as_of or date.today()
        monthly_rate = (Decimal(1) + expected_annual_real_return) ** (Decimal(1) / Decimal(12)) - Decimal(1)
        balance = starting_value
        points: list[tuple[date, Decimal]] = []
        for m in range(months + 1):
            month_date = as_of + timedelta(days=30 * m)
            points.append((month_date, balance))
            balance = balance * (Decimal(1) + monthly_rate) + monthly_savings
        return NetWorthProjection(
            starting_value=starting_value,
            monthly_savings=monthly_savings,
            expected_real_return=expected_annual_real_return,
            months=months,
            points=points,
        )

    @staticmethod
    def years_to_target(
        starting_value: Decimal,
        target: Decimal,
        monthly_savings: Decimal,
        expected_annual_real_return: Decimal,
        cap_years: int = 100,
    ) -> float | None:
        if starting_value >= target:
            return 0.0
        if monthly_savings <= 0 and expected_annual_real_return <= 0:
            return None
        proj = NetWorthForecaster.project(
            starting_value=starting_value,
            monthly_savings=monthly_savings,
            expected_annual_real_return=expected_annual_real_return,
            months=cap_years * 12,
        )
        for i, (_, value) in enumerate(proj.points):
            if value >= target:
                return i / 12.0
        return None
