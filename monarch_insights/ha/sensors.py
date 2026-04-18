"""Sensor payload builders for HA — flatten insight outputs into HA-friendly state dicts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable

from monarch_insights.insights.investments import InvestmentInsights, PortfolioStats
from monarch_insights.insights.networth import NetWorthBreakdown, NetWorthInsights
from monarch_insights.models import Account, Holding, Transaction


@dataclass
class SensorPayload:
    name: str
    state: float | int | str | None
    unit_of_measurement: str | None = None
    icon: str | None = None
    attributes: dict | None = None
    unique_id: str | None = None
    device_class: str | None = None


class SensorProducer:
    """Maps domain objects → sensor payloads HA can ingest as MQTT or via REST."""

    def __init__(self, currency: str = "USD") -> None:
        self.currency = currency

    def net_worth(self, breakdown: NetWorthBreakdown) -> list[SensorPayload]:
        attr = {
            "assets": float(breakdown.assets),
            "liabilities": float(breakdown.liabilities),
            "by_type": {k: float(v) for k, v in breakdown.by_account_type.items()},
            "by_institution": {k: float(v) for k, v in breakdown.by_institution.items()},
            "as_of": breakdown.on_date.isoformat(),
        }
        return [
            SensorPayload(
                name="Net worth",
                unique_id="monarch_net_worth",
                state=float(breakdown.net_worth),
                unit_of_measurement=self.currency,
                icon="mdi:scale-balance",
                device_class="monetary",
                attributes=attr,
            ),
            SensorPayload(
                name="Liquid net worth",
                unique_id="monarch_liquid_net_worth",
                state=float(breakdown.liquid_net_worth),
                unit_of_measurement=self.currency,
                icon="mdi:cash-multiple",
                device_class="monetary",
            ),
            SensorPayload(
                name="Total assets",
                unique_id="monarch_total_assets",
                state=float(breakdown.assets),
                unit_of_measurement=self.currency,
                icon="mdi:bank",
                device_class="monetary",
            ),
            SensorPayload(
                name="Total liabilities",
                unique_id="monarch_total_liabilities",
                state=float(breakdown.liabilities),
                unit_of_measurement=self.currency,
                icon="mdi:credit-card",
                device_class="monetary",
            ),
        ]

    def per_account(self, accounts: Iterable[Account]) -> list[SensorPayload]:
        out: list[SensorPayload] = []
        for a in accounts:
            if a.is_hidden:
                continue
            balance = float(a.current_balance) if a.current_balance is not None else None
            out.append(
                SensorPayload(
                    name=f"{a.display_name} balance",
                    unique_id=f"monarch_account_{a.id}",
                    state=balance,
                    unit_of_measurement=self.currency,
                    icon="mdi:credit-card-outline" if a.is_liability else "mdi:bank-outline",
                    device_class="monetary",
                    attributes={
                        "type": a.type.value,
                        "subtype": a.subtype.value,
                        "is_liability": a.is_liability,
                        "institution": a.institution.name if a.institution else None,
                        "last_balance_at": a.last_balance_at.isoformat() if a.last_balance_at else None,
                    },
                )
            )
        return out

    def portfolio_stats(self, stats: PortfolioStats) -> list[SensorPayload]:
        return [
            SensorPayload(
                name="Portfolio value",
                unique_id="monarch_portfolio_value",
                state=float(stats.total_value),
                unit_of_measurement=self.currency,
                icon="mdi:chart-line",
                device_class="monetary",
                attributes={
                    "cost_basis": float(stats.total_cost_basis),
                    "unrealized": float(stats.total_unrealized),
                    "holdings_count": stats.holdings_count,
                    "accounts_count": stats.accounts_count,
                    "concentration_top": [
                        {"ticker": t, "value": float(v)} for t, v in stats.concentration_top
                    ],
                    "expense_ratio_drag_annual": (
                        float(stats.expense_ratio_drag_annual)
                        if stats.expense_ratio_drag_annual is not None
                        else None
                    ),
                },
            ),
        ]

    def cashflow_runway(self, runway: dict) -> SensorPayload | None:
        if not runway.get("available"):
            return None
        return SensorPayload(
            name="Emergency fund runway",
            unique_id="monarch_emergency_runway",
            state=round(runway["months_of_runway"], 2),
            unit_of_measurement="months",
            icon="mdi:shield-cash",
            attributes=runway,
        )

    def alerts(self, alerts: Iterable[dict]) -> list[SensorPayload]:
        alerts = list(alerts)
        return [
            SensorPayload(
                name="Open alerts",
                unique_id="monarch_open_alerts",
                state=len(alerts),
                icon="mdi:alert-circle-outline",
                attributes={"alerts": alerts[:25]},
            ),
        ]
