"""Account, institution, and balance-snapshot models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import Field, field_validator

from monarch_insights.models._base import MonarchModel, money, parse_date, parse_datetime


class AccountType(str, Enum):
    """Top-level Monarch account categories.

    Values mirror the strings Monarch returns from ``GetAccountTypeOptions``. Anything
    we haven't mapped explicitly falls through to ``OTHER`` instead of raising.
    """

    DEPOSITORY = "depository"
    CREDIT = "credit"
    BROKERAGE = "brokerage"
    LOAN = "loan"
    REAL_ESTATE = "real_estate"
    VEHICLE = "vehicle"
    CRYPTOCURRENCY = "cryptocurrency"
    VALUABLES = "valuables"
    OTHER_ASSET = "other_asset"
    OTHER_LIABILITY = "other_liability"
    OTHER = "other"

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        return cls.OTHER


class AccountSubtype(str, Enum):
    """Common Monarch subtypes; we keep the list small and lean on ``OTHER``."""

    CHECKING = "checking"
    SAVINGS = "savings"
    MONEY_MARKET = "money_market"
    CD = "cd"
    CREDIT_CARD = "credit_card"
    BROKERAGE = "brokerage"
    IRA = "ira"
    ROTH_IRA = "roth_ira"
    ROLLOVER_IRA = "rollover_ira"
    SEP_IRA = "sep_ira"
    TRADITIONAL_401K = "401k"
    ROTH_401K = "roth_401k"
    HSA = "hsa"
    FSA = "fsa"
    FIVE_TWO_NINE = "529"
    TRUST = "trust"
    MORTGAGE = "mortgage"
    AUTO_LOAN = "auto_loan"
    STUDENT_LOAN = "student_loan"
    PERSONAL_LOAN = "personal_loan"
    HELOC = "heloc"
    CRYPTO = "cryptocurrency"
    REAL_ESTATE = "real_estate"
    VEHICLE = "vehicle"
    OTHER = "other"

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        return cls.OTHER


class Institution(MonarchModel):
    """A Plaid/MX-backed financial institution Monarch is syncing from."""

    id: str
    name: str
    url: Optional[str] = None
    logo_url: Optional[str] = Field(default=None, alias="logo")
    primary_color: Optional[str] = Field(default=None, alias="primaryColor")
    plaid_institution_id: Optional[str] = Field(default=None, alias="plaidInstitutionId")
    status: Optional[str] = None
    last_refreshed_at: Optional[datetime] = Field(default=None, alias="lastRefreshedAt")

    @field_validator("last_refreshed_at", mode="before")
    @classmethod
    def _parse_dt(cls, v):
        return parse_datetime(v)


class Account(MonarchModel):
    """A single account Monarch knows about (synced or manual)."""

    id: str
    display_name: str = Field(alias="displayName")
    type: AccountType = Field(alias="type")
    subtype: AccountSubtype = Field(default=AccountSubtype.OTHER, alias="subtype")

    current_balance: Optional[Decimal] = Field(default=None, alias="currentBalance")
    available_balance: Optional[Decimal] = Field(default=None, alias="availableBalance")
    display_balance: Optional[Decimal] = Field(default=None, alias="displayBalance")

    is_asset: Optional[bool] = Field(default=None, alias="isAsset")
    is_hidden: bool = Field(default=False, alias="isHidden")
    is_manual: bool = Field(default=False, alias="isManual")
    include_in_net_worth: bool = Field(default=True, alias="includeInNetWorth")
    hide_from_summary_list: bool = Field(default=False, alias="hideFromList")
    hide_transactions_from_reports: bool = Field(default=False, alias="hideTransactionsFromReports")

    institution: Optional[Institution] = None
    mask: Optional[str] = None
    currency: str = Field(default="USD", alias="currency")
    sync_disabled: bool = Field(default=False, alias="syncDisabled")
    deactivated_at: Optional[datetime] = Field(default=None, alias="deactivatedAt")
    last_balance_at: Optional[datetime] = Field(default=None, alias="updatedAt")
    created_at: Optional[datetime] = Field(default=None, alias="createdAt")

    @field_validator("current_balance", "available_balance", "display_balance", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v)

    @field_validator("deactivated_at", "last_balance_at", "created_at", mode="before")
    @classmethod
    def _parse_dt(cls, v):
        return parse_datetime(v)

    @property
    def is_investment(self) -> bool:
        return self.type == AccountType.BROKERAGE

    @property
    def is_liability(self) -> bool:
        return self.type in {
            AccountType.CREDIT,
            AccountType.LOAN,
            AccountType.OTHER_LIABILITY,
        }

    @property
    def signed_balance(self) -> Decimal | None:
        """Net-worth-friendly balance: liabilities are negated."""
        if self.current_balance is None:
            return None
        return -self.current_balance if self.is_liability else self.current_balance


class AccountSnapshot(MonarchModel):
    """A single point-in-time balance reading for one account."""

    account_id: str = Field(alias="accountId")
    on_date: date = Field(alias="date")
    balance: Decimal

    @field_validator("on_date", mode="before")
    @classmethod
    def _parse_d(cls, v):
        return parse_date(v)

    @field_validator("balance", mode="before")
    @classmethod
    def _parse_money(cls, v):
        return money(v) or Decimal(0)
