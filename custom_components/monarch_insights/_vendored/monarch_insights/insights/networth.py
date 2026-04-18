"""Net worth analytics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from monarch_insights.models import Account, AccountType


@dataclass
class NetWorthBreakdown:
    on_date: date
    assets: Decimal = Decimal(0)
    liabilities: Decimal = Decimal(0)
    by_account_type: dict[str, Decimal] = field(default_factory=dict)
    by_account: dict[str, Decimal] = field(default_factory=dict)
    by_institution: dict[str, Decimal] = field(default_factory=dict)
    excluded_accounts: list[str] = field(default_factory=list)

    @property
    def net_worth(self) -> Decimal:
        return self.assets - self.liabilities

    @property
    def liquid_net_worth(self) -> Decimal:
        liquid_types = {AccountType.DEPOSITORY.value, AccountType.BROKERAGE.value, AccountType.CRYPTOCURRENCY.value}
        liquid_assets = sum(
            (v for k, v in self.by_account_type.items() if k in liquid_types and v > 0),
            Decimal(0),
        )
        return liquid_assets - self.liabilities


class NetWorthInsights:
    @staticmethod
    def snapshot(accounts: Iterable[Account], as_of: date | None = None) -> NetWorthBreakdown:
        as_of = as_of or date.today()
        breakdown = NetWorthBreakdown(on_date=as_of)
        for a in accounts:
            if not a.include_in_net_worth or a.is_hidden:
                breakdown.excluded_accounts.append(a.id)
                continue
            balance = a.signed_balance or Decimal(0)
            if a.is_liability:
                breakdown.liabilities += abs(balance)
            else:
                breakdown.assets += balance
            type_key = a.type.value
            breakdown.by_account_type[type_key] = breakdown.by_account_type.get(type_key, Decimal(0)) + balance
            breakdown.by_account[a.id] = balance
            inst = (a.institution.name if a.institution else "Manual")
            breakdown.by_institution[inst] = breakdown.by_institution.get(inst, Decimal(0)) + balance
        return breakdown

    @staticmethod
    def trend(
        history: list[dict],
        window_days: int = 30,
    ) -> dict:
        """Return change in net worth over the trailing window from a history list.

        ``history`` shape: list of {"date": "YYYY-MM-DD", "net_worth": float}.
        """
        if not history:
            return {"available": False}
        sorted_hist = sorted(history, key=lambda r: r["date"])
        latest = sorted_hist[-1]
        latest_date = date.fromisoformat(latest["date"])
        cutoff = latest_date - timedelta(days=window_days)
        baseline = next((r for r in reversed(sorted_hist) if date.fromisoformat(r["date"]) <= cutoff), sorted_hist[0])
        delta = Decimal(str(latest["net_worth"])) - Decimal(str(baseline["net_worth"]))
        return {
            "available": True,
            "from_date": baseline["date"],
            "to_date": latest["date"],
            "from_value": baseline["net_worth"],
            "to_value": latest["net_worth"],
            "delta": float(delta),
            "delta_pct": float(delta / Decimal(str(baseline["net_worth"]))) if baseline["net_worth"] else None,
            "window_days": window_days,
        }

    @staticmethod
    def emergency_fund_runway(
        breakdown: NetWorthBreakdown, average_monthly_spend: Decimal
    ) -> dict:
        if average_monthly_spend <= 0:
            return {"available": False}
        liquid = breakdown.liquid_net_worth
        months = liquid / average_monthly_spend if average_monthly_spend else Decimal(0)
        return {
            "available": True,
            "liquid_assets": float(liquid),
            "monthly_spend": float(average_monthly_spend),
            "months_of_runway": float(months),
            "status": (
                "danger" if months < 1 else "warn" if months < 3 else "ok" if months < 6 else "great"
            ),
        }
