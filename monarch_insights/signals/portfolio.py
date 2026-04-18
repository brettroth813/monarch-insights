"""Portfolio-context signals: tax-loss harvesting, lot ageing, concentration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from monarch_insights.insights.investments import HoldingPerformance


@dataclass
class PortfolioSignal:
    symbol: str
    kind: str  # tax_loss_harvest | rebalance_sell | rebalance_buy | concentration | aging_lot
    summary: str
    detail: dict


class PortfolioSignals:
    @staticmethod
    def tax_loss_candidates(
        performances: Iterable[HoldingPerformance],
        min_loss: Decimal = Decimal(500),
    ) -> list[PortfolioSignal]:
        out: list[PortfolioSignal] = []
        for h in performances:
            if h.unrealized_gain is None:
                continue
            loss = -h.unrealized_gain  # positive when we have a loss
            if loss >= min_loss:
                out.append(
                    PortfolioSignal(
                        symbol=h.ticker,
                        kind="tax_loss_harvest",
                        summary=(
                            f"{h.ticker} is down ${loss:,.0f} "
                            f"({(loss/(h.cost_basis or Decimal(1))*100):.1f}%) — eligible for harvest."
                        ),
                        detail={
                            "loss": float(loss),
                            "cost_basis": float(h.cost_basis or 0),
                            "market_value": float(h.market_value or 0),
                            "account_id": h.account_id,
                        },
                    )
                )
        return out

    @staticmethod
    def aging_short_term_lots(
        lots: Iterable[dict],
        warn_within_days: int = 45,
    ) -> list[PortfolioSignal]:
        """Lots that are less than 45 days from long-term — flag in case you plan to sell."""
        from datetime import datetime

        today = date.today()
        out: list[PortfolioSignal] = []
        for lot in lots:
            acquired = date.fromisoformat(lot["acquired_on"])
            days_held = (today - acquired).days
            days_to_lt = 366 - days_held
            if 0 < days_to_lt <= warn_within_days:
                out.append(
                    PortfolioSignal(
                        symbol=lot["ticker"],
                        kind="aging_lot",
                        summary=(
                            f"{lot['ticker']} lot from {acquired} crosses to long-term in "
                            f"{days_to_lt} days. Wait if planning to sell."
                        ),
                        detail={"lot_id": lot["id"], "acquired_on": lot["acquired_on"], "days_to_lt": days_to_lt},
                    )
                )
        return out
