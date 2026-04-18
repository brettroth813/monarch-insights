"""Federal bracket utilities — 2025 brackets baked in, override-able for other years."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Sequence


class FilingStatus(str, Enum):
    SINGLE = "single"
    MARRIED_JOINT = "mfj"
    MARRIED_SEPARATE = "mfs"
    HEAD_OF_HOUSEHOLD = "hoh"


@dataclass(frozen=True)
class TaxBracket:
    floor: Decimal
    ceiling: Decimal | None
    rate: Decimal


_BRACKETS_2025: dict[FilingStatus, list[TaxBracket]] = {
    FilingStatus.SINGLE: [
        TaxBracket(Decimal(0), Decimal(11925), Decimal("0.10")),
        TaxBracket(Decimal(11925), Decimal(48475), Decimal("0.12")),
        TaxBracket(Decimal(48475), Decimal(103350), Decimal("0.22")),
        TaxBracket(Decimal(103350), Decimal(197300), Decimal("0.24")),
        TaxBracket(Decimal(197300), Decimal(250525), Decimal("0.32")),
        TaxBracket(Decimal(250525), Decimal(626350), Decimal("0.35")),
        TaxBracket(Decimal(626350), None, Decimal("0.37")),
    ],
    FilingStatus.MARRIED_JOINT: [
        TaxBracket(Decimal(0), Decimal(23850), Decimal("0.10")),
        TaxBracket(Decimal(23850), Decimal(96950), Decimal("0.12")),
        TaxBracket(Decimal(96950), Decimal(206700), Decimal("0.22")),
        TaxBracket(Decimal(206700), Decimal(394600), Decimal("0.24")),
        TaxBracket(Decimal(394600), Decimal(501050), Decimal("0.32")),
        TaxBracket(Decimal(501050), Decimal(751600), Decimal("0.35")),
        TaxBracket(Decimal(751600), None, Decimal("0.37")),
    ],
    FilingStatus.MARRIED_SEPARATE: [
        TaxBracket(Decimal(0), Decimal(11925), Decimal("0.10")),
        TaxBracket(Decimal(11925), Decimal(48475), Decimal("0.12")),
        TaxBracket(Decimal(48475), Decimal(103350), Decimal("0.22")),
        TaxBracket(Decimal(103350), Decimal(197300), Decimal("0.24")),
        TaxBracket(Decimal(197300), Decimal(250525), Decimal("0.32")),
        TaxBracket(Decimal(250525), Decimal(375800), Decimal("0.35")),
        TaxBracket(Decimal(375800), None, Decimal("0.37")),
    ],
    FilingStatus.HEAD_OF_HOUSEHOLD: [
        TaxBracket(Decimal(0), Decimal(17000), Decimal("0.10")),
        TaxBracket(Decimal(17000), Decimal(64850), Decimal("0.12")),
        TaxBracket(Decimal(64850), Decimal(103350), Decimal("0.22")),
        TaxBracket(Decimal(103350), Decimal(197300), Decimal("0.24")),
        TaxBracket(Decimal(197300), Decimal(250500), Decimal("0.32")),
        TaxBracket(Decimal(250500), Decimal(626350), Decimal("0.35")),
        TaxBracket(Decimal(626350), None, Decimal("0.37")),
    ],
}


def federal_brackets(status: FilingStatus | str = FilingStatus.SINGLE) -> Sequence[TaxBracket]:
    if isinstance(status, str):
        status = FilingStatus(status)
    return _BRACKETS_2025[status]


def federal_tax(income: Decimal, status: FilingStatus | str = FilingStatus.SINGLE) -> Decimal:
    income = Decimal(str(income))
    if income <= 0:
        return Decimal(0)
    brackets = federal_brackets(status)
    total = Decimal(0)
    for b in brackets:
        if b.ceiling is None or income > b.ceiling:
            slice_income = ((b.ceiling or income) - b.floor)
            total += slice_income * b.rate
            if b.ceiling is None:
                break
        else:
            total += (income - b.floor) * b.rate
            break
    return total


def marginal_rate(income: Decimal, status: FilingStatus | str = FilingStatus.SINGLE) -> Decimal:
    income = Decimal(str(income))
    for b in federal_brackets(status):
        if b.ceiling is None or income < b.ceiling:
            return b.rate
    return federal_brackets(status)[-1].rate


def bracket_headroom(
    income: Decimal, status: FilingStatus | str = FilingStatus.SINGLE
) -> dict:
    income = Decimal(str(income))
    for b in federal_brackets(status):
        if b.ceiling is None or income < b.ceiling:
            ceiling = b.ceiling or income
            return {
                "current_bracket_rate": float(b.rate),
                "headroom_dollars": float(ceiling - income) if b.ceiling else float("inf"),
                "next_bracket_rate": _next_rate(status, b),
                "current_bracket_top": float(b.ceiling) if b.ceiling else None,
            }
    return {}


def _next_rate(status: FilingStatus | str, current: TaxBracket) -> float | None:
    brackets = federal_brackets(status)
    for i, b in enumerate(brackets):
        if b.floor == current.floor and i + 1 < len(brackets):
            return float(brackets[i + 1].rate)
    return None
