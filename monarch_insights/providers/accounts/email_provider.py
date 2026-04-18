"""Generic e-mail-derived account provider.

For institutions without a public API (Chase, Citi, Barclays, Amex, Bilt, Marcus, Toyota
Financial Services, etc.), we reach in via Gmail using vendor-specific subject patterns.

This module owns the *subject + parsing rules table*; the actual Gmail fetch lives in
``providers/google/gmail.py``. Splitting them lets us add a vendor by editing the rules
table without touching IMAP code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Iterable

from monarch_insights.providers.accounts.base import (
    AccountSnapshot,
    StatementReference,
    TradeRecord,
)


@dataclass
class EmailSignal:
    """A parsed email payload that maps to a balance, trade, or statement."""

    institution: str
    kind: str  # "balance" | "trade" | "statement" | "alert"
    received_at: datetime
    subject: str
    sender: str
    body: str
    extracted: dict = field(default_factory=dict)
    message_id: str | None = None


@dataclass
class EmailRule:
    institution: str
    sender_match: re.Pattern
    subject_match: re.Pattern
    extractor: Callable[[str, str, datetime], dict]
    kind: str = "balance"


def _money(s: str | None) -> Decimal | None:
    if not s:
        return None
    cleaned = s.replace(",", "").replace("$", "").strip()
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _re(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(pattern, flags)


def _extract_balance(body: str, subject: str, received: datetime) -> dict:
    m = re.search(r"\$?([\d,]+\.\d{2})", body) or re.search(r"\$?([\d,]+\.\d{2})", subject)
    return {"balance": _money(m.group(1) if m else None)}


def _extract_payment_due(body: str, subject: str, received: datetime) -> dict:
    amt = re.search(r"\$([\d,]+\.\d{2})", body)
    due = re.search(r"due\s+(?:on\s+)?(\w+\s+\d{1,2},?\s+\d{4})", body, re.IGNORECASE)
    return {
        "payment_due_amount": _money(amt.group(1) if amt else None),
        "payment_due_date_raw": due.group(1) if due else None,
    }


def _extract_statement(body: str, subject: str, received: datetime) -> dict:
    period = re.search(r"statement\s+for\s+([A-Za-z]+\s+\d{4})", body, re.IGNORECASE)
    return {"period_label": period.group(1) if period else None}


def _extract_transaction(body: str, subject: str, received: datetime) -> dict:
    amt = re.search(r"\$([\d,]+\.\d{2})", body) or re.search(r"\$([\d,]+\.\d{2})", subject)
    merchant = re.search(r"at\s+([A-Z][A-Za-z0-9 &'\.-]{2,40})", body)
    return {
        "amount": _money(amt.group(1) if amt else None),
        "merchant": merchant.group(1).strip() if merchant else None,
    }


DEFAULT_RULES: list[EmailRule] = [
    EmailRule(
        institution="Chase",
        sender_match=_re(r"@chase\.com$|@alerts\.chase\.com$|@chasemail\.chase\.com$"),
        subject_match=_re(r"transaction|alert|statement|payment", re.I),
        extractor=_extract_transaction,
        kind="alert",
    ),
    EmailRule(
        institution="American Express",
        sender_match=_re(r"@americanexpress\.com$|@welcome\.aexp\.com$"),
        subject_match=_re(r"transaction|charge|statement|payment", re.I),
        extractor=_extract_transaction,
        kind="alert",
    ),
    EmailRule(
        institution="Citi",
        sender_match=_re(r"@citi\.com$|@email\.citi\.com$|@accountonline\.com$"),
        subject_match=_re(r"transaction|alert|statement|payment", re.I),
        extractor=_extract_transaction,
        kind="alert",
    ),
    EmailRule(
        institution="Barclays",
        sender_match=_re(r"@barclaysus\.com$|@barclaycardus\.com$"),
        subject_match=_re(r"alert|payment|statement", re.I),
        extractor=_extract_payment_due,
        kind="statement",
    ),
    EmailRule(
        institution="Bilt",
        sender_match=_re(r"@biltrewards\.com$|@bilt\.com$"),
        subject_match=_re(r"transaction|payment|statement|points", re.I),
        extractor=_extract_transaction,
        kind="alert",
    ),
    EmailRule(
        institution="Marcus",
        sender_match=_re(r"@marcus\.com$|@goldmansachs\.com$"),
        subject_match=_re(r"statement|interest|deposit|transfer", re.I),
        extractor=_extract_balance,
        kind="balance",
    ),
    EmailRule(
        institution="Toyota Financial Services",
        sender_match=_re(r"@toyotafinancial\.com$|@toyota\.com$"),
        subject_match=_re(r"payment|statement|due|account", re.I),
        extractor=_extract_payment_due,
        kind="statement",
    ),
    EmailRule(
        institution="Schwab",
        sender_match=_re(r"@schwab\.com$|@email\.schwab\.com$"),
        subject_match=_re(r"trade confirmation|statement|deposit|transfer|balance", re.I),
        extractor=_extract_transaction,
        kind="trade",
    ),
    EmailRule(
        institution="Robinhood",
        sender_match=_re(r"@robinhood\.com$"),
        subject_match=_re(r"trade|order|deposit|withdrawal|statement|tax", re.I),
        extractor=_extract_transaction,
        kind="trade",
    ),
]


class EmailAccountProvider:
    """Maps Gmail messages → account signals using ``DEFAULT_RULES``.

    The actual Gmail fetch is provided to ``ingest`` by the caller; we keep this class
    independent of any specific Gmail client.
    """

    name = "email-derived"
    institution = "various"
    auth_kind = "email"

    def __init__(self, rules: list[EmailRule] | None = None) -> None:
        self.rules = rules or DEFAULT_RULES

    def classify(
        self, sender: str, subject: str, body: str, received: datetime, message_id: str | None = None
    ) -> EmailSignal | None:
        for rule in self.rules:
            if rule.sender_match.search(sender) and rule.subject_match.search(subject):
                return EmailSignal(
                    institution=rule.institution,
                    kind=rule.kind,
                    received_at=received,
                    subject=subject,
                    sender=sender,
                    body=body[:2000],
                    extracted=rule.extractor(body, subject, received),
                    message_id=message_id,
                )
        return None

    def ingest(self, messages: Iterable[dict]) -> list[EmailSignal]:
        signals: list[EmailSignal] = []
        for msg in messages:
            signal = self.classify(
                sender=msg.get("from", ""),
                subject=msg.get("subject", ""),
                body=msg.get("body", ""),
                received=msg.get("received_at", datetime.utcnow()),
                message_id=msg.get("id"),
            )
            if signal:
                signals.append(signal)
        return signals

    # ----- Conformance to AccountProvider protocol (best-effort) ------------

    async def list_accounts(self) -> list[AccountSnapshot]:
        return []  # populated by ingest() pipelines

    async def list_trades(
        self, account_id: str, start: date | None = None, end: date | None = None
    ) -> list[TradeRecord]:
        return []

    async def list_statements(self, account_id: str, since: date | None = None) -> list[StatementReference]:
        return []
