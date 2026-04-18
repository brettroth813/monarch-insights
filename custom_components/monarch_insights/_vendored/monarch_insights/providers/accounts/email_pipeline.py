"""Bridge from EmailAccountProvider signals → SupplementStore writes.

When an :class:`EmailSignal` looks like a brokerage trade confirmation, we want a
``CostBasisLot`` (for buys) or a ``Disposal`` (for sells) automatically written to the
supplements DB. This is the highest-leverage email parse: it eliminates the most
common manual data-entry chore (typing in 1099-B values).

The parsing strategy is deliberately conservative — the regex tables only fire when we
can extract *all* required fields. Anything ambiguous is logged and surfaced as an
``InfoRequest`` for the user to confirm.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from monarch_insights.gaps.requests import InfoRequest, RequestKind, Severity
from monarch_insights.observability import EventLog, get_logger
from monarch_insights.providers.accounts.email_provider import EmailSignal
from monarch_insights.supplements.store import SupplementStore

log = get_logger(__name__)


# Each pattern must capture: side (buy/sell), quantity, ticker, price, optional fees.
# Patterns are intentionally tight; ambiguous emails fall through to the info-request
# path so the user gets a chance to provide the missing pieces.
TRADE_PATTERNS: list[re.Pattern] = [
    # Schwab style: "You bought 10 shares of AAPL at $187.45"
    re.compile(
        r"You\s+(?P<side>bought|sold)\s+(?P<qty>[\d,.]+)\s+shares?\s+of\s+(?P<ticker>[A-Z][A-Z0-9.]{0,5})"
        r"\s+(?:at|@)\s+\$?(?P<price>[\d,.]+)",
        re.IGNORECASE,
    ),
    # Robinhood style: "Order filled: 5 NVDA @ $480.21"
    re.compile(
        r"(?:Order\s+filled[:\s]+)?(?P<qty>[\d,.]+)\s+(?P<ticker>[A-Z][A-Z0-9.]{0,5})\s+@\s+\$?(?P<price>[\d,.]+)",
    ),
    # Generic confirmation: "Trade confirmation - BUY 100 SCHB at $52.10"
    re.compile(
        r"(?P<side>buy|sell)\s+(?P<qty>[\d,.]+)\s+(?P<ticker>[A-Z][A-Z0-9.]{0,5})\s+(?:at|@)\s+\$?(?P<price>[\d,.]+)",
        re.IGNORECASE,
    ),
]


@dataclass
class TradeIngestResult:
    """Outcome of running :func:`ingest_trade_signals` over a batch of emails."""

    lots_added: list[str]              # cost-basis lot IDs
    disposals_added: list[str]         # disposal IDs
    info_requests: list[InfoRequest]   # ambiguous emails that need user confirmation
    skipped: int                        # signals that didn't look like trades

    @property
    def total_processed(self) -> int:
        return len(self.lots_added) + len(self.disposals_added) + len(self.info_requests) + self.skipped


def parse_trade(signal: EmailSignal) -> dict | None:
    """Try every pattern; return the first match as a normalised dict, else ``None``.

    The returned dict has keys: ``side``, ``qty``, ``ticker``, ``price``. ``side`` is
    forced to ``"buy"`` for unmatched-side patterns (Robinhood "fill" emails) — sells
    on RH are explicit elsewhere.
    """
    haystack = f"{signal.subject}\n{signal.body}"
    for pattern in TRADE_PATTERNS:
        match = pattern.search(haystack)
        if not match:
            continue
        groups = match.groupdict()
        side = (groups.get("side") or "buy").lower()
        side = "sell" if side.startswith("s") else "buy"
        try:
            qty = Decimal(groups["qty"].replace(",", ""))
            price = Decimal(groups["price"].replace(",", ""))
        except Exception:
            log.warning(
                "email.trade.parse_failed",
                extra={"signal_id": signal.message_id, "groups": groups},
            )
            continue
        if qty <= 0 or price <= 0:
            continue
        return {
            "side": side,
            "qty": qty,
            "ticker": groups["ticker"].upper(),
            "price": price,
        }
    return None


def ingest_trade_signals(
    signals: Iterable[EmailSignal],
    *,
    store: SupplementStore,
    account_resolver,
    event_log: EventLog | None = None,
    persist: bool = True,
) -> TradeIngestResult:
    """Walk a batch of email signals and persist matched trades.

    Args:
        signals: Iterable of :class:`EmailSignal` from
            :class:`EmailAccountProvider.ingest`.
        store: SupplementStore to write lots/disposals/info-requests into.
        account_resolver: Callable ``(institution: str) -> account_id | None`` so we
            can attribute the trade to the correct supplements account. Pass a small
            dict-backed lambda such as ``{"Schwab": "ACT_schwab_brokerage"}.get``.
        event_log: Optional structured event sink for "we wrote a lot" audit rows.
        persist: When ``False`` we skip the SQL writes (handy for dry runs / tests).

    Returns:
        :class:`TradeIngestResult` summarising what happened.
    """

    lots: list[str] = []
    disposals: list[str] = []
    info_requests: list[InfoRequest] = []
    skipped = 0

    for signal in signals:
        if signal.kind not in {"trade", "alert"}:
            skipped += 1
            continue

        parsed = parse_trade(signal)
        if parsed is None:
            # The institution sends trade emails but we couldn't pull all four fields —
            # surface as an info-request so the user can fix it manually.
            req = InfoRequest.new(
                kind=RequestKind.COST_BASIS,
                summary=(
                    f"Possible trade email from {signal.institution} couldn't be parsed "
                    f"(subject: {signal.subject[:60]!r})"
                ),
                severity=Severity.INFO,
                suggested_action="Open the email and add the lot via `monarch-insights cost-basis add`.",
                detail={
                    "institution": signal.institution,
                    "subject": signal.subject,
                    "received_at": signal.received_at.isoformat(),
                    "message_id": signal.message_id,
                },
            )
            info_requests.append(req)
            if persist:
                store.add_info_request(req.to_storage_dict())
            if event_log is not None:
                event_log.record(
                    "email.trade",
                    "unparsed",
                    {"institution": signal.institution, "message_id": signal.message_id},
                    severity="info",
                )
            continue

        account_id = account_resolver(signal.institution)
        if account_id is None:
            req = InfoRequest.new(
                kind=RequestKind.ACCOUNT_HISTORY,
                summary=(
                    f"Trade email from {signal.institution} but no mapped account; can't attribute"
                ),
                severity=Severity.WARN,
                suggested_action=(
                    "Add an account-resolver entry mapping the institution to a Monarch account ID."
                ),
                detail={"institution": signal.institution, "ticker": parsed["ticker"]},
            )
            info_requests.append(req)
            if persist:
                store.add_info_request(req.to_storage_dict())
            continue

        on_date_iso = signal.received_at.date().isoformat()
        if parsed["side"] == "buy":
            lot_id = f"email-{signal.message_id or uuid.uuid4().hex}-{parsed['ticker']}"
            if persist:
                store.add_lot(
                    {
                        "id": lot_id,
                        "account_id": account_id,
                        "ticker": parsed["ticker"],
                        "quantity": parsed["qty"],
                        "acquired_on": on_date_iso,
                        "cost_per_share": parsed["price"],
                        "fees": 0,
                        "source": f"email:{signal.institution}",
                        "notes": f"Auto-imported from {signal.institution} email",
                    }
                )
            lots.append(lot_id)
            if event_log is not None:
                event_log.record(
                    "email.trade",
                    "lot.added",
                    {
                        "institution": signal.institution,
                        "account_id": account_id,
                        "ticker": parsed["ticker"],
                        "quantity": float(parsed["qty"]),
                        "price": float(parsed["price"]),
                    },
                    ref=lot_id,
                )
        else:
            # Sells require lot-by-lot disposal logic; we record an info request so the
            # user can choose FIFO/LIFO/HIFO/specific. We don't auto-FIFO sells because
            # mistakes here ripple into tax filings.
            req = InfoRequest.new(
                kind=RequestKind.COST_BASIS,
                summary=(
                    f"Sell of {parsed['qty']} {parsed['ticker']} from {signal.institution} email — "
                    "confirm disposal method (FIFO/LIFO/HIFO/Specific) before recording."
                ),
                severity=Severity.WARN,
                suggested_action="Run `monarch-insights cost-basis dispose` to lock in.",
                related_account_id=account_id,
                related_ticker=parsed["ticker"],
                detail={
                    "qty": float(parsed["qty"]),
                    "price": float(parsed["price"]),
                    "on_date": on_date_iso,
                    "message_id": signal.message_id,
                },
            )
            info_requests.append(req)
            if persist:
                store.add_info_request(req.to_storage_dict())
            if event_log is not None:
                event_log.record(
                    "email.trade",
                    "sell.pending_user",
                    {
                        "institution": signal.institution,
                        "ticker": parsed["ticker"],
                        "qty": float(parsed["qty"]),
                    },
                    severity="warn",
                )

    return TradeIngestResult(
        lots_added=lots,
        disposals_added=disposals,
        info_requests=info_requests,
        skipped=skipped,
    )
