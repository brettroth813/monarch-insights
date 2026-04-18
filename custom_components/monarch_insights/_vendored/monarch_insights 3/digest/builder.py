"""Compose a single Markdown digest from the day's insight + alert outputs.

Designed to be idempotent + side-effect-free so the daemon can call it as often as it
wants. The resulting object exposes:

* ``markdown`` — full report.
* ``summary_line`` — one-sentence headline for push notifications.
* ``to_alert()`` — package as a single :class:`Alert` so existing dispatchers can fan it
  out (HA notify, log, store, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable

from monarch_insights.alerts.engine import Alert, Severity
from monarch_insights.insights.networth import NetWorthBreakdown


@dataclass
class DailyDigest:
    """Rolled-up daily summary that combines net worth, alerts, and gap requests."""

    on_date: date
    net_worth: NetWorthBreakdown | None = None
    alerts: list[Alert] = field(default_factory=list)
    gap_summary: list[dict] = field(default_factory=list)
    portfolio_unrealized: Decimal | None = None
    cashflow_runway_months: float | None = None
    fire_age_estimate: int | None = None
    extras: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ formatting

    @property
    def critical_count(self) -> int:
        return sum(1 for a in self.alerts if a.severity == Severity.CRITICAL)

    @property
    def warn_count(self) -> int:
        return sum(1 for a in self.alerts if a.severity == Severity.WARN)

    @property
    def info_count(self) -> int:
        return sum(1 for a in self.alerts if a.severity == Severity.INFO)

    @property
    def summary_line(self) -> str:
        bits: list[str] = []
        if self.net_worth is not None:
            bits.append(f"Net worth ${self.net_worth.net_worth:,.0f}")
        if self.cashflow_runway_months is not None:
            bits.append(f"runway {self.cashflow_runway_months:.1f}mo")
        if self.warn_count or self.critical_count:
            bits.append(f"{self.warn_count + self.critical_count} alerts")
        return " · ".join(bits) or "Nothing notable today."

    @property
    def markdown(self) -> str:
        lines: list[str] = [f"# Daily digest — {self.on_date.isoformat()}", ""]

        if self.net_worth is not None:
            nw = self.net_worth
            lines.append("## Snapshot")
            lines.append(f"- Net worth: **${nw.net_worth:,.0f}**")
            lines.append(f"- Liquid: ${nw.liquid_net_worth:,.0f}")
            lines.append(f"- Assets: ${nw.assets:,.0f}")
            lines.append(f"- Liabilities: ${nw.liabilities:,.0f}")
            if self.portfolio_unrealized is not None:
                lines.append(f"- Portfolio unrealized: ${self.portfolio_unrealized:+,.0f}")
            if self.cashflow_runway_months is not None:
                lines.append(f"- Emergency-fund runway: {self.cashflow_runway_months:.1f} months")
            if self.fire_age_estimate is not None:
                lines.append(f"- FIRE age estimate: {self.fire_age_estimate}")
            lines.append("")

        if self.alerts:
            lines.append("## Alerts")
            for sev in (Severity.CRITICAL, Severity.WARN, Severity.INFO):
                relevant = [a for a in self.alerts if a.severity == sev]
                if not relevant:
                    continue
                lines.append(f"### {sev.value.title()} ({len(relevant)})")
                for alert in relevant:
                    lines.append(f"- **{alert.title}** — {alert.message}")
                    if alert.suggested_action:
                        lines.append(f"  - _Action_: {alert.suggested_action}")
                lines.append("")

        if self.gap_summary:
            lines.append("## Open data gaps")
            for gap in self.gap_summary[:10]:
                lines.append(f"- [{gap.get('severity', 'info')}] {gap.get('summary', '?')}")
            lines.append("")

        if self.extras:
            lines.append("## Notes")
            for key, value in self.extras.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")

        if len(lines) == 2:  # only the header was added
            lines.append("_No new findings today._")
        return "\n".join(lines)

    def to_alert(self) -> Alert:
        """Wrap the digest as an :class:`Alert` so existing dispatchers can fan it out."""
        sev = Severity.CRITICAL if self.critical_count else Severity.WARN if self.warn_count else Severity.INFO
        return Alert.new(
            kind="daily_digest",
            title=f"📊 Monarch daily digest — {self.on_date.isoformat()}",
            message=self.summary_line,
            severity=sev,
            detail={"markdown": self.markdown},
        )

    # ------------------------------------------------------------------ builder

    @classmethod
    def build(
        cls,
        on_date: date,
        *,
        net_worth: NetWorthBreakdown | None = None,
        alerts: Iterable[Alert] = (),
        gap_summary: Iterable[dict] = (),
        portfolio_unrealized: Decimal | None = None,
        cashflow_runway_months: float | None = None,
        fire_age_estimate: int | None = None,
        extras: dict | None = None,
    ) -> DailyDigest:
        return cls(
            on_date=on_date,
            net_worth=net_worth,
            alerts=list(alerts),
            gap_summary=list(gap_summary),
            portfolio_unrealized=portfolio_unrealized,
            cashflow_runway_months=cashflow_runway_months,
            fire_age_estimate=fire_age_estimate,
            extras=extras or {},
        )
