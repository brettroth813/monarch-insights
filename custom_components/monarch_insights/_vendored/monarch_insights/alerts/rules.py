"""Default alert rules — readable functions, easy to enable/disable individually."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from monarch_insights.alerts.engine import Alert, AlertContext, AlertRule, Severity
from monarch_insights.insights.cashflow import CashflowInsights
from monarch_insights.insights.investments import InvestmentInsights
from monarch_insights.insights.recurring import RecurringInsights
from monarch_insights.insights.spending import SpendingInsights


def rule_budget_pace(context: AlertContext) -> Iterable[Alert]:
    for budget in context.budgets:
        for pace in SpendingInsights.budget_pace(budget, today=context.today):
            if pace.status == "over_pace":
                yield Alert.new(
                    kind="budget_pace",
                    title=f"⚠️ {pace.category_name} over pace",
                    message=(
                        f"Spent ${pace.actual:.0f} of ${pace.planned:.0f} "
                        f"with {pace.days_elapsed}/{pace.days_in_period} days elapsed "
                        f"(expected ${pace.expected_actual:.0f})."
                    ),
                    severity=Severity.WARN,
                    detail={
                        "category_id": pace.category_id,
                        "delta": float(pace.pace_delta),
                    },
                )


def rule_low_balance_forecast(context: AlertContext) -> Iterable[Alert]:
    starting = Decimal(str(context.extras.get("checking_balance", 0)))
    floor = Decimal(str(context.extras.get("low_balance_floor", 0)))
    if starting <= 0 or floor <= 0:
        return
    inflows = context.extras.get("upcoming_inflows", [])
    outflows = context.extras.get("upcoming_outflows", [])
    projection = CashflowInsights.project_balance(
        starting, inflows, outflows, horizon_days=context.extras.get("horizon_days", 60)
    )
    danger = CashflowInsights.detect_low_balance(projection, floor)
    if not danger:
        return
    first = danger[0]
    yield Alert.new(
        kind="balance_forecast",
        title="🟡 Checking projected to dip",
        message=(
            f"Projected ending balance below ${floor:.0f} on {first['date']} "
            f"(projected ${first['balance']:.0f})."
        ),
        severity=Severity.WARN,
        detail={"first_dip": first, "horizon": projection[-1]},
    )


def rule_subscription_intel(context: AlertContext) -> Iterable[Alert]:
    duplicates = RecurringInsights.find_duplicates(context.recurring)
    for dup in duplicates:
        yield Alert.new(
            kind="subscription_duplicate",
            title=f"🔁 Possible duplicate subscription: {dup.merchant_name}",
            message=(
                f"Detected {len(dup.streams)} recurring streams for {dup.merchant_name} "
                f"totaling ~${dup.total_monthly:.2f}/period."
            ),
            severity=Severity.INFO,
            detail={"streams": dup.streams},
            suggested_action="Cancel one, or merge them in Monarch.",
        )

    creep = RecurringInsights.detect_price_creep(context.transactions)
    for c in creep:
        yield Alert.new(
            kind="subscription_creep",
            title=f"📈 Subscription price creep — {c.detail['merchant'].title()}",
            message=c.summary,
            severity=Severity.WARN if c.severity == "warn" else Severity.INFO,
            detail=c.detail,
        )

    idle = RecurringInsights.detect_idle_subscriptions(context.recurring)
    for i in idle:
        yield Alert.new(
            kind="subscription_idle",
            title=f"💤 Idle subscription — {i.detail.get('stream_id')}",
            message=i.summary,
            severity=Severity.INFO,
        )


def rule_allocation_drift(context: AlertContext) -> Iterable[Alert]:
    if not context.targets:
        return
    insights = InvestmentInsights()
    for d in insights.drift(context.holdings, context.targets):
        if not d.over_threshold:
            continue
        verb = "overweight" if d.drift_pct > 0 else "underweight"
        yield Alert.new(
            kind="allocation_drift",
            title=f"⚖️ {d.bucket} {verb}",
            message=(
                f"{d.bucket} is {d.current_pct:.1f}% (target {d.target_pct:.1f}%, "
                f"drift {d.drift_pct:+.1f}%, ${d.drift_dollars:+,.0f})"
            ),
            severity=Severity.WARN,
            detail={
                "bucket": d.bucket,
                "current_pct": float(d.current_pct),
                "target_pct": float(d.target_pct),
                "drift_dollars": float(d.drift_dollars),
            },
            suggested_action=(
                f"Sell ~${abs(d.drift_dollars):,.0f} of {d.bucket}"
                if d.drift_pct > 0
                else f"Buy ~${abs(d.drift_dollars):,.0f} of {d.bucket}"
            ),
        )


def rule_holding_concentration(context: AlertContext) -> Iterable[Alert]:
    threshold = Decimal(str(context.extras.get("concentration_threshold_pct", 10)))
    insights = InvestmentInsights()
    for c in insights.concentration_alerts(context.holdings, threshold):
        yield Alert.new(
            kind="concentration",
            title=f"🎯 {c['ticker']} is {c['pct']:.1f}% of portfolio",
            message=(
                f"{c['ticker']} value ${c['value']:,.0f} crosses your "
                f"{float(threshold):.0f}% concentration threshold."
            ),
            severity=Severity.INFO,
        )


def rule_stock_price_movement(context: AlertContext) -> Iterable[Alert]:
    """Watchlist movement alerts. Reads context.extras['quotes'] (dict of symbol → quote)."""
    quotes: dict = context.extras.get("quotes") or {}
    threshold = float(context.extras.get("price_move_threshold_pct", 5)) / 100
    for symbol, q in quotes.items():
        change_pct = q.get("change_pct") if isinstance(q, dict) else getattr(q, "change_pct", None)
        if change_pct is None:
            continue
        change = float(change_pct)
        if abs(change) >= threshold:
            direction = "↑" if change > 0 else "↓"
            yield Alert.new(
                kind="price_movement",
                title=f"📊 {symbol} {direction} {abs(change):.1%}",
                message=f"{symbol} moved {change:+.1%} today.",
                severity=Severity.INFO if abs(change) < threshold * 2 else Severity.WARN,
                detail={"symbol": symbol, "change_pct": change},
            )


def rule_anomalous_spend(context: AlertContext) -> Iterable[Alert]:
    from monarch_insights.insights.anomalies import AnomalyDetector

    detector = AnomalyDetector()
    for a in detector.per_merchant_outliers(context.transactions):
        yield Alert.new(
            kind="anomalous_spend",
            title=f"🚨 Unusual charge — {a.merchant_name}",
            message=a.summary,
            severity=Severity.WARN,
            detail={"transaction_id": a.transaction_id, "z_score": a.z_score},
        )


def rule_goal_off_track(context: AlertContext) -> Iterable[Alert]:
    from monarch_insights.forecast.goals import GoalForecaster

    for proj in GoalForecaster.project(context.goals):
        if proj.on_track:
            continue
        msg = f"{proj.goal_name}: "
        if proj.shortfall_per_month and proj.shortfall_per_month > 0:
            msg += f"need an extra ${proj.shortfall_per_month:,.0f}/mo to hit target."
        else:
            msg += "behind schedule."
        yield Alert.new(
            kind="goal_off_track",
            title=f"🎯 Goal off track — {proj.goal_name}",
            message=msg,
            severity=Severity.INFO,
            detail={"goal_id": proj.goal_id},
        )


def default_rules() -> list[AlertRule]:
    return [
        rule_budget_pace,
        rule_low_balance_forecast,
        rule_subscription_intel,
        rule_allocation_drift,
        rule_holding_concentration,
        rule_stock_price_movement,
        rule_anomalous_spend,
        rule_goal_off_track,
    ]
