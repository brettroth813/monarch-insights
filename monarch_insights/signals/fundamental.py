"""Valuation reading from fundamentals + analyst targets."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from monarch_insights.providers.market_data.base import AnalystTargets, Fundamentals, Quote


@dataclass
class ValuationReading:
    symbol: str
    pe: Decimal | None
    forward_pe: Decimal | None
    peg: Decimal | None
    dividend_yield: Decimal | None
    debt_to_equity: Decimal | None
    analyst_consensus: str | None
    upside_to_mean_target: Decimal | None
    upside_to_high_target: Decimal | None
    notes: list[str]


# Sector medians are *very* approximate; revisit per-sector if precision matters.
PE_SANITY = (Decimal(8), Decimal(35))
PEG_SANITY = (Decimal("0.5"), Decimal("2.0"))


class FundamentalSignals:
    @staticmethod
    def reading(
        symbol: str,
        quote: Quote | None,
        fundamentals: Fundamentals | None,
        targets: AnalystTargets | None,
    ) -> ValuationReading:
        notes: list[str] = []
        upside_mean = None
        upside_high = None
        if quote and targets and targets.mean and quote.price:
            upside_mean = (targets.mean - quote.price) / quote.price
        if quote and targets and targets.high and quote.price:
            upside_high = (targets.high - quote.price) / quote.price

        if fundamentals:
            if fundamentals.pe_ratio:
                if fundamentals.pe_ratio < PE_SANITY[0]:
                    notes.append("low_pe")
                elif fundamentals.pe_ratio > PE_SANITY[1]:
                    notes.append("rich_pe")
            if fundamentals.peg_ratio:
                if fundamentals.peg_ratio < PEG_SANITY[0]:
                    notes.append("low_peg")
                elif fundamentals.peg_ratio > PEG_SANITY[1]:
                    notes.append("high_peg")
            if fundamentals.dividend_yield and fundamentals.dividend_yield > Decimal("0.05"):
                notes.append("high_yield")
            if fundamentals.debt_to_equity and fundamentals.debt_to_equity > Decimal(2):
                notes.append("leveraged")

        if targets and (targets.consensus or "").lower() in ("strong buy", "buy"):
            notes.append("street_bullish")
        if upside_mean is not None and upside_mean > Decimal("0.20"):
            notes.append("street_target_upside_>20")

        return ValuationReading(
            symbol=symbol,
            pe=fundamentals.pe_ratio if fundamentals else None,
            forward_pe=fundamentals.forward_pe if fundamentals else None,
            peg=fundamentals.peg_ratio if fundamentals else None,
            dividend_yield=fundamentals.dividend_yield if fundamentals else None,
            debt_to_equity=fundamentals.debt_to_equity if fundamentals else None,
            analyst_consensus=(targets.consensus if targets else None),
            upside_to_mean_target=upside_mean,
            upside_to_high_target=upside_high,
            notes=notes,
        )
