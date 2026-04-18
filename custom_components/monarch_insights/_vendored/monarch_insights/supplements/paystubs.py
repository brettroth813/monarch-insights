"""Paystub structure: gross → deductions → net, plus YTD running totals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class LineItemCategory(str, Enum):
    EARNINGS = "earnings"
    TAX = "tax"
    DEDUCTION = "deduction"
    BENEFIT = "benefit"
    EMPLOYER = "employer"


@dataclass
class PaystubLineItem:
    id: str
    category: LineItemCategory
    label: str
    amount: Decimal
    ytd_amount: Decimal | None = None
    pretax: bool = False


@dataclass
class Paystub:
    id: str
    employer: str
    period_start: date
    period_end: date
    paid_on: date
    gross_pay: Decimal
    net_pay: Decimal
    line_items: list[PaystubLineItem] = field(default_factory=list)
    document_id: str | None = None
    transaction_id: str | None = None

    @classmethod
    def new(cls, employer: str, paid_on: date, gross: Decimal, net: Decimal,
            period_start: date | None = None, period_end: date | None = None) -> Paystub:
        return cls(
            id=str(uuid.uuid4()),
            employer=employer,
            period_start=period_start or paid_on,
            period_end=period_end or paid_on,
            paid_on=paid_on,
            gross_pay=gross,
            net_pay=net,
        )

    def add_item(
        self,
        category: LineItemCategory | str,
        label: str,
        amount: Decimal | float | int,
        ytd: Decimal | float | int | None = None,
        pretax: bool = False,
    ) -> PaystubLineItem:
        item = PaystubLineItem(
            id=str(uuid.uuid4()),
            category=LineItemCategory(category) if isinstance(category, str) else category,
            label=label,
            amount=Decimal(str(amount)),
            ytd_amount=Decimal(str(ytd)) if ytd is not None else None,
            pretax=pretax,
        )
        self.line_items.append(item)
        return item

    @property
    def total_taxes(self) -> Decimal:
        return sum(
            (li.amount for li in self.line_items if li.category == LineItemCategory.TAX),
            Decimal(0),
        )

    @property
    def total_deductions(self) -> Decimal:
        return sum(
            (
                li.amount
                for li in self.line_items
                if li.category in (LineItemCategory.DEDUCTION, LineItemCategory.BENEFIT)
            ),
            Decimal(0),
        )

    @property
    def total_pretax(self) -> Decimal:
        return sum((li.amount for li in self.line_items if li.pretax), Decimal(0))

    @property
    def effective_tax_rate(self) -> Decimal | None:
        if self.gross_pay == 0:
            return None
        return self.total_taxes / self.gross_pay

    @property
    def net_check_match(self) -> Decimal:
        """Computed net (gross - taxes - deductions) vs. reported net. Should be ~zero."""
        computed = self.gross_pay - self.total_taxes - self.total_deductions
        return computed - self.net_pay

    def to_storage_dict(self) -> dict:
        return {
            "id": self.id,
            "employer": self.employer,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "paid_on": self.paid_on.isoformat(),
            "gross_pay": float(self.gross_pay),
            "net_pay": float(self.net_pay),
            "document_id": self.document_id,
            "transaction_id": self.transaction_id,
            "detail": {"item_count": len(self.line_items)},
            "line_items": [
                {
                    "id": li.id,
                    "category": li.category.value,
                    "label": li.label,
                    "amount": float(li.amount),
                    "ytd_amount": float(li.ytd_amount) if li.ytd_amount is not None else None,
                    "pretax": li.pretax,
                }
                for li in self.line_items
            ],
        }
