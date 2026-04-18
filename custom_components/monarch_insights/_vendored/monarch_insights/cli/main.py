"""``monarch-insights`` CLI entry point.

Usage hints (these all run today against fixture/cache data; live Monarch comes once
auth is wired):

    monarch-insights auth login --email you@example.com
    monarch-insights sync --full
    monarch-insights insight networth
    monarch-insights insight cashflow --months 12
    monarch-insights insight spending --days 30
    monarch-insights insight investments
    monarch-insights forecast cashflow --days 60
    monarch-insights forecast retirement --age 35 --balance 250000 --savings 24000
    monarch-insights gaps list
    monarch-insights tax packet --year 2025
    monarch-insights alerts run
"""

from __future__ import annotations

import asyncio
import getpass
import json
import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from monarch_insights.client.api import MonarchClient
from monarch_insights.client.auth import MonarchAuth
from monarch_insights.client.exceptions import MonarchMFARequired
from monarch_insights.forecast.cashflow import CashflowForecaster
from monarch_insights.forecast.retirement import RetirementSimulator
from monarch_insights.gaps.detector import GapDetector
from monarch_insights.insights.cashflow import CashflowInsights
from monarch_insights.insights.investments import InvestmentInsights
from monarch_insights.insights.networth import NetWorthInsights
from monarch_insights.insights.spending import SpendingInsights
from monarch_insights.storage.cache import MonarchCache
from monarch_insights.storage.snapshots import SnapshotStore
from monarch_insights.supplements.store import SupplementStore
from monarch_insights.tax.brackets import FilingStatus, federal_tax, marginal_rate, bracket_headroom

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Monarch Insights")
auth_app = typer.Typer(help="Authenticate with Monarch")
sync_app = typer.Typer(help="Pull data from Monarch into the local cache")
insight_app = typer.Typer(help="Read-only analytics over cached data")
forecast_app = typer.Typer(help="Forward-looking projections")
gaps_app = typer.Typer(help="Information requests + gap reports")
tax_app = typer.Typer(help="Tax-prep helpers")
alerts_app = typer.Typer(help="Run the alert engine")
provider_app = typer.Typer(help="Account-provider configuration")
daemon_app = typer.Typer(help="Long-running scheduler daemon")
watchlist_app = typer.Typer(help="Stock watchlist management")
events_app = typer.Typer(help="Query the structured event log")

app.add_typer(auth_app, name="auth")
app.add_typer(sync_app, name="sync")
app.add_typer(insight_app, name="insight")
app.add_typer(forecast_app, name="forecast")
app.add_typer(gaps_app, name="gaps")
app.add_typer(tax_app, name="tax")
app.add_typer(alerts_app, name="alerts")
app.add_typer(provider_app, name="providers")
app.add_typer(daemon_app, name="daemon")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(events_app, name="events")

# One-time bootstrap flows for Google / Schwab / Robinhood live in their own module
# so this file stays readable. Import after the sub-apps are registered so Typer
# discovers the nested commands correctly.
from monarch_insights.cli.bootstrap import app as bootstrap_app  # noqa: E402

app.add_typer(bootstrap_app, name="bootstrap")

console = Console()


# --------------------------------------------------------------------- helpers

def _client_or_die() -> MonarchClient:
    auth = MonarchAuth()
    if not auth.session_path.exists():
        console.print("[red]No saved Monarch session — run `monarch-insights auth login` first.[/]")
        raise typer.Exit(1)
    return MonarchClient(auth)


# --------------------------------------------------------------------- auth

@auth_app.command("login")
def auth_login(
    email: str = typer.Option(..., prompt=True, help="Monarch account email"),
    password: str | None = typer.Option(None, hide_input=True, help="Password (omit to be prompted)"),
):
    if password is None:
        password = getpass.getpass("Monarch password: ")
    auth = MonarchAuth()

    async def _do():
        try:
            await auth.login(email, password)
        except MonarchMFARequired:
            method = typer.prompt("MFA method [totp/email_otp]", default="totp")
            code = typer.prompt(f"Enter {method} code")
            await auth.submit_mfa(email, password, code, method=method)
        return auth.session

    session = asyncio.run(_do())
    console.print(f"[green]✔[/] Saved session for [bold]{session.user_email}[/]")


@auth_app.command("status")
def auth_status():
    auth = MonarchAuth()
    session = auth.load()
    if session is None:
        console.print("[yellow]No session found.[/]")
        raise typer.Exit(1)
    console.print(f"[green]✔[/] Session for [bold]{session.user_email}[/] (device {session.device_uuid[:8]})")


@auth_app.command("logout")
def auth_logout():
    auth = MonarchAuth()
    asyncio.run(auth.logout())
    console.print("[green]✔[/] Cleared session.")


# --------------------------------------------------------------------- sync

@sync_app.command("full")
def sync_full(months: int = typer.Option(18, help="How many months of transactions to backfill")):
    cache = MonarchCache()

    async def _do():
        client = _client_or_die()
        await client.start()
        try:
            console.print("Fetching accounts…")
            accounts = await client.get_accounts()
            cache.upsert_many("account", [(a.id, a.model_dump()) for a in accounts])
            run_id = cache.record_sync_start("full")
            console.print(f"  {len(accounts)} accounts.")

            console.print("Fetching holdings…")
            holdings = await client.get_holdings()
            cache.upsert_holdings([h.model_dump() for h in holdings])
            console.print(f"  {len(holdings)} holdings.")

            console.print("Fetching categories + tags…")
            categories = await client.get_categories()
            tags = await client.get_tags()
            cache.upsert_many("category", [(c.id, c.model_dump()) for c in categories])
            cache.upsert_many("tag", [(t.id, t.model_dump()) for t in tags])

            console.print(f"Fetching transactions for last {months} months…")
            tx_count = 0
            async for tx in client.iter_transactions(
                start_date=date.today() - timedelta(days=months * 31)
            ):
                cache.upsert_transactions([tx.model_dump()])
                tx_count += 1
                if tx_count % 200 == 0:
                    console.print(f"  …{tx_count}")
            console.print(f"  {tx_count} transactions.")

            console.print("Fetching recurring + goals…")
            recurring = await client.get_recurring()
            goals = await client.get_goals()
            cache.upsert_many("recurring", [(r.id, r.model_dump()) for r in recurring])
            cache.upsert_many("goal", [(g.id, g.model_dump()) for g in goals])

            cache.record_sync_finish(run_id, "ok", detail={
                "accounts": len(accounts),
                "holdings": len(holdings),
                "transactions": tx_count,
                "recurring": len(recurring),
                "goals": len(goals),
            })
            console.print("[green]✔ sync complete[/]")
        finally:
            await client.close()

    asyncio.run(_do())


@sync_app.command("snapshot-networth")
def snapshot_networth():
    """Persist today's net worth into the snapshot store."""
    cache = MonarchCache()
    snapshots = SnapshotStore()
    raw_accounts = cache.list_entities("account")
    if not raw_accounts:
        console.print("[red]No accounts in cache. Run `monarch-insights sync full` first.[/]")
        raise typer.Exit(1)
    from monarch_insights.models import Account

    accounts = [Account.model_validate(r) for r in raw_accounts]
    breakdown = NetWorthInsights.snapshot(accounts)
    snapshots.record_net_worth(
        on_date=breakdown.on_date,
        assets=float(breakdown.assets),
        liabilities=float(breakdown.liabilities),
        detail={"by_type": {k: float(v) for k, v in breakdown.by_account_type.items()}},
    )
    console.print(f"[green]✔[/] net worth snapshot ${breakdown.net_worth:,.0f}")


# --------------------------------------------------------------------- insights

@insight_app.command("networth")
def insight_networth():
    cache = MonarchCache()
    raw = cache.list_entities("account")
    from monarch_insights.models import Account

    accounts = [Account.model_validate(r) for r in raw]
    bd = NetWorthInsights.snapshot(accounts)
    table = Table(title=f"Net worth — {bd.on_date}")
    table.add_column("Bucket")
    table.add_column("Value", justify="right")
    table.add_row("Assets", f"${bd.assets:,.0f}")
    table.add_row("Liabilities", f"${bd.liabilities:,.0f}")
    table.add_row("Net worth", f"${bd.net_worth:,.0f}")
    table.add_row("Liquid", f"${bd.liquid_net_worth:,.0f}")
    console.print(table)


@insight_app.command("cashflow")
def insight_cashflow(months: int = 12):
    cache = MonarchCache()
    rows = cache.list_entities("transaction")
    if not rows:
        with cache.connect() as conn:
            db_rows = conn.execute("SELECT payload_json FROM transactions").fetchall()
        rows = [json.loads(r["payload_json"]) for r in db_rows]
    from monarch_insights.models import Transaction

    txs = [Transaction.model_validate(r) for r in rows]
    monthly = CashflowInsights.monthly(txs, months=months)
    table = Table(title=f"Cashflow — last {months} months")
    table.add_column("Month")
    table.add_column("Income", justify="right")
    table.add_column("Expense", justify="right")
    table.add_column("Net", justify="right")
    table.add_column("Savings rate", justify="right")
    for m in monthly:
        rate = f"{(m.savings_rate or 0) * 100:.0f}%" if m.savings_rate is not None else "—"
        table.add_row(
            m.month,
            f"${m.income:,.0f}",
            f"${m.expense:,.0f}",
            f"${m.net:,.0f}",
            rate,
        )
    console.print(table)


@insight_app.command("spending")
def insight_spending(days: int = 30, limit: int = 10):
    cache = MonarchCache()
    with cache.connect() as conn:
        rows = conn.execute("SELECT payload_json FROM transactions").fetchall()
    from monarch_insights.models import Transaction

    txs = [Transaction.model_validate(json.loads(r["payload_json"])) for r in rows]
    cats = SpendingInsights.top_categories(txs, limit=limit, since=date.today() - timedelta(days=days))
    table = Table(title=f"Top spend categories — last {days} days")
    table.add_column("Category")
    table.add_column("Total", justify="right")
    table.add_column("Count", justify="right")
    table.add_column("% of spend", justify="right")
    for c in cats:
        pct = f"{(c.pct_of_total or 0) * 100:.0f}%" if c.pct_of_total else "—"
        table.add_row(c.category_name, f"${c.total:,.0f}", str(c.transaction_count), pct)
    console.print(table)


@insight_app.command("investments")
def insight_investments():
    cache = MonarchCache()
    with cache.connect() as conn:
        rows = conn.execute("SELECT payload_json FROM holdings").fetchall()
    from monarch_insights.models import Holding

    holdings = [Holding.model_validate(json.loads(r["payload_json"])) for r in rows]
    insights = InvestmentInsights()
    stats = insights.stats(holdings)
    console.print(f"[bold]Portfolio value:[/] ${stats.total_value:,.0f}")
    console.print(f"[bold]Cost basis:[/] ${stats.total_cost_basis:,.0f}")
    console.print(f"[bold]Unrealized:[/] ${stats.total_unrealized:,.0f}")
    if stats.expense_ratio_drag_annual is not None:
        console.print(f"[bold]Expense ratio drag (annual):[/] ${stats.expense_ratio_drag_annual:,.0f}")
    table = Table(title="Top concentration")
    table.add_column("Ticker")
    table.add_column("Value", justify="right")
    for ticker, value in stats.concentration_top:
        table.add_row(ticker, f"${value:,.0f}")
    console.print(table)


# --------------------------------------------------------------------- forecast

@forecast_app.command("cashflow")
def forecast_cashflow(
    starting_balance: float = typer.Option(..., help="Today's checking balance"),
    days: int = 60,
    floor: float = 1000.0,
):
    cache = MonarchCache()
    raw = cache.list_entities("recurring")
    if not raw:
        console.print("[yellow]No recurring streams cached — run sync first.[/]")
    from monarch_insights.models import RecurringStream

    streams = [RecurringStream.model_validate(r) for r in raw]
    forecaster = CashflowForecaster(low_balance_floor=Decimal(str(floor)))
    days_proj = forecaster.project(Decimal(str(starting_balance)), streams, horizon_days=days)
    danger = forecaster.low_balance_dates(days_proj)
    console.print(f"Projected ending balance in {days} days: ${days_proj[-1].ending_balance:,.0f}")
    if danger:
        console.print(f"[red]⚠ {len(danger)} days projected below ${floor}[/]")
        first = danger[0]
        console.print(f"   First dip: {first.on_date} → ${first.ending_balance:,.0f}")
    else:
        console.print(f"[green]✔[/] balance stays above ${floor} the whole horizon.")


@forecast_app.command("retirement")
def forecast_retirement(
    age: int = 35,
    balance: float = 100_000,
    savings: float = 24_000,
    spend: float = 60_000,
    iterations: int = 1000,
):
    sim = RetirementSimulator()
    fire_age = sim.fire_age(
        current_age=age,
        starting_balance=balance,
        annual_savings=savings,
        annual_spend_target=spend,
    )
    console.print(f"Estimated FIRE age: [bold]{fire_age}[/]" if fire_age else "FIRE not reached by 80")
    result = sim.simulate(
        starting_balance=balance,
        annual_savings=savings,
        years_to_retirement=fire_age - age if fire_age else 30,
        annual_spend_in_retirement=spend,
        iterations=iterations,
    )
    table = Table(title=f"Monte Carlo ({iterations} iterations)")
    table.add_column("Stat")
    table.add_column("Value", justify="right")
    table.add_row("Success rate", f"{result.success_rate * 100:.1f}%")
    table.add_row("Median final", f"${result.median_final:,.0f}")
    table.add_row("p5 final", f"${result.p5_final:,.0f}")
    table.add_row("p95 final", f"${result.p95_final:,.0f}")
    console.print(table)


# --------------------------------------------------------------------- gaps

@gaps_app.command("scan")
def gaps_scan():
    cache = MonarchCache()
    store = SupplementStore()
    raw_accounts = cache.list_entities("account")
    raw_recurring = cache.list_entities("recurring")
    with cache.connect() as conn:
        tx_rows = conn.execute("SELECT payload_json FROM transactions").fetchall()
        h_rows = conn.execute("SELECT payload_json FROM holdings").fetchall()
    from monarch_insights.models import Account, Holding, RecurringStream, Transaction

    accounts = [Account.model_validate(r) for r in raw_accounts]
    recurring = [RecurringStream.model_validate(r) for r in raw_recurring]
    txs = [Transaction.model_validate(json.loads(r["payload_json"])) for r in tx_rows]
    holdings = [Holding.model_validate(json.loads(r["payload_json"])) for r in h_rows]
    report = GapDetector(store).run(accounts, holdings, txs, recurring)
    console.print(report.to_markdown())


@gaps_app.command("list")
def gaps_list():
    store = SupplementStore()
    table = Table(title="Open information requests")
    table.add_column("Severity")
    table.add_column("Kind")
    table.add_column("Summary")
    table.add_column("Action")
    for r in store.open_info_requests():
        table.add_row(r["severity"], r["kind"], r["summary"], r.get("suggested_action") or "—")
    console.print(table)


# --------------------------------------------------------------------- tax

@tax_app.command("brackets")
def tax_brackets(
    income: float = typer.Option(..., help="Taxable income"),
    status: str = "single",
):
    fs = FilingStatus(status)
    tax = federal_tax(Decimal(str(income)), fs)
    rate = marginal_rate(Decimal(str(income)), fs)
    headroom = bracket_headroom(Decimal(str(income)), fs)
    console.print(f"Federal tax estimate: [bold]${tax:,.0f}[/] (marginal rate {rate * 100:.0f}%)")
    console.print(f"Bracket headroom: ${headroom.get('headroom_dollars', 0):,.0f} until next rate")


# --------------------------------------------------------------------- providers

@provider_app.command("list")
def providers_list():
    from monarch_insights.providers.accounts.directory import build_default_directory

    table = Table(title="Account provider directory")
    table.add_column("Institution")
    table.add_column("Provider")
    table.add_column("Auth")
    table.add_column("Setup hint")
    for entry in build_default_directory():
        table.add_row(entry.institution, entry.provider_name, entry.auth_kind, entry.setup_hint)
    console.print(table)


# --------------------------------------------------------------------- watchlist

@watchlist_app.command("add")
def watchlist_add(
    symbol: str = typer.Argument(..., help="Ticker, e.g. NVDA"),
    target_price: float | None = typer.Option(None, help="Price trigger (buy_below / sell_above)"),
    kind: str = typer.Option("alert_move", help="buy_below | sell_above | alert_move"),
    move_threshold: float = typer.Option(5.0, help="Daily % move to alert on (alert_move only)"),
    notes: str = typer.Option("", help="Free-form note"),
):
    """Add or update a watchlist entry."""
    from monarch_insights.watchlist.store import WatchlistEntry, WatchlistStore

    store = WatchlistStore()
    entry = WatchlistEntry(
        symbol=symbol,
        target_price=Decimal(str(target_price)) if target_price is not None else None,
        target_kind=kind,
        move_threshold_pct=Decimal(str(move_threshold)),
        notes=notes or None,
    )
    store.add(entry)
    console.print(f"[green]✔[/] watchlist updated for {symbol.upper()}")


@watchlist_app.command("list")
def watchlist_list():
    """Show every watchlist entry."""
    from monarch_insights.watchlist.store import WatchlistStore

    entries = WatchlistStore().list()
    table = Table(title="Watchlist")
    table.add_column("Symbol")
    table.add_column("Kind")
    table.add_column("Target", justify="right")
    table.add_column("Move%", justify="right")
    table.add_column("Notes")
    for e in entries:
        table.add_row(
            e.symbol,
            e.target_kind or "—",
            f"${e.target_price}" if e.target_price is not None else "—",
            f"{e.move_threshold_pct}%" if e.move_threshold_pct is not None else "—",
            e.notes or "",
        )
    console.print(table)


@watchlist_app.command("remove")
def watchlist_remove(symbol: str):
    from monarch_insights.watchlist.store import WatchlistStore

    WatchlistStore().remove(symbol)
    console.print(f"[yellow]removed {symbol.upper()}[/]")


# --------------------------------------------------------------------- events

@events_app.command("recent")
def events_recent(
    limit: int = typer.Option(50),
    source: str = typer.Option(None, help="Filter by source, supports SQL LIKE patterns (use %)"),
    kind: str = typer.Option(None),
    severity: str = typer.Option(None),
):
    """Show recent events from the structured event log."""
    from monarch_insights.observability import EventLog

    rows = EventLog().recent(limit=limit, source=source, kind=kind, severity=severity)
    table = Table(title=f"Recent events ({len(rows)})")
    table.add_column("Time", style="dim")
    table.add_column("Source")
    table.add_column("Kind")
    table.add_column("Sev")
    table.add_column("Detail")
    for r in rows:
        detail = ", ".join(f"{k}={v}" for k, v in list(r.detail.items())[:3])
        table.add_row(r.ts.strftime("%Y-%m-%d %H:%M"), r.source, r.kind, r.severity, detail)
    console.print(table)


@events_app.command("count")
def events_count(source: str = typer.Option(None), kind: str = typer.Option(None)):
    from monarch_insights.observability import EventLog

    console.print(EventLog().count(source=source, kind=kind))


# --------------------------------------------------------------------- daemon

@daemon_app.command("run")
def daemon_run(
    sync_interval_minutes: int = typer.Option(60),
    digest_hour: int = typer.Option(7),
):
    """Start the long-running scheduler.

    Installs three jobs by default:
      * ``sync`` every ``sync_interval_minutes`` — refresh Monarch + run alerts.
      * ``digest`` daily at ``digest_hour`` UTC — produce the daily digest.
      * ``gap_scan`` daily at 06:00 UTC — write info requests to the supplements DB.

    Stop with Ctrl-C; the scheduler writes a ``daemon.stop`` event on exit.
    """
    from datetime import time as _time, timedelta as _timedelta

    from monarch_insights.daemon.scheduler import DaemonConfig, MonarchDaemon
    from monarch_insights.observability import EventLog, configure_logging

    configure_logging()
    config = DaemonConfig(
        sync_interval=_timedelta(minutes=sync_interval_minutes),
        digest_at=_time(digest_hour, 0),
    )
    daemon = MonarchDaemon(config, event_log=EventLog())

    async def _sync_job():
        # Real sync is wired once credentials exist; for now just record a heartbeat.
        EventLog().record("daemon.sync", "heartbeat", {"sync_interval_minutes": sync_interval_minutes})

    async def _digest_job():
        EventLog().record("daemon.digest", "heartbeat")

    async def _gap_job():
        EventLog().record("daemon.gaps", "heartbeat")

    daemon.register_interval("sync", _sync_job, _timedelta(minutes=sync_interval_minutes))
    daemon.register_daily("digest", _digest_job, _time(digest_hour, 0))
    daemon.register_daily("gap_scan", _gap_job, _time(6, 0))

    try:
        asyncio.run(daemon.run_forever())
    except KeyboardInterrupt:
        console.print("[yellow]stopping daemon…[/]")


def main():  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
