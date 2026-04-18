"""Tests for the Monarch CSV importer.

Covers the real export schema (``Balances.csv`` with ``Date,Balance,Account`` and
``Transactions.csv`` with ``Date,Merchant,Category,Account,Original Statement,
Notes,Amount,Tags,Owner``), plus edge cases around money parsing, account-type
inference, idempotent re-import, and schema-mismatch detection.
"""

from __future__ import annotations

import textwrap
from decimal import Decimal
from pathlib import Path

import pytest

from monarch_insights.ingest.csv_monarch import (
    MonarchCsvImporter,
    _classify,
    _parse_money,
    stable_account_id,
    stable_transaction_id,
)
from monarch_insights.models import AccountSubtype, AccountType
from monarch_insights.storage.cache import MonarchCache


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected_type, expected_subtype",
    [
        ("Chase Checking (...1234)", AccountType.DEPOSITORY, AccountSubtype.CHECKING),
        ("Marcus HYS", AccountType.DEPOSITORY, AccountSubtype.SAVINGS),
        ("Robinhood Roth IRA (...8507)", AccountType.BROKERAGE, AccountSubtype.ROTH_IRA),
        ("Fidelity 401k", AccountType.BROKERAGE, AccountSubtype.TRADITIONAL_401K),
        ("American Express Gold Card (...3008)", AccountType.CREDIT, AccountSubtype.CREDIT_CARD),
        ("Bilt Palladium Card (...6678)", AccountType.CREDIT, AccountSubtype.CREDIT_CARD),
        ("Mortgage (...5432)", AccountType.LOAN, AccountSubtype.MORTGAGE),
        ("Auto Loan", AccountType.LOAN, AccountSubtype.AUTO_LOAN),
        ("Coinbase BTC", AccountType.CRYPTOCURRENCY, AccountSubtype.CRYPTO),
        ("Unclassifiable Blob", AccountType.OTHER, AccountSubtype.OTHER),
    ],
)
def test_classify(name, expected_type, expected_subtype):
    t, s = _classify(name)
    assert t == expected_type
    assert s == expected_subtype


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("-36.05", Decimal("-36.05")),
        ("$1,234.56", Decimal("1234.56")),
        ("(500.00)", Decimal("-500.00")),
        ("0.00", Decimal("0.00")),
        ("", Decimal("0")),
        (None, Decimal("0")),
        ("  -$1,000  ", Decimal("-1000")),
    ],
)
def test_parse_money(raw, expected):
    assert _parse_money(raw) == expected


def test_stable_ids_are_deterministic():
    # Same name → same id, across calls.
    assert stable_account_id("Chase Checking") == stable_account_id("Chase Checking")
    # Case / whitespace invariant.
    assert stable_account_id("  chase checking  ") == stable_account_id("Chase Checking")
    # Different names yield different ids.
    assert stable_account_id("Chase Checking") != stable_account_id("Chase Savings")


def test_stable_transaction_id_changes_with_index():
    from datetime import date as D

    kwargs = dict(
        on_date=D(2026, 4, 18),
        amount=Decimal("-10"),
        account_id="CSV_ABC",
        merchant="Coffee",
        original="COFFEE PLACE",
    )
    a = stable_transaction_id(**kwargs, index=2)
    b = stable_transaction_id(**kwargs, index=3)
    assert a != b


# ---------------------------------------------------------------------------
# Full-file import
# ---------------------------------------------------------------------------


BALANCES_CSV = textwrap.dedent(
    """\
    Date,Balance,Account
    2025-10-15,200377.69,Robinhood Roth IRA (...8507)
    2025-10-15,4200.00,Primary Checking (...1300)
    2025-10-15,-1968.80,American Express Gold Card (...3008)
    2025-10-16,4150.25,Primary Checking (...1300)
    2025-10-16,-2010.00,American Express Gold Card (...3008)
    """
)

TRANSACTIONS_CSV = textwrap.dedent(
    """\
    Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags,Owner
    2026-04-18,Hair Salon & Barbershops,Personal,Bilt Palladium Card (...6678),Sundays Barber Shop,,-36.05,,Brett Roth
    2026-04-17,Trader Joe's,Groceries,Robinhood Credit Card (...7027),Trader Joe's,personal,-97.96,groceries;weekly,Brett Roth
    2026-04-16,Shell,Gas,Bilt Palladium Card (...6678),Shell,,-31.13,,Brett Roth
    2026-04-10,Payroll,Income,Primary Checking (...1300),ACME EMPLOYER PAYROLL,,4250.00,,Brett Roth
    """
)


@pytest.fixture
def importer(tmp_path):
    cache = MonarchCache(path=tmp_path / "cache.db")
    return MonarchCsvImporter(cache=cache)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


def test_import_balances_populates_accounts_and_snapshots(tmp_path, importer):
    path = _write(tmp_path, "Balances.csv", BALANCES_CSV)
    result = importer.import_balances(path)
    assert result.accounts_seen == 3
    assert result.balances_imported == 5
    assert result.skipped_rows == 0

    accounts = {a["display_name"]: a for a in importer.cache.list_entities("account")}
    # Type inference holds up against real names.
    assert accounts["Robinhood Roth IRA (...8507)"]["type"] == "brokerage"
    assert accounts["American Express Gold Card (...3008)"]["type"] == "credit"
    assert accounts["Primary Checking (...1300)"]["type"] == "depository"
    # Most-recent balance wins for current_balance.
    assert Decimal(str(accounts["Primary Checking (...1300)"]["current_balance"])) == Decimal("4150.25")


def test_import_transactions_captures_full_fields(tmp_path, importer):
    path = _write(tmp_path, "Transactions.csv", TRANSACTIONS_CSV)
    result = importer.import_transactions(path)
    assert result.transactions_imported == 4
    assert result.accounts_seen == 3  # Bilt, Robinhood CC, Checking
    # Spot-check that tag splitting + notes survive.
    with importer.cache.connect() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM transactions ORDER BY on_date DESC"
        ).fetchall()
    import json

    payloads = [json.loads(r["payload_json"]) for r in rows]
    notes = next(p for p in payloads if p.get("notes") == "personal")
    assert notes["tag_names"] == ["groceries", "weekly"]


def test_import_is_idempotent(tmp_path, importer):
    path = _write(tmp_path, "Transactions.csv", TRANSACTIONS_CSV)
    first = importer.import_transactions(path)
    second = importer.import_transactions(path)
    with importer.cache.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
    assert first.transactions_imported == second.transactions_imported == count


def test_import_flags_missing_columns(tmp_path, importer):
    path = _write(tmp_path, "bad.csv", "Foo,Bar\n1,2\n")
    with pytest.raises(ValueError, match="missing required columns"):
        importer.import_transactions(path)


def test_zero_amount_rows_skipped(tmp_path, importer):
    body = textwrap.dedent(
        """\
        Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags,Owner
        2026-04-10,Adjustment,Other,Primary Checking (...1300),ADJ,,,,Brett
        2026-04-11,Real,Food,Primary Checking (...1300),REAL,,-5.00,,Brett
        """
    )
    path = _write(tmp_path, "Transactions.csv", body)
    result = importer.import_transactions(path)
    assert result.transactions_imported == 1
    assert result.skipped_rows == 1
