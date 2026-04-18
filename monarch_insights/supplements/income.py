"""Income sources and events.

Lets the tax module distinguish W-2, 1099, K-1, dividend, interest, rental, and RSU
income — Monarch's category system collapses this distinction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class IncomeKind(str, Enum):
    W2 = "w2"
    NEC_1099 = "1099_nec"
    MISC_1099 = "1099_misc"
    DIV_1099 = "1099_div"
    INT_1099 = "1099_int"
    B_1099 = "1099_b"
    K1 = "k1"
    RSU = "rsu"
    INTEREST = "interest"
    DIVIDEND = "dividend"
    CAPITAL_GAIN = "capital_gain"
    RENTAL = "rental"
    ROYALTY = "royalty"
    OTHER = "other"

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        return cls.OTHER


@dataclass
class IncomeSource:
    id: str
    name: str
    source_type: IncomeKind
    employer_or_payer: str | None = None
    notes: str | None = None
    is_active: bool = True

    @classmethod
    def new(cls, name: str, source_type: IncomeKind | str, **kwargs) -> IncomeSource:
        return cls(
            id=str(uuid.uuid4()),
            name=name,
            source_type=IncomeKind(source_type) if isinstance(source_type, str) else source_type,
            **kwargs,
        )


@dataclass
class IncomeEvent:
    id: str
    source_id: str
    on_date: date
    gross_amount: Decimal
    taxable_amount: Decimal | None = None
    withholding_amount: Decimal = Decimal(0)
    detail: dict = field(default_factory=dict)
    transaction_id: str | None = None

    @classmethod
    def new(cls, source_id: str, on_date: date, gross: Decimal, **kwargs) -> IncomeEvent:
        return cls(id=str(uuid.uuid4()), source_id=source_id, on_date=on_date, gross_amount=gross, **kwargs)

    @property
    def effective_taxable(self) -> Decimal:
        return self.taxable_amount if self.taxable_amount is not None else self.gross_amount
