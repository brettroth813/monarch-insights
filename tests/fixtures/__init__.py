"""Reusable fixture builders so demo + tests share the same canned dataset."""

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
    return [
        Account.model_validate(
            {
                "id": "ACT_chase_checking",
                "displayName": "Chase Checking",
                "type": "depository",
                "subtype": "checking",
                "currentBalance": "8423.10",
                "isAsset": True,
                "includeInNetWorth": True,
                "institution": {"id": "INST_chase", "name": "Chase"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_marcus_savings",
                "displayName": "Marcus HYS",
                "type": "depository",
                "subtype": "savings",
                "currentBalance": "47120.00",
                "isAsset": True,
                "includeInNetWorth": True,
                "institution": {"id": "INST_marcus", "name": "Marcus"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_schwab_brokerage",
                "displayName": "Schwab Brokerage",
                "type": "brokerage",
                "subtype": "brokerage",
                "currentBalance": "184320.00",
                "isAsset": True,
                "includeInNetWorth": True,
                "institution": {"id": "INST_schwab", "name": "Charles Schwab"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_robinhood",
                "displayName": "Robinhood",
                "type": "brokerage",
                "subtype": "brokerage",
                "currentBalance": "21560.00",
                "isAsset": True,
                "includeInNetWorth": True,
                "institution": {"id": "INST_rh", "name": "Robinhood"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_amex_gold",
                "displayName": "Amex Gold",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "1245.30",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_amex", "name": "American Express"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_chase_sapphire",
                "displayName": "Chase Sapphire Reserve",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "835.00",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_chase", "name": "Chase"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_citi_double",
                "displayName": "Citi Double Cash",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "112.45",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_citi", "name": "Citi"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_barclays_aa",
                "displayName": "Barclays AAdvantage",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "0",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_barclays", "name": "Barclays"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_bilt",
                "displayName": "Bilt Mastercard",
                "type": "credit",
                "subtype": "credit_card",
                "currentBalance": "1985.00",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_bilt", "name": "Bilt"},
            }
        ),
        Account.model_validate(
            {
                "id": "ACT_toyota_loan",
                "displayName": "Toyota Auto Loan",
                "type": "loan",
                "subtype": "auto_loan",
                "currentBalance": "12450.00",
                "isAsset": False,
                "includeInNetWorth": True,
                "institution": {"id": "INST_toyota", "name": "Toyota Financial Services"},
            }
        ),
    ]


def build_holdings() -> list[Holding]:
    return [
        Holding.model_validate(
            {"id": "H_VTI", "accountId": "ACT_schwab_brokerage", "ticker": "VTI",
             "quantity": 480, "costBasis": 95000, "value": 124000, "marketValue": 124000}
        ),
        Holding.model_validate(
            {"id": "H_VXUS", "accountId": "ACT_schwab_brokerage", "ticker": "VXUS",
             "quantity": 320, "costBasis": 18000, "value": 19200, "marketValue": 19200}
        ),
        Holding.model_validate(
            {"id": "H_BND", "accountId": "ACT_schwab_brokerage", "ticker": "BND",
             "quantity": 250, "costBasis": 19500, "value": 18800, "marketValue": 18800}
        ),
        Holding.model_validate(
            {"id": "H_VOO_RH", "accountId": "ACT_robinhood", "ticker": "VOO",
             "quantity": 25, "costBasis": 11000, "value": 14200, "marketValue": 14200}
        ),
        Holding.model_validate(
            {"id": "H_NVDA_RH", "accountId": "ACT_robinhood", "ticker": "NVDA",
             "quantity": 12, "value": 7360, "marketValue": 7360}  # cost basis missing on purpose
        ),
        Holding.model_validate(
            {"id": "H_AAPL_SCH", "accountId": "ACT_schwab_brokerage", "ticker": "AAPL",
             "quantity": 100, "costBasis": 17800, "value": 22320, "marketValue": 22320}
        ),
    ]


def build_transactions(days: int = 365) -> list[Transaction]:
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

    # Recurring paycheck biweekly
    pay_day = today
    while pay_day > today - timedelta(days=days):
        _add(pay_day, 4250.00, "ACT_chase_checking", ("CAT_payroll", "Paycheck"), "Acme Co Payroll", recurring=True)
        pay_day -= timedelta(days=14)

    # Rent monthly
    rent_day = today.replace(day=1)
    while rent_day > today - timedelta(days=days):
        _add(rent_day, -2200, "ACT_bilt", ("CAT_housing", "Rent"), "Bilt Rent Payment", recurring=True)
        rent_day = (rent_day - timedelta(days=1)).replace(day=1)

    # Subscriptions — Netflix gradually creeps up to demonstrate price-creep alert
    sub_day = today
    netflix_price = 15.99
    while sub_day > today - timedelta(days=days):
        _add(sub_day, -netflix_price, "ACT_chase_sapphire", ("CAT_streaming", "Streaming"), "Netflix", recurring=True)
        netflix_price = min(netflix_price + 0.50, 22.99)
        _add(sub_day, -10.99, "ACT_chase_sapphire", ("CAT_streaming", "Streaming"), "Spotify", recurring=True)
        _add(sub_day, -2.99, "ACT_chase_sapphire", ("CAT_storage", "Cloud Storage"), "iCloud", recurring=True)
        sub_day -= timedelta(days=30)

    # Duplicate streaming for duplicate-detector test
    _add(today - timedelta(days=10), -15.99, "ACT_amex_gold", ("CAT_streaming", "Streaming"), "NETFLIX", recurring=True)

    # Variable spending
    cats = [
        ("CAT_groceries", "Groceries", "Whole Foods", -120, 30),
        ("CAT_dining", "Dining", "Chipotle", -18, 15),
        ("CAT_dining", "Dining", "Local Diner", -42, 25),
        ("CAT_transport", "Transportation", "Uber", -22, 20),
        ("CAT_shopping", "Shopping", "Amazon", -68, 40),
    ]
    for d in (today - timedelta(days=i) for i in range(days)):
        for cat_id, cat_name, merchant, mean, sigma in cats:
            if rng.random() < 0.7:
                amt = round(rng.gauss(mean, sigma), 2)
                if amt < 0:
                    _add(d, amt, "ACT_amex_gold", (cat_id, cat_name), merchant)

    # One huge anomaly to surface in detector
    _add(today - timedelta(days=8), -1850.00, "ACT_chase_sapphire", ("CAT_dining", "Dining"), "Local Diner")

    # Mortgage interest deduction candidate. We step back month-by-month by going to the
    # first of the current month, subtracting one day to land on the previous month, then
    # snapping to the 15th. Avoids the day-rolls-around bug that hits .replace(day=15)
    # when you only subtract a single day.
    int_day = today.replace(day=15)
    cutoff = today - timedelta(days=days)
    while int_day > cutoff:
        _add(int_day, -1240.00, "ACT_chase_checking", ("CAT_housing", "Mortgage Interest"), "Chase Mortgage Interest")
        prior_month_end = int_day.replace(day=1) - timedelta(days=1)
        int_day = prior_month_end.replace(day=15)

    # Charitable contributions
    _add(today - timedelta(days=45), -250, "ACT_amex_gold", ("CAT_charity", "Charity"), "Donation Box")
    _add(today - timedelta(days=160), -500, "ACT_amex_gold", ("CAT_charity", "Charity"), "Charity Donation")

    return txs


def build_recurring() -> list[RecurringStream]:
    today = date.today()
    return [
        RecurringStream.model_validate(
            {"id": "stream_payroll", "name": "Acme Co Payroll", "frequency": "biweekly",
             "averageAmount": 4250.00, "nextDate": (today + timedelta(days=7)).isoformat(), "isActive": True, "isIncome": True,
             "accountId": "ACT_chase_checking", "accountName": "Chase Checking"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_rent", "name": "Rent", "frequency": "monthly",
             "averageAmount": -2200, "nextDate": (today + timedelta(days=10)).isoformat(), "isActive": True,
             "accountId": "ACT_bilt", "accountName": "Bilt"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_netflix1", "name": "Netflix", "frequency": "monthly",
             "averageAmount": -22.99, "nextDate": (today + timedelta(days=14)).isoformat(), "isActive": True,
             "accountId": "ACT_chase_sapphire"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_netflix2", "name": "NETFLIX", "frequency": "monthly",
             "averageAmount": -15.99, "nextDate": (today + timedelta(days=21)).isoformat(), "isActive": True,
             "accountId": "ACT_amex_gold"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_spotify", "name": "Spotify", "frequency": "monthly",
             "averageAmount": -10.99, "nextDate": (today + timedelta(days=18)).isoformat(), "isActive": True,
             "accountId": "ACT_chase_sapphire"}
        ),
        RecurringStream.model_validate(
            {"id": "stream_toyota", "name": "Toyota Auto Loan", "frequency": "monthly",
             "averageAmount": -385, "nextDate": (today + timedelta(days=8)).isoformat(), "isActive": True,
             "accountId": "ACT_chase_checking"}
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
