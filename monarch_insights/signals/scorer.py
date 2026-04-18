"""Combine technical, fundamental, and portfolio signals into a single per-ticker score.

Output is intentionally conservative: this is *idea generation*, not investment advice.
A "score" of +3 means "buy-leaning evidence" — never auto-trade off it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable

from monarch_insights.signals.fundamental import ValuationReading
from monarch_insights.signals.portfolio import PortfolioSignal
from monarch_insights.signals.technical import TechnicalReading


class Action(str, Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"
    HARVEST_LOSS = "harvest_loss"


@dataclass
class ScoredSignal:
    symbol: str
    score: int
    action: Action
    rationale: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "action": self.action.value,
            "rationale": self.rationale,
            "generated_at": self.generated_at.isoformat(),
        }


def _score_technical(t: TechnicalReading | None) -> tuple[int, list[str]]:
    if t is None:
        return 0, []
    score = 0
    notes: list[str] = []
    if t.golden_cross:
        score += 1
        notes.append("technical: 50/200 SMA in uptrend")
    elif t.sma_50 and t.sma_200 and t.sma_50 < t.sma_200:
        score -= 1
        notes.append("technical: 50/200 SMA in downtrend")
    if t.oversold:
        score += 1
        notes.append("technical: RSI oversold (<30)")
    if t.overbought:
        score -= 1
        notes.append("technical: RSI overbought (>70)")
    if "macd_bullish" in t.notes:
        score += 1
        notes.append("technical: MACD bullish crossover")
    if "below_lower_band" in t.notes:
        score += 1
        notes.append("technical: price below lower Bollinger band")
    if "above_upper_band" in t.notes:
        score -= 1
        notes.append("technical: price above upper Bollinger band")
    return score, notes


def _score_fundamental(v: ValuationReading | None) -> tuple[int, list[str]]:
    if v is None:
        return 0, []
    score = 0
    notes: list[str] = []
    if "low_pe" in v.notes:
        score += 1
        notes.append("fundamental: low P/E")
    if "rich_pe" in v.notes:
        score -= 1
        notes.append("fundamental: stretched P/E")
    if "low_peg" in v.notes:
        score += 1
        notes.append("fundamental: PEG below 0.5 (growth at reasonable price)")
    if "high_peg" in v.notes:
        score -= 1
        notes.append("fundamental: PEG above 2 (overpaying for growth)")
    if "leveraged" in v.notes:
        score -= 1
        notes.append("fundamental: high debt/equity")
    if "high_yield" in v.notes:
        score += 1
        notes.append("fundamental: dividend yield > 5%")
    if v.upside_to_mean_target and v.upside_to_mean_target > 0.20:
        score += 1
        notes.append(f"analyst mean target implies +{float(v.upside_to_mean_target):.0%} upside")
    if v.upside_to_mean_target and v.upside_to_mean_target < -0.10:
        score -= 1
        notes.append(f"analyst mean target implies {float(v.upside_to_mean_target):.0%} downside")
    if "street_bullish" in v.notes:
        score += 1
        notes.append("fundamental: analyst consensus buy/strong buy")
    return score, notes


def _score_portfolio(signals: Iterable[PortfolioSignal]) -> tuple[int, list[str], bool]:
    score = 0
    notes: list[str] = []
    harvest = False
    for s in signals:
        if s.kind == "tax_loss_harvest":
            harvest = True
            score -= 2
            notes.append(f"portfolio: {s.summary}")
        elif s.kind == "concentration":
            score -= 1
            notes.append(f"portfolio: {s.summary}")
        elif s.kind == "aging_lot":
            notes.append(f"portfolio: {s.summary}")
    return score, notes, harvest


def _to_action(score: int, harvest: bool) -> Action:
    if harvest and score <= -2:
        return Action.HARVEST_LOSS
    if score >= 4:
        return Action.STRONG_BUY
    if score >= 2:
        return Action.BUY
    if score <= -4:
        return Action.STRONG_SELL
    if score <= -2:
        return Action.SELL
    return Action.HOLD


@dataclass
class SignalScorer:
    def score(
        self,
        symbol: str,
        technical: TechnicalReading | None = None,
        fundamental: ValuationReading | None = None,
        portfolio: Iterable[PortfolioSignal] = (),
    ) -> ScoredSignal:
        t_score, t_notes = _score_technical(technical)
        f_score, f_notes = _score_fundamental(fundamental)
        p_score, p_notes, harvest = _score_portfolio(list(portfolio))
        total = t_score + f_score + p_score
        return ScoredSignal(
            symbol=symbol,
            score=total,
            action=_to_action(total, harvest),
            rationale=t_notes + f_notes + p_notes,
        )
