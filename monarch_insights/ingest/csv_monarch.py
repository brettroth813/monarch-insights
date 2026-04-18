"""Importer for Monarch Money's native CSV exports.

Monarch exposes two relevant exports under Settings → Data → Export:

* **Transactions CSV** — one row per transaction with columns
  ``Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags,Owner``.
* **Balances CSV** — one row per (account, date) with columns
  ``Date,Balance,Account``.

This module turns either (or both) into :class:`Account` / :class:`Transaction` /
``AccountSnapshot`` entities and persists them via :class:`MonarchCache`, the same
local store the live-API sync writes to. Every downstream insight / forecast /
alert rule works transparently against imported data.

Design:

* **Stable account IDs.** Monarch exports identify accounts by their human-readable
  friendly name (e.g. ``"Chase Checking (...1234)"``). We derive a deterministic id
  by SHA-256-hashing that name. Re-imports of later exports update existing rows
  by the same id instead of duplicating.
* **Account-type inference.** The friendly name usually betrays the type
  (``"401k"`` → brokerage, ``"Credit Card"`` → credit, ``"Mortgage"`` → loan). When
  the heuristics can't decide we fall back to :data:`AccountType.OTHER`, which the
  insights layer tolerates.
* **Idempotent writes.** Re-importing the same file is a no-op beyond
  last-seen-at timestamps; transaction ids are stable across imports so duplicates
  don't accumulate.
* **No live data required.** The importer never touches Monarch's API — it's a
  pure local-to-local ingest. Useful for CSV-first workflows, occasional backfills,
  or environments where the API is rate-limited / broken.

Typical CLI flow::

    monarch-insights import monarch-csv \\
        --transactions path/to/Transactions.csv \\
        --balances path/to/Balances.csv

After import, every existing command — ``insight networth``, ``insight cashflow``,
``insight investments``, ``gaps scan``, etc. — runs against the imported data.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from monarch_insights.models import (
    Account,
    AccountSubtype,
    AccountType,
    Transaction,
)
from monarch_insights.storage.cache import MonarchCache

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heuristics for account classification
# ---------------------------------------------------------------------------
#
# Monarch doesn't expose the account's type in its CSV export — only the friendly
# name. The user almost always names accounts in a way that betrays the type, so a
# small keyword lookup handles most real-world cases. Anything we miss drops into
# ``AccountType.OTHER`` which the insights layer tolerates.

_TYPE_KEYWORDS: tuple[tuple[AccountType, AccountSubtype, tuple[str, ...]], ...] = (
    (AccountType.LOAN, AccountSubtype.MORTGAGE, ("mortgage",)),
    (AccountType.LOAN, AccountSubtype.AUTO_LOAN, ("auto loan", "car loan")),
    (AccountType.LOAN, AccountSubtype.STUDENT_LOAN, ("student loan", "sallie mae")),
    (AccountType.LOAN, AccountSubtype.HELOC, ("heloc", "home equity")),
    (AccountType.LOAN, AccountSubtype.PERSONAL_LOAN, ("personal loan",)),
    (AccountType.CREDIT, AccountSubtype.CREDIT_CARD, (
        "credit card", " card", "visa", "mastercard", "amex", "american express",
        "discover", "sapphire", "freedom", "citi", "barclays", "chase ink",
        "capital one", "bilt", "palladium", "platinum",
    )),
    (AccountType.BROKERAGE, AccountSubtype.ROTH_IRA, ("roth ira",)),
    (AccountType.BROKERAGE, AccountSubtype.ROLLOVER_IRA, ("rollover ira",)),
    (AccountType.BROKERAGE, AccountSubtype.SEP_IRA, ("sep ira", "sep-ira")),
    (AccountType.BROKERAGE, AccountSubtype.IRA, ("traditional ira", " ira")),
    (AccountType.BROKERAGE, AccountSubtype.ROTH_401K, ("roth 401", "roth401")),
    (AccountType.BROKERAGE, AccountSubtype.TRADITIONAL_401K, ("401k", "401(k)", "401 k")),
    (AccountType.BROKERAGE, AccountSubtype.HSA, ("hsa", "health savings")),
    (AccountType.BROKERAGE, AccountSubtype.FIVE_TWO_NINE, ("529",)),
    (AccountType.BROKERAGE, AccountSubtype.BROKERAGE, (
        "brokerage", "invest", "robinhood", "schwab", "fidelity", "vanguard",
        "etrade", "e-trade", "merrill", "interactive broker",
    )),
    (AccountType.CRYPTOCURRENCY, AccountSubtype.CRYPTO, (
        "coinbase", "binance", "kraken", "crypto", "btc", "ethereum",
    )),
    (AccountType.DEPOSITORY, AccountSubtype.CHECKING, ("checking", "everyday", "operations")),
    (AccountType.DEPOSITORY, AccountSubtype.SAVINGS, ("savings", "hys", "high-yield", "hysa", "marcus")),
    (AccountType.DEPOSITORY, AccountSubtype.MONEY_MARKET, ("money market",)),
    (AccountType.DEPOSITORY, AccountSubtype.CD, (" cd ", "certificate")),
    (AccountType.REAL_ESTATE, AccountSubtype.REAL_ESTATE, ("zillow", "redfin", "real estate", "property")),
    (AccountType.VEHICLE, AccountSubtype.VEHICLE, ("kelley", "kbb", "vehicle", "car value")),
)


def _classify(name: str) -> tuple[AccountType, AccountSubtype]:
    """Best-effort account-type inference from the friendly name.

    The keyword table above is checked in order; the first hit wins. Since loan /
    credit keywords are more specific than the broader ``checking`` /
    ``savings`` ones, they're listed first so a name like ``"Mortgage Savings"``
    (rare but possible) classifies as loan, not depository.
    """
    lower = f" {name.lower()} "
    for account_type, subtype, keywords in _TYPE_KEYWORDS:
        if any(k in lower for k in keywords):
            return account_type, subtype
    return AccountType.OTHER, AccountSubtype.OTHER


# ---------------------------------------------------------------------------
# Stable id generation
# ---------------------------------------------------------------------------

_ID_PREFIX = "CSV_"


def stable_account_id(friendly_name: str) -> str:
    """Return a deterministic account id derived from ``friendly_name``.

    We hash the trimmed lower-case name so the same account always gets the same
    id across repeated imports, even if the file or timestamp changes. The ``CSV_``
    prefix flags the origin so downstream tools can tell imported accounts from
    live-API ones at a glance.
    """
    canonical = friendly_name.strip().lower()
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{_ID_PREFIX}{digest}"


def stable_transaction_id(
    on_date: date, amount: Decimal, account_id: str, merchant: str, original: str, index: int
) -> str:
    """Deterministic transaction id built from the row's own fields.

    Monarch's export doesn't expose an internal id. We hash date + amount +
    account + merchant + original statement + row index — stable across re-imports
    of the same file, unique across distinct rows even when the other fields
    collide (e.g. twice-in-a-day coffee purchases, differentiated by row index).
    """
    raw = f"{on_date.isoformat()}|{amount}|{account_id}|{merchant}|{original}|{index}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"CSV_T_{digest}"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ImportResult:
    """Summary of a single import run, returned for CLI + logging."""

    accounts_seen: int = 0
    balances_imported: int = 0
    transactions_imported: int = 0
    skipped_rows: int = 0
    date_range: tuple[date | None, date | None] = (None, None)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        start, end = self.date_range
        return {
            "accounts_seen": self.accounts_seen,
            "balances_imported": self.balances_imported,
            "transactions_imported": self.transactions_imported,
            "skipped_rows": self.skipped_rows,
            "date_range": {
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            },
            "errors": self.errors[:10],
        }


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


class MonarchCsvImporter:
    """Idempotent importer for Monarch's CSV exports.

    One instance can be reused for multiple files — :meth:`import_balances` and
    :meth:`import_transactions` each return an independent :class:`ImportResult`
    but both accumulate into the provided :class:`MonarchCache`.

    Args:
        cache: Destination SQLite store. Defaults to the canonical per-user cache
            at ``~/.local/share/monarch-insights/cache.db``.
    """

    def __init__(self, cache: MonarchCache | None = None) -> None:
        self.cache = cache or MonarchCache()

    # ------------------------------------------------------------------ balances

    def import_balances(self, path: Path | str) -> ImportResult:
        """Read a Monarch Balances CSV and persist derived accounts + snapshots.

        Every row also seeds an :class:`Account` row (if not already seen) so that
        transaction-only exports don't need a matching balances file to populate
        the account table.
        """
        path = Path(path)
        result = ImportResult()
        accounts: dict[str, Account] = {}
        snapshots: list[tuple[str, str, float]] = []
        min_date: date | None = None
        max_date: date | None = None

        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            self._require_columns(reader, {"Date", "Balance", "Account"}, path, result)
            for row_idx, row in enumerate(reader, start=2):
                try:
                    name = (row.get("Account") or "").strip()
                    if not name:
                        result.skipped_rows += 1
                        continue
                    on_date = _parse_date(row["Date"])
                    balance = _parse_money(row["Balance"])
                    account_id = stable_account_id(name)
                    if account_id not in accounts:
                        accounts[account_id] = _build_account(account_id, name, balance)
                    else:
                        # Keep the most recent balance as the account's current_balance.
                        if on_date >= (max_date or on_date):
                            accounts[account_id].current_balance = balance
                            accounts[account_id].last_balance_at = datetime.combine(
                                on_date, datetime.min.time(), tzinfo=timezone.utc
                            )
                    snapshots.append((account_id, on_date.isoformat(), float(balance)))
                    min_date = on_date if (min_date is None or on_date < min_date) else min_date
                    max_date = on_date if (max_date is None or on_date > max_date) else max_date
                except Exception as exc:  # noqa: BLE001 — record + continue
                    result.skipped_rows += 1
                    result.errors.append(f"row {row_idx}: {exc}")

        result.accounts_seen = len(accounts)
        result.balances_imported = len(snapshots)
        result.date_range = (min_date, max_date)

        # Persist accounts first so foreign-key-ish lookups have something to point at.
        self.cache.upsert_many("account", [(a.id, a.model_dump()) for a in accounts.values()])
        # Daily balance snapshots go into the cache's dedicated table.
        if snapshots:
            with self.cache.connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO account_balances (account_id, on_date, balance) VALUES (?, ?, ?)",
                    snapshots,
                )
        log.info("ingest.balances.imported", extra={"count": len(snapshots), "path": str(path)})
        return result

    # ------------------------------------------------------------------ transactions

    def import_transactions(self, path: Path | str) -> ImportResult:
        """Read a Monarch Transactions CSV and persist each row as a :class:`Transaction`.

        Accounts that appear in the transaction file but were never seen in a
        balances import get auto-created with ``current_balance=None`` so insights
        can still use them.
        """
        path = Path(path)
        result = ImportResult()
        transactions: list[Transaction] = []
        seen_accounts: dict[str, Account] = {}
        min_date: date | None = None
        max_date: date | None = None

        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            self._require_columns(
                reader,
                {"Date", "Merchant", "Category", "Account", "Amount"},
                path,
                result,
            )
            for row_idx, row in enumerate(reader, start=2):
                try:
                    account_name = (row.get("Account") or "").strip()
                    merchant = (row.get("Merchant") or "").strip()
                    category = (row.get("Category") or "").strip() or None
                    original = (row.get("Original Statement") or "").strip()
                    notes = (row.get("Notes") or "").strip() or None
                    tags = _split_tags(row.get("Tags"))
                    amount = _parse_money(row.get("Amount"))
                    on_date = _parse_date(row["Date"])
                    if not account_name or amount == Decimal(0):
                        result.skipped_rows += 1
                        continue

                    account_id = stable_account_id(account_name)
                    if account_id not in seen_accounts:
                        seen_accounts[account_id] = _build_account(account_id, account_name, None)

                    tx_id = stable_transaction_id(
                        on_date, amount, account_id, merchant, original, row_idx
                    )
                    transactions.append(
                        Transaction.model_validate(
                            {
                                "id": tx_id,
                                "date": on_date.isoformat(),
                                "amount": str(amount),
                                "accountId": account_id,
                                "accountDisplayName": account_name,
                                "categoryId": _stable_category_id(category) if category else None,
                                "categoryName": category,
                                "merchantId": _stable_merchant_id(merchant) if merchant else None,
                                "merchantName": merchant or None,
                                "originalDescription": original or None,
                                "notes": notes,
                                "tagIds": [_stable_tag_id(t) for t in tags],
                                "tagNames": tags,
                                "isRecurring": False,
                            }
                        )
                    )
                    min_date = on_date if (min_date is None or on_date < min_date) else min_date
                    max_date = on_date if (max_date is None or on_date > max_date) else max_date
                except Exception as exc:  # noqa: BLE001 — record + continue
                    result.skipped_rows += 1
                    result.errors.append(f"row {row_idx}: {exc}")

        result.accounts_seen = len(seen_accounts)
        result.transactions_imported = len(transactions)
        result.date_range = (min_date, max_date)

        if seen_accounts:
            # Don't clobber balance data that a prior balances import wrote. Only
            # upsert accounts we've never seen before. Accounts that already exist
            # in the cache keep their richer (balance-populated) row.
            existing_ids = {r.get("id") for r in self.cache.list_entities("account")}
            new_accounts = [
                (a.id, a.model_dump())
                for a in seen_accounts.values()
                if a.id not in existing_ids
            ]
            if new_accounts:
                self.cache.upsert_many("account", new_accounts)
        if transactions:
            self.cache.upsert_transactions([t.model_dump() for t in transactions])
        log.info(
            "ingest.transactions.imported",
            extra={"count": len(transactions), "path": str(path)},
        )
        return result

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _require_columns(
        reader: csv.DictReader, required: set[str], path: Path, result: ImportResult
    ) -> None:
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path.name}: missing required columns {sorted(missing)} — "
                f"got {reader.fieldnames}"
            )


# ---------------------------------------------------------------------------
# Row-level helpers
# ---------------------------------------------------------------------------


_MONEY_RE = re.compile(r"^[\s\$]*(-?)\s*\$?\s*([\d,]+(?:\.\d+)?)\s*$")


def _parse_money(value: Any) -> Decimal:
    """Parse a Monarch money column — handles ``$1,234.56``, ``-1234.56``, ``(1.2)``, etc."""
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return Decimal(0)
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    match = _MONEY_RE.match(text)
    if not match:
        # Best-effort: strip spaces + commas + $ and try again.
        cleaned = text.replace(",", "").replace("$", "").strip()
        return Decimal(cleaned)
    sign, digits = match.groups()
    cleaned = digits.replace(",", "")
    signed = f"-{cleaned}" if sign else cleaned
    return Decimal(signed)


def _parse_date(value: Any) -> date:
    """Parse a Monarch date — always ISO ``YYYY-MM-DD`` in current exports."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    # Explicit ISO first; fall back to US-style if Monarch ever changes format.
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date: {value!r}")


def _split_tags(raw: Any) -> list[str]:
    if not raw:
        return []
    text = str(raw).strip()
    if not text:
        return []
    # Monarch exports tags as comma-separated, sometimes with trailing whitespace.
    parts = [p.strip() for p in re.split(r"[,;]", text)]
    return [p for p in parts if p]


def _build_account(account_id: str, name: str, balance: Decimal | None) -> Account:
    """Construct an :class:`Account` instance from just the friendly name + balance."""
    account_type, subtype = _classify(name)
    payload: dict[str, Any] = {
        "id": account_id,
        "displayName": name,
        "type": account_type.value,
        "subtype": subtype.value,
        "includeInNetWorth": True,
        "isAsset": account_type not in {
            AccountType.CREDIT,
            AccountType.LOAN,
            AccountType.OTHER_LIABILITY,
        },
        "isManual": True,  # CSV-imported accounts behave like manual entries
    }
    if balance is not None:
        payload["currentBalance"] = str(balance)
    return Account.model_validate(payload)


def _stable_category_id(name: str) -> str:
    return f"CSV_CAT_{hashlib.sha256(name.strip().lower().encode()).hexdigest()[:12]}"


def _stable_merchant_id(name: str) -> str:
    return f"CSV_M_{hashlib.sha256(name.strip().lower().encode()).hexdigest()[:12]}"


def _stable_tag_id(name: str) -> str:
    return f"CSV_TAG_{hashlib.sha256(name.strip().lower().encode()).hexdigest()[:10]}"


# ---------------------------------------------------------------------------
# Convenience functions for the CLI
# ---------------------------------------------------------------------------


def import_monarch_csvs(
    transactions: Iterable[Path] = (),
    balances: Iterable[Path] = (),
    cache: MonarchCache | None = None,
) -> dict[str, Any]:
    """Import any combination of Monarch CSV files and return a summary dict.

    This is what the CLI + HA service wrap. Each file is processed independently
    so one bad file doesn't block the others; the caller gets the full picture.
    """
    importer = MonarchCsvImporter(cache=cache)
    results: dict[str, Any] = {"balances": [], "transactions": []}
    for path in balances:
        results["balances"].append({"path": str(path), **importer.import_balances(path).as_dict()})
    for path in transactions:
        results["transactions"].append(
            {"path": str(path), **importer.import_transactions(path).as_dict()}
        )
    return results
