"""Investment insights — performance, allocation drift, expense ratio drag.

Where Monarch is weakest. We surface:
  * Per-holding gain/loss (uses supplements cost basis when Monarch lacks it)
  * Asset allocation drift vs target with drift % and rebalance amount
  * Expense ratio drag annualised
  * Concentration alerts (any single ticker > X% of portfolio)
  * Time-weighted return approximation if snapshot history exists
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from monarch_insights.models import Holding


@dataclass
class HoldingPerformance:
    account_id: str
    ticker: str
    name: str | None
    quantity: Decimal
    market_value: Decimal | None
    cost_basis: Decimal | None
    unrealized_gain: Decimal | None
    unrealized_gain_pct: Decimal | None
    last_priced_at: str | None = None
    cost_basis_source: str = "monarch"  # "monarch" | "supplement" | "missing"


@dataclass
class AllocationDrift:
    bucket: str
    current_value: Decimal
    current_pct: Decimal
    target_pct: Decimal
    drift_pct: Decimal
    drift_dollars: Decimal
    threshold_pct: Decimal
    over_threshold: bool


@dataclass
class PortfolioStats:
    total_value: Decimal
    total_cost_basis: Decimal
    total_unrealized: Decimal
    holdings_count: int
    accounts_count: int
    concentration_top: list[tuple[str, Decimal]] = field(default_factory=list)
    expense_ratio_drag_annual: Decimal | None = None  # USD/year


# Coarse classifier — just enough to give meaningful drift insights without polling
# external metadata APIs. Users can override via target buckets in supplements.
KNOWN_TICKER_BUCKETS: dict[str, str] = {
    # Broad-market US
    "VTI": "us_stock", "ITOT": "us_stock", "SCHB": "us_stock",
    "VOO": "us_stock", "SPY": "us_stock", "IVV": "us_stock", "FXAIX": "us_stock",
    "QQQ": "us_stock", "VUG": "us_stock", "IWM": "us_stock", "VB": "us_stock",
    # International
    "VXUS": "intl_stock", "IXUS": "intl_stock", "VEU": "intl_stock",
    "EFA": "intl_stock", "IEFA": "intl_stock", "VWO": "em_stock", "IEMG": "em_stock",
    # Bonds
    "BND": "bond", "AGG": "bond", "BNDX": "bond", "VTEB": "bond",
    "TLT": "bond", "SHY": "bond", "TIP": "bond", "VTIP": "bond",
    # Real estate / alts
    "VNQ": "real_estate", "VNQI": "real_estate", "SCHH": "real_estate",
    # Cash equivalents
    "BIL": "cash", "SHV": "cash", "SGOV": "cash",
}

# Approximate expense ratios — feed your real data in via supplements/expense_ratios for accuracy.
APPROXIMATE_EXPENSE_RATIOS: dict[str, Decimal] = {
    "VTI": Decimal("0.0003"), "VOO": Decimal("0.0003"), "VXUS": Decimal("0.0007"),
    "BND": Decimal("0.0003"), "VEU": Decimal("0.0006"), "VTEB": Decimal("0.0005"),
    "SPY": Decimal("0.00095"), "QQQ": Decimal("0.0020"),
    "FXAIX": Decimal("0.00015"), "VTSAX": Decimal("0.0004"),
}


class InvestmentInsights:
    def __init__(
        self,
        *,
        ticker_bucket_map: dict[str, str] | None = None,
        expense_ratio_map: dict[str, Decimal] | None = None,
        cost_basis_lookup=None,
    ) -> None:
        self.ticker_bucket = {**KNOWN_TICKER_BUCKETS, **(ticker_bucket_map or {})}
        self.expense_ratios = {**APPROXIMATE_EXPENSE_RATIOS, **(expense_ratio_map or {})}
        self.cost_basis_lookup = cost_basis_lookup  # callable: (account_id, ticker) -> Decimal | None

    def classify(self, ticker: str) -> str:
        t = (ticker or "").upper()
        if t in self.ticker_bucket:
            return self.ticker_bucket[t]
        if t.endswith("X"):  # Mutual fund convention — best guess
            return "us_stock"
        if t in {"BTC", "ETH", "SOL", "BTC-USD", "ETH-USD"}:
            return "crypto"
        return "other"

    def performance(self, holdings: Iterable[Holding]) -> list[HoldingPerformance]:
        out: list[HoldingPerformance] = []
        for h in holdings:
            ticker = (h.ticker or "").upper() or "UNKNOWN"
            cost_basis = h.cost_basis
            source = "monarch" if cost_basis is not None else "missing"
            if cost_basis is None and self.cost_basis_lookup:
                supplemental = self.cost_basis_lookup(h.account_id, ticker)
                if supplemental is not None:
                    cost_basis = supplemental
                    source = "supplement"
            mv = h.best_value
            unreal = (mv - cost_basis) if mv is not None and cost_basis is not None else None
            unreal_pct = (
                (unreal / cost_basis) if unreal is not None and cost_basis and cost_basis != 0 else None
            )
            out.append(
                HoldingPerformance(
                    account_id=h.account_id,
                    ticker=ticker,
                    name=h.name,
                    quantity=h.quantity,
                    market_value=mv,
                    cost_basis=cost_basis,
                    unrealized_gain=unreal,
                    unrealized_gain_pct=unreal_pct,
                    last_priced_at=h.last_priced_at.isoformat() if h.last_priced_at else None,
                    cost_basis_source=source,
                )
            )
        return out

    def allocation(self, holdings: Iterable[Holding]) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        for h in holdings:
            value = h.best_value
            if value is None:
                continue
            bucket = self.classify(h.ticker or "")
            totals[bucket] += value
        return dict(totals)

    def drift(
        self,
        holdings: Iterable[Holding],
        targets: dict[str, dict],  # bucket -> {"target_pct": float, "drift_threshold_pct": float}
    ) -> list[AllocationDrift]:
        current = self.allocation(holdings)
        total = sum(current.values()) or Decimal(1)
        out: list[AllocationDrift] = []
        all_buckets = set(current) | set(targets)
        for bucket in all_buckets:
            cv = current.get(bucket, Decimal(0))
            cp = (cv / total) * Decimal(100)
            tp_raw = (targets.get(bucket) or {}).get("target_pct")
            if tp_raw is None:
                continue
            tp = Decimal(str(tp_raw))
            drift_pct = cp - tp
            target_dollars = total * (tp / Decimal(100))
            drift_dollars = cv - target_dollars
            threshold_raw = (targets.get(bucket) or {}).get("drift_threshold_pct", 5)
            threshold = Decimal(str(threshold_raw))
            out.append(
                AllocationDrift(
                    bucket=bucket,
                    current_value=cv,
                    current_pct=cp,
                    target_pct=tp,
                    drift_pct=drift_pct,
                    drift_dollars=drift_dollars,
                    threshold_pct=threshold,
                    over_threshold=abs(drift_pct) > threshold,
                )
            )
        out.sort(key=lambda d: abs(d.drift_pct), reverse=True)
        return out

    def expense_ratio_drag(self, holdings: Iterable[Holding]) -> dict:
        annual = Decimal(0)
        details = []
        for h in holdings:
            ticker = (h.ticker or "").upper()
            er = self.expense_ratios.get(ticker)
            if er is None:
                continue
            mv = h.best_value or Decimal(0)
            cost = mv * er
            annual += cost
            details.append({"ticker": ticker, "value": float(mv), "er": float(er), "annual_cost": float(cost)})
        details.sort(key=lambda d: d["annual_cost"], reverse=True)
        return {"annual_cost": float(annual), "rows": details}

    def stats(self, holdings: list[Holding]) -> PortfolioStats:
        perf = self.performance(holdings)
        total_value = sum((h.market_value or Decimal(0) for h in perf), Decimal(0))
        total_cost = sum((h.cost_basis or Decimal(0) for h in perf if h.cost_basis is not None), Decimal(0))
        total_unreal = sum((h.unrealized_gain or Decimal(0) for h in perf if h.unrealized_gain is not None), Decimal(0))
        ticker_totals: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        for h in perf:
            if h.market_value is not None:
                ticker_totals[h.ticker] += h.market_value
        top = sorted(ticker_totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
        accounts = {h.account_id for h in perf}
        return PortfolioStats(
            total_value=total_value,
            total_cost_basis=total_cost,
            total_unrealized=total_unreal,
            holdings_count=len(perf),
            accounts_count=len(accounts),
            concentration_top=top,
            expense_ratio_drag_annual=Decimal(str(self.expense_ratio_drag(holdings)["annual_cost"])),
        )

    def concentration_alerts(
        self, holdings: list[Holding], threshold_pct: Decimal = Decimal("10")
    ) -> list[dict]:
        total = sum((h.best_value or Decimal(0) for h in holdings), Decimal(0))
        if total == 0:
            return []
        ticker_totals: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        for h in holdings:
            ticker_totals[(h.ticker or "UNKNOWN").upper()] += h.best_value or Decimal(0)
        alerts = []
        for ticker, value in ticker_totals.items():
            pct = (value / total) * Decimal(100)
            if pct >= threshold_pct:
                alerts.append({"ticker": ticker, "value": float(value), "pct": float(pct)})
        alerts.sort(key=lambda a: a["pct"], reverse=True)
        return alerts
