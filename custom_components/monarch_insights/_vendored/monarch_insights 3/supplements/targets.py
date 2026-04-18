"""Target asset allocations and longer-form financial plans."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class AllocationTarget:
    bucket: str
    target_pct: Decimal
    drift_threshold_pct: Decimal = Decimal("5")
    notes: str | None = None


@dataclass
class FinancialPlan:
    """A user-defined planning scenario.

    `detail` is a free-form dict so a single record can support FIRE, retirement,
    home-purchase, college, kid plans without forcing a schema explosion. The forecast
    module knows how to read each plan-kind's expected keys.
    """

    id: str
    name: str
    kind: str  # fire | retirement | home_purchase | college | sabbatical | other
    detail: dict = field(default_factory=dict)
    created_at: date = field(default_factory=date.today)
    is_active: bool = True

    @classmethod
    def fire_plan(
        cls,
        target_annual_spend: Decimal,
        swr: Decimal = Decimal("0.04"),
        starting_age: int | None = None,
        target_age: int | None = None,
        expected_real_return: Decimal = Decimal("0.05"),
        savings_rate: Decimal | None = None,
    ) -> FinancialPlan:
        return cls(
            id=str(uuid.uuid4()),
            name="FIRE",
            kind="fire",
            detail={
                "target_annual_spend": str(target_annual_spend),
                "swr": str(swr),
                "fire_number": str(target_annual_spend / swr),
                "starting_age": starting_age,
                "target_age": target_age,
                "expected_real_return": str(expected_real_return),
                "savings_rate": str(savings_rate) if savings_rate is not None else None,
            },
        )

    @classmethod
    def home_plan(
        cls,
        target_price: Decimal,
        down_payment_pct: Decimal,
        target_close_date: date,
    ) -> FinancialPlan:
        return cls(
            id=str(uuid.uuid4()),
            name=f"Home @ {target_close_date.isoformat()}",
            kind="home_purchase",
            detail={
                "target_price": str(target_price),
                "down_payment_pct": str(down_payment_pct),
                "down_payment_amount": str(target_price * down_payment_pct),
                "target_close_date": target_close_date.isoformat(),
            },
        )
