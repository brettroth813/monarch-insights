#!/usr/bin/env python3
"""End-to-end demo using fixture data — no Monarch credentials needed.

Run with::

    python scripts/demo.py
or::

    .venv/bin/python scripts/demo.py

Exercises every major subsystem so we can sanity-check the wiring before tomorrow:
  * Net worth + breakdowns
  * Cashflow + balance forecast
  * Spending insights + budget pace
  * Investments: drift / ER drag / concentration / TLH candidates
  * Subscription intelligence
  * Anomaly detection
  * Gap detector
  * Alert engine + log dispatcher
  * Tax: income aggregator + deductions + brackets + capital gains
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# Allow running from project root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monarch_insights.alerts.dispatchers import LogDispatcher, StoreDispatcher
from monarch_insights.alerts.engine import AlertContext, AlertEngine
from monarch_insights.alerts.rules import default_rules
from monarch_insights.forecast.cashflow import CashflowForecaster
from monarch_insights.forecast.goals import GoalForecaster
from monarch_insights.forecast.networth import NetWorthForecaster
from monarch_insights.forecast.retirement import RetirementSimulator
from monarch_insights.gaps.detector import GapDetector
from monarch_insights.insights.anomalies import AnomalyDetector
from monarch_insights.insights.cashflow import CashflowInsights
from monarch_insights.insights.investments import InvestmentInsights
from monarch_insights.insights.networth import NetWorthInsights
from monarch_insights.insights.recurring import RecurringInsights
from monarch_insights.insights.spending import SpendingInsights
from monarch_insights.storage.cache import MonarchCache
from monarch_insights.supplements.store import SupplementStore
from monarch_insights.tax.brackets import FilingStatus, federal_tax, marginal_rate, bracket_headroom
from monarch_insights.tax.deductions import DeductionFinder
from monarch_insights.tax.income import IncomeAggregator
from monarch_insights.tax.reports import build_packet

from tests.fixtures import (
    build_accounts,
    build_budgets,
    build_goals,
    build_holdings,
    build_recurring,
    build_transactions,
)


def header(text: str) -> None:
    print()
    print("=" * 78)
    print(text)
    print("=" * 78)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    accounts = build_accounts()
    holdings = build_holdings()
    transactions = build_transactions()
    recurring = build_recurring()
    budgets = build_budgets()
    goals = build_goals()

    with tempfile.TemporaryDirectory() as tmp:
        cache = MonarchCache(path=Path(tmp) / "cache.db")
        store = SupplementStore(path=Path(tmp) / "supp.db")

        header("NET WORTH")
        nw = NetWorthInsights.snapshot(accounts)
        print(f"  Net worth:        ${nw.net_worth:>12,.0f}")
        print(f"  Liquid:           ${nw.liquid_net_worth:>12,.0f}")
        print(f"  Assets:           ${nw.assets:>12,.0f}")
        print(f"  Liabilities:      ${nw.liabilities:>12,.0f}")
        print("  By account type:")
        for k, v in sorted(nw.by_account_type.items(), key=lambda kv: -float(kv[1])):
            print(f"    {k:<20} ${float(v):>12,.0f}")

        header("CASHFLOW (last 12 months)")
        monthly = CashflowInsights.monthly(transactions, months=12)
        for m in monthly[-6:]:
            rate = f"{(m.savings_rate or 0) * 100:>4.0f}%" if m.savings_rate else "  —"
            print(
                f"  {m.month}  income ${m.income:>8,.0f}  expense ${m.expense:>8,.0f}  "
                f"net ${m.net:>+8,.0f}  rate {rate}"
            )
        avg_spend = CashflowInsights.average_monthly_spend(monthly)
        runway = NetWorthInsights.emergency_fund_runway(nw, avg_spend)
        print(f"\n  Average monthly spend (last 6mo): ${avg_spend:,.0f}")
        if runway.get("available"):
            print(f"  Emergency runway: {runway['months_of_runway']:.1f} months ({runway['status']})")

        header("60-DAY CHECKING BALANCE FORECAST")
        forecaster = CashflowForecaster(low_balance_floor=Decimal(2000))
        # Use Chase Checking as primary
        primary = next(a for a in accounts if a.id == "ACT_checking_primary")
        days = forecaster.project(primary.current_balance or Decimal(0), recurring, horizon_days=60)
        danger = forecaster.low_balance_dates(days)
        print(f"  Starting balance: ${primary.current_balance:,.0f}")
        print(f"  Day 60 projected: ${days[-1].ending_balance:,.0f}")
        if danger:
            print(f"  ⚠ {len(danger)} days projected below floor")
            print(f"     first dip: {danger[0].on_date} → ${danger[0].ending_balance:,.0f}")
        else:
            print("  ✔ no dips below floor")

        header("TOP CATEGORIES (last 30 days)")
        for c in SpendingInsights.top_categories(
            transactions, limit=8, since=date.today() - timedelta(days=30)
        ):
            pct = f"{(c.pct_of_total or 0) * 100:>3.0f}%" if c.pct_of_total else "  —"
            print(f"  {c.category_name:<25} ${c.total:>9,.0f}  {pct}  ({c.transaction_count}x)")

        header("BUDGET PACE (current month)")
        for pace in SpendingInsights.budget_pace(budgets[0]):
            print(
                f"  {pace.category_name:<15} planned ${pace.planned:>5,.0f}  "
                f"actual ${pace.actual:>5,.0f}  status {pace.status}"
            )

        header("INVESTMENTS")
        targets = {
            "us_stock": {"target_pct": 60, "drift_threshold_pct": 5},
            "intl_stock": {"target_pct": 25, "drift_threshold_pct": 5},
            "bond": {"target_pct": 15, "drift_threshold_pct": 5},
        }
        invest = InvestmentInsights()
        stats = invest.stats(holdings)
        print(f"  Portfolio value:  ${stats.total_value:>10,.0f}")
        print(f"  Cost basis:       ${stats.total_cost_basis:>10,.0f}")
        print(f"  Unrealized:       ${stats.total_unrealized:>+10,.0f}")
        if stats.expense_ratio_drag_annual is not None:
            print(f"  ER drag /yr:      ${stats.expense_ratio_drag_annual:>10,.0f}")
        print("  Drift vs target:")
        for d in invest.drift(holdings, targets):
            arrow = "↑" if d.drift_pct > 0 else "↓"
            flag = " ⚠" if d.over_threshold else ""
            print(
                f"    {d.bucket:<12} actual {float(d.current_pct):>5.1f}% / target "
                f"{float(d.target_pct):>5.1f}%   {arrow}{abs(float(d.drift_pct)):>4.1f}%   "
                f"${float(d.drift_dollars):>+10,.0f}{flag}"
            )

        header("SUBSCRIPTIONS")
        for dup in RecurringInsights.find_duplicates(recurring):
            print(f"  🔁 duplicate: {dup.merchant_name} (streams {dup.streams}) ~${dup.total_monthly}")
        for c in RecurringInsights.detect_price_creep(transactions):
            print(f"  📈 {c.summary}")
        for i in RecurringInsights.detect_idle_subscriptions(recurring):
            print(f"  💤 {i.summary}")

        header("ANOMALIES")
        det = AnomalyDetector()
        for a in det.per_merchant_outliers(transactions):
            print(f"  🚨 {a.summary}")
        for a in det.category_spike(transactions)[:3]:
            print(f"  📊 {a.summary}")

        header("GAP DETECTOR")
        gap_report = GapDetector(store).run(accounts, holdings, transactions, recurring, persist=True)
        for r in gap_report.requests:
            print(f"  [{r.severity.value:<5}] {r.kind.value:<22} {r.summary}")
            if r.suggested_action:
                print(f"            → {r.suggested_action}")

        header("ALERT ENGINE")
        engine = AlertEngine(default_rules())
        ctx = AlertContext(
            accounts=accounts,
            transactions=transactions,
            holdings=holdings,
            recurring=recurring,
            budgets=budgets,
            goals=goals,
            targets=targets,
            extras={
                "checking_balance": float(primary.current_balance or 0),
                "low_balance_floor": 2000,
                "upcoming_inflows": [],
                "upcoming_outflows": [],
                "concentration_threshold_pct": 10,
                "quotes": {"NVDA": {"change_pct": 0.07}, "AAPL": {"change_pct": -0.04}},
                "price_move_threshold_pct": 5,
            },
        )
        alerts = engine.evaluate(ctx)
        await engine.dispatch(alerts, [LogDispatcher(), StoreDispatcher(cache)])
        print(f"\n  Total alerts: {len(alerts)}")
        sev_counts = {}
        for a in alerts:
            sev_counts[a.severity.value] = sev_counts.get(a.severity.value, 0) + 1
        for sev, count in sorted(sev_counts.items()):
            print(f"    {sev}: {count}")

        header("FORECAST — RETIREMENT")
        sim = RetirementSimulator(seed=2026)
        fire_age = sim.fire_age(
            current_age=35,
            starting_balance=float(stats.total_value),
            annual_savings=24_000,
            annual_spend_target=72_000,
        )
        print(f"  Estimated FIRE age (median, 85% success): {fire_age}")
        result = sim.simulate(
            starting_balance=float(stats.total_value),
            annual_savings=24_000,
            years_to_retirement=fire_age - 35 if fire_age else 25,
            annual_spend_in_retirement=72_000,
            iterations=500,
        )
        print(f"  Success rate:  {result.success_rate * 100:.1f}%")
        print(f"  Median final:  ${result.median_final:,.0f}")
        print(f"  p5 / p95:      ${result.p5_final:,.0f} / ${result.p95_final:,.0f}")

        header("FORECAST — GOALS")
        for proj in GoalForecaster.project(goals):
            on_track = "✔ on track" if proj.on_track else "⚠ off track"
            print(
                f"  {proj.goal_name:<25}  ${proj.current_amount:>7,.0f} / ${proj.target_amount:>7,.0f}   "
                f"~{proj.months_to_target}mo   {on_track}"
            )

        header("TAX (current year)")
        agg = IncomeAggregator()
        report = agg.aggregate(year=date.today().year, transactions=transactions)
        deductions = DeductionFinder().scan(transactions, year=date.today().year)
        packet = build_packet(date.today().year, report, deductions=deductions)
        print(packet.to_markdown())
        tax = federal_tax(report.gross_income, FilingStatus.SINGLE)
        rate = marginal_rate(report.gross_income, FilingStatus.SINGLE)
        head = bracket_headroom(report.gross_income, FilingStatus.SINGLE)
        print(f"\n  Estimated federal tax (single):  ${tax:,.0f}")
        print(f"  Marginal rate: {rate * 100:.0f}%   "
              f"Bracket headroom: ${head.get('headroom_dollars', 0):,.0f}")

        header("DONE")
        print("Pipeline ran end-to-end against fixture data with no live credentials.")


if __name__ == "__main__":
    asyncio.run(main())
