"""Lightweight technical indicators (RSI, SMA cross, Bollinger, MACD).

Pure-Python so it works without numpy/pandas; if those are present we use them for speed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import mean, stdev
from typing import Sequence

from monarch_insights.providers.market_data.base import HistoricalBar


@dataclass
class TechnicalReading:
    symbol: str
    as_of: date
    close: Decimal
    sma_50: Decimal | None
    sma_200: Decimal | None
    rsi_14: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    bollinger_upper: Decimal | None
    bollinger_lower: Decimal | None
    notes: list[str]

    @property
    def golden_cross(self) -> bool:
        if self.sma_50 is None or self.sma_200 is None:
            return False
        return self.sma_50 > self.sma_200

    @property
    def oversold(self) -> bool:
        return self.rsi_14 is not None and self.rsi_14 < Decimal(30)

    @property
    def overbought(self) -> bool:
        return self.rsi_14 is not None and self.rsi_14 > Decimal(70)


class TechnicalSignals:
    @staticmethod
    def _ema(values: Sequence[float], period: int) -> list[float]:
        if not values:
            return []
        k = 2 / (period + 1)
        out = [values[0]]
        for v in values[1:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    @staticmethod
    def _rsi(values: Sequence[float], period: int = 14) -> float | None:
        if len(values) < period + 1:
            return None
        deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
        gains = [max(d, 0) for d in deltas[-period:]]
        losses = [-min(d, 0) for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period or 1e-9
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @classmethod
    def reading(cls, bars: Sequence[HistoricalBar]) -> TechnicalReading | None:
        if not bars:
            return None
        sorted_bars = sorted(bars, key=lambda b: b.on_date)
        closes = [float(b.close) for b in sorted_bars]
        latest = sorted_bars[-1]
        notes: list[str] = []

        sma_50 = Decimal(str(mean(closes[-50:]))) if len(closes) >= 50 else None
        sma_200 = Decimal(str(mean(closes[-200:]))) if len(closes) >= 200 else None
        rsi = cls._rsi(closes, 14)
        rsi_dec = Decimal(str(rsi)) if rsi is not None else None

        ema_12 = cls._ema(closes, 12)
        ema_26 = cls._ema(closes, 26)
        macd_line = [a - b for a, b in zip(ema_12[-len(ema_26):], ema_26)]
        macd_signal = cls._ema(macd_line, 9)
        macd = Decimal(str(macd_line[-1])) if macd_line else None
        macd_sig = Decimal(str(macd_signal[-1])) if macd_signal else None

        upper, lower = (None, None)
        if len(closes) >= 20:
            window = closes[-20:]
            sd = stdev(window) if len(window) > 1 else 0
            mid = mean(window)
            upper = Decimal(str(mid + 2 * sd))
            lower = Decimal(str(mid - 2 * sd))

        if sma_50 and sma_200:
            notes.append("uptrend" if sma_50 > sma_200 else "downtrend")
        if rsi_dec is not None:
            if rsi_dec < 30:
                notes.append("oversold")
            elif rsi_dec > 70:
                notes.append("overbought")
        if macd is not None and macd_sig is not None:
            notes.append("macd_bullish" if macd > macd_sig else "macd_bearish")
        if lower and Decimal(str(closes[-1])) < lower:
            notes.append("below_lower_band")
        if upper and Decimal(str(closes[-1])) > upper:
            notes.append("above_upper_band")

        return TechnicalReading(
            symbol=latest.symbol,
            as_of=latest.on_date,
            close=Decimal(str(closes[-1])),
            sma_50=sma_50,
            sma_200=sma_200,
            rsi_14=rsi_dec,
            macd=macd,
            macd_signal=macd_sig,
            bollinger_upper=upper,
            bollinger_lower=lower,
            notes=notes,
        )
