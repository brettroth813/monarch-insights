"""Reusable fixture builders so the demo + downstream tests share the same canned dataset.

All institution + account names here are deliberately generic placeholders. Real user
account mappings belong in the user's local ``monarch_insights.yaml`` config file, which
is loaded by :mod:`monarch_insights.config` at runtime — not checked into git.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from monarch_insights.models import (
    Account,
    Budget,
    BudgetItem,
    Goal,
    Holding,
    RecurringStream,
    Transaction,
)


def build_accounts() -> list[Account]:
    """Return a representative 10-account mix: depository, brokerage, credit, loan."""
    return [
        Account.model_validate(
            {
                "id": "ACT_checking_primary",
                "displayName": "Primary Checking",
                "type": "depository",
                "subtype": "checking",
                "currentBalance": "8423.10",
                "isAsset": True,
                "includeInNetWorth": True,
                "institution": {"id": "INST_bank_a", "name": "Bank A"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_savings_hys",
                "displayName": "High-Yield Savings",
                "type": "depository",
                "subtype": "savings",
                "currentBalance": "47120.00",
                "isAsset": True,
                "includeInNetWorth": True,
                "institution": {"id": "INST_bank_b", "name": "Bank B"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_brokerage_primary",
                "displayName": "Primary Brokerage",
                "type": "brokerage",
                "subtype": "brokerage",
                "currentBalance": "184320.00",
                "isAsset": True,
                "includeInNetWorth": True,
                "institution": {"id": "INST_broker_a", "name": "Broker A"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_brokerage_self",
                "displayName": "Self-Directed Brokerage",
                "type": "brokerage",
                "subtype": "brokerage",
                "currentBalance": "21560.00",
                "isAsset": True,
                "includeInNetWorth": True,
                "institution": {"id": "INST_broker_b", "name": "Broker B"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_card_rewards_a",
                "displayName": "Rewards Card A",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "1245.30",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_issuer_a", "name": "Issuer A"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_card_travel",
                "displayName": "Travel Card",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "835.00",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_bank_a", "name": "Bank A"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_card_cashback",
                "displayName": "Cashback Card",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "112.45",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_issuer_b", "name": "Issuer B"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_card_airline",
                "displayName": "Airline Card",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "0",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_issuer_c", "name": "Issuer C"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_card_rent",
                "displayName": "Rent Rewards Card",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "1985.00",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_issuer_d", "name": "Issuer D"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_loan_auto",
                "displayName": "Auto Loan",
                "type": "loan",
                "subtype": "auto_loan",
                "currentBalance": "12450.00",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_lender_auto", "name": "Auto Lender"},
            }
        ),
    ]


def build_holdings() -> list[Holding]:
    """Holdings spread across the two brokerage accounts; one deliberately missing cost basis."""
    return [
        Holding.model_validate(
            {"id": "H_VTI", "accountId": "ACT_brokerage_primary", "ticker": "VTI",
             "quantity": 480, "costBasis": 95000, "value": 124000, "marketValue": 124000}
        ),
        Holding.model_validate(
            {"id": "H_VXUS", "accountId": "ACT_brokerage_primary", "ticker": "VXUS",
             "quantity": 320, "costBasis": 18000, "value": 19200, "marketValue": 19200}
        ),
        Holding.model_validate(
            {"id": "H_BND", "accountId": "ACT_brokerage_primary", "ticker": "BND",
             "quantity": 250, "costBasis": 19500, "value": 18800, "marketValue": 18800}
        ),
        Holding.model_validate(
            {"id": "H_VOO_RH", "accountId": "ACT_brokerage_self", "ticker": "VOO",
             "quantity": 25, "costBasis": 11000, "value": 14200, "marketValue": 14200}
        ),
        Holding.model_validate(
            # Deliberately missing cost basis — exercises the gap detector.
            {"id": "H_NVDA_RH", "accountId": "ACT_brokerage_self", "ticker": "NVDA",
             "quantity": 12, "value": 7360, "marketValue": 7360}
        ),
        Holding.model_validate(
            {"id": "H_AAPL_SCH", "accountId": "ACT_brokerage_primary", "ticker": "AAPL",
             "quantity": 100, "costBasis": 17800, "value": 22320, "marketValue": 22320}
        ),
    ]


def build_transactions(days: int = 365) -> list[Transaction]:
    """Synthesize ~12 months of transactions across payroll, rent, subscriptions, spend."""
    rng = random.Random(42)
    today = date.today()
    txs: list[Transaction] = []
    counter = 0

    def _add(d, amount, account, category, merchant, recurring=False, tags=None):
        nonlocal counter
        counter += 1
        txs.append(
            Transaction.model_validate(
                {
                    "id": f"T{counter:05d}",
                    "date": d.isoformat(),
                    "amount": amount,
                    "accountId": account,
                    "categoryId": category[0],
                    "categoryName": category[1],
                    "merchantId": f"M_{merchant.lower().replace(' ', '_')}",
                    "merchantName": merchant,
                    "tags": tags or [],
                    "isRecurring": recurring,
                }
            )
        )

    # Biweekly payroll.
    pay_day = today
    while pay_day > today - timedelta(days=days):
        _add(pay_day, 4250.00, "ACT_checking_primary", ("CAT_payroll", "Paycheck"), "Employer Payroll", recurring=True)
        pay_day -= timedelta(days=14)

    # Monthly rent paid via rewards card.
    rent_day = today.replace(day=1)
    while rent_day > today - timedelta(days=days):
        _add(rent_day, -2200, "ACT_card_rent", ("CAT_housing", "Rent"), "Rent Payment", recurring=True)
        rent_day = (rent_day - timedelta(days=1)).replace(day=1)

    # Streaming subs — one creeps up in price to exercise the creep detector.
    sub_day = today
    streaming_price = 15.99
    while sub_day > today - timedelta(days=days):
        _add(sub_day, -streaming_price, "ACT_card_travel", ("CAT_streaming", "Streaming"), "Streaming Service A", recurring=True)
        streaming_price = min(streaming_price + 0.50, 22.99)
        _add(sub_day, -10.99, "ACT_card_travel", ("CAT_streaming", "Streaming"), "Streaming Service B", recurring=True)
        _add(sub_day, -2.99, "ACT_card_travel", ("CAT_storage", "Cloud Storage"), "Cloud Storage", recurring=True)
        sub_day -= timedelta(days=30)

    # Duplicate streaming sub on another card — exercises the duplicate detector.
    _add(today - timedelta(days=10), -15.99, "ACT_card_rewards_a", ("CAT_streaming", "Streaming"), "STREAMING SERVICE A", recurring=True)

    # Variable daily spending across categories.
    cats = [
        ("CAT_groceries", "Groceries", "Grocery Store", -120, 30),
        ("CAT_dining", "Dining", "Fast Casual", -18, 15),
        ("CAT_dining", "Dining", "Local Diner", -42, 25),
        ("CAT_transport", "Transportation", "Ride Share", -22, 20),
        ("CAT_shopping", "Shopping", "Online Retailer", -68, 40),
    ]
    for d in (today - timedelta(days=i) for i in range(days)):
        for cat_id, cat_name, merchant, mean, sigma in cats:
            if rng.random() < 0.7:
                amt = round(rng.gauss(mean, sigma), 2)
                if amt < 0:
                    _add(d, amt, "ACT_card_rewards_a", (cat_id, cat_name), merchant)

    # One large outlier so anomaly detection has something to surface.
    _add(today - timedelta(days=8), -1850.00, "ACT_card_travel", ("CAT_dining", "Dining"), "Local Diner")

    # Monthly mortgage interest for Schedule A deduction candidate. Month-stepper
    # walks to the first of the current month, back one day, then snaps to the 15th.
    int_day = today.replace(day=15)
    cutoff = today - timedelta(days=days)
    while int_day > cutoff:
        _add(int_day, -1240.00, "ACT_checking_primary", ("CAT_housing", "Mortgage Interest"), "Mortgage Interest Payment")
        prior_month_end = int_day.replace(day=1) - timedelta(days=1)
        int_day = prior_month_end.replace(day=15)

    # Two charitable contributions across the year.
    _add(today - timedelta(days=45), -250, "ACT_card_rewards_a", ("CAT_charity", "Charity"), "Charity Donation")
    _add(today - timedelta(days=160), -500, "ACT_card_rewards_a", ("CAT_charity", "Charity"), "Charity Donation")

    return txs


def build_recurring() -> list[RecurringStream]:
    today = date.today()
    return [
        RecurringStream.model_validate(
            {"id": "stream_payroll", "name": "Employer Payroll", "frequency": "biweekly",
             "averageAmount": 4250.00, "nextDate": (today + timedelta(days=7)).isoformat(), "isActive": True, "isIncome": True,
             "accountId": "ACT_checking_primary", "accountName": "Primary Checking"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_rent", "name": "Rent", "frequency": "monthly",
             "averageAmount": -2200, "nextDate": (today + timedelta(days=10)).isoformat(), "isActive": True,
             "accountId": "ACT_card_rent", "accountName": "Rent Rewards Card"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_streaming_a1", "name": "Streaming Service A", "frequency": "monthly",
             "averageAmount": -22.99, "nextDate": (today + timedelta(days=14)).isoformat(), "isActive": True,
             "accountId": "ACT_card_travel"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_streaming_a2", "name": "STREAMING SERVICE A", "frequency": "monthly",
             "averageAmount": -15.99, "nextDate": (today + timedelta(days=21)).isoformat(), "isActive": True,
             "accountId": "ACT_card_rewards_a"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_streaming_b", "name": "Streaming Service B", "frequency": "monthly",
             "averageAmount": -10.99, "nextDate": (today + timedelta(days=18)).isoformat(), "isActive": True,
             "accountId": "ACT_card_travel"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_auto_loan", "name": "Auto Loan", "frequency": "monthly",
             "averageAmount": -385, "nextDate": (today + timedelta(days=8)).isoformat(), "isActive": True,
             "accountId": "ACT_checking_primary"}
        ),
    ]


def build_budgets() -> list[Budget]:
    today = date.today()
    period = today.replace(day=1)
    return [
        Budget.model_validate(
            {
                "startDate": period.isoformat(),
                "endDate": period.isoformat(),
                "totalPlannedIncome": 8500,
                "totalPlannedExpense": 6500,
                "totalActualIncome": 8500,
                "totalActualExpense": 5800,
                "items": [
                    {"id": "bi_groceries", "categoryId": "CAT_groceries", "categoryName": "Groceries",
                     "plannedCashFlowAmount": 600, "actualAmount": 720},
                    {"id": "bi_dining", "categoryId": "CAT_dining", "categoryName": "Dining",
                     "plannedCashFlowAmount": 400, "actualAmount": 590},
                    {"id": "bi_streaming", "categoryId": "CAT_streaming", "categoryName": "Streaming",
                     "plannedCashFlowAmount": 50, "actualAmount": 28},
                    {"id": "bi_transport", "categoryId": "CAT_transport", "categoryName": "Transportation",
                     "plannedCashFlowAmount": 150, "actualAmount": 135},
                ],
            }
        )
    ]


def build_goals() -> list[Goal]:
    today = date.today()
    return [
        Goal.model_validate(
            {
                "id": "goal_emergency",
                "name": "Emergency fund",
                "targetAmount": 30000,
                "currentAmount": 24000,
                "monthlyContribution": 500,
                "targetDate": (today + timedelta(days=240)).isoformat(),
                "isCompleted": False,
            }
        ),
        Goal.model_validate(
            {
                "id": "goal_house",
                "name": "House down payment",
                "targetAmount": 100000,
                "currentAmount": 35000,
                "monthlyContribution": 1500,
                "targetDate": (today + timedelta(days=900)).isoformat(),
                "isCompleted": False,
            }
        ),
    ]
