"""Transaction, split, and merchant models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import Field, field_validator

from monarch_insights.models._base import MonarchModel, money, parse_date, parse_datetime


class Merchant(MonarchModel):
    id: str
    name: str
    logo_url: Optional[str] = Field(default=None, alias="logoUrl")
    transaction_count: Optional[int] = Field(default=None, alias="transactionCount")
    recurring_transaction_stream_id: Optional[str] = Field(
        default=None, alias="recurringTransactionStreamId"
    )


class TransactionSplit(MonarchModel):
    """A single sub-transaction within a split."""

    id: str
    amount: Decimal
    notes: Optional[str] = None
    category_id: Optional[str] = Field(default=None, alias="categoryId")
    merchant_name: Optional[str] = Field(default=None, alias="merchantName")

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v) or Decimal(0)


class Transaction(MonarchModel):
    """A single posted (or pending) transaction.

    Sign convention: Monarch returns *negative* amounts for outflows / spending and
    positive for inflows / income. We preserve that — analytics modules normalize.
    """

    id: str
    on_date: date = Field(alias="date")
    amount: Decimal
    pending: bool = False
    notes: Optional[str] = None
    plaid_name: Optional[str] = Field(default=None, alias="plaidName")
    original_description: Optional[str] = Field(default=None, alias="originalDescription")

    account_id: str = Field(alias="accountId")
    account_display_name: Optional[str] = Field(default=None, alias="accountDisplayName")

    category_id: Optional[str] = Field(default=None, alias="categoryId")
    category_name: Optional[str] = Field(default=None, alias="categoryName")
    category_group_id: Optional[str] = Field(default=None, alias="categoryGroupId")

    merchant_id: Optional[str] = Field(default=None, alias="merchantId")
    merchant_name: Optional[str] = Field(default=None, alias="merchantName")

    tag_ids: list[str] = Field(default_factory=list, alias="tagIds")
    tag_names: list[str] = Field(default_factory=list, alias="tagNames")

    is_recurring: bool = Field(default=False, alias="isRecurring")
    is_split: bool = Field(default=False, alias="isSplit")
    is_hidden_from_reports: bool = Field(default=False, alias="hideFromReports")
    needs_review: bool = Field(default=False, alias="needsReview")

    splits: list[TransactionSplit] = Field(default_factory=list)

    created_at: Optional[datetime] = Field(default=None, alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, alias="updatedAt")

    @field_validator("on_date", mode="before")
    @classmethod
    def _parse_d(cls, v):
        return parse_date(v)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v) or Decimal(0)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_dt(cls, v):
        return parse_datetime(v)

    @property
    def is_outflow(self) -> bool:
        return self.amount < 0

    @property
    def is_inflow(self) -> bool:
        return self.amount > 0

    @property
    def absolute_amount(self) -> Decimal:
        return abs(self.amount)
