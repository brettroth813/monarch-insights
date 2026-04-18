"""Technical-signal smoke test."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from monarch_insights.providers.market_data.base import HistoricalBar
from monarch_insights.signals.scorer import Action, SignalScorer
from monarch_insights.signals.technical import TechnicalSignals


def _bars(closes):
    today = date.today()
    return [
        HistoricalBar(
            symbol="TEST",
            on_date=today - timedelta(days=len(closes) - i),
            open=Decimal(c),
            high=Decimal(c),
            low=Decimal(c),
            close=Decimal(c),
        )
        for i, c in enumerate(closes)
    ]


def test_technical_reading_uptrend():
    closes = list(range(100, 350))
    reading = TechnicalSignals.reading(_bars(closes))
    assert reading is not None
    assert reading.golden_cross
    assert reading.overbought


def test_signal_scorer_combines():
    closes = list(range(200, 50, -1))  # downtrend
    technical = TechnicalSignals.reading(_bars(closes))
    scored = SignalScorer().score("TEST", technical=technical)
    assert scored.action in (Action.SELL, Action.STRONG_SELL, Action.HOLD)
