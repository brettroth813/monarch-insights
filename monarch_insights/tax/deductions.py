"""Deduction-finder: scans transactions for Schedule A / above-the-line candidates."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from monarch_insights.models import Transaction


@dataclass
class DeductionCandidate:
    bucket: str  # mortgage_interest | property_tax | state_income_tax | charitable | medical | hsa | sep_ira | student_loan_interest | child_care | other
    label: str
    amount: Decimal
    transaction_ids: list[str]


_DEDUCTION_RULES: list[tuple[str, list[str], str]] = [
    ("mortgage_interest", ["mortgage interest", "interest paid"], "Mortgage interest"),
    ("property_tax", ["property tax", "prop tax", "real estate tax"], "Property tax"),
    ("state_income_tax", ["state withholding", "state tax"], "State income tax"),
    ("charitable", ["donation", "charity", "givewell", "kiva", "donorbox"], "Charitable contribution"),
    ("medical", ["pharmacy", "rx", "hospital", "clinic", "medical center", "lab corp"], "Medical/dental"),
    ("hsa", ["hsa contribution", "hsa transfer"], "HSA contribution"),
    ("sep_ira", ["sep contribution", "solo 401k"], "Self-employed retirement"),
    ("student_loan_interest", ["student loan interest", "sallie mae interest"], "Student loan interest"),
    ("child_care", ["daycare", "preschool", "child care"], "Child / dependent care"),
]


class DeductionFinder:
    def scan(self, transactions: Iterable[Transaction], year: int | None = None) -> list[DeductionCandidate]:
        buckets: dict[str, DeductionCandidate] = {}
        for t in transactions:
            if year and t.on_date.year != year:
                continue
            if not t.is_outflow or t.is_hidden_from_reports:
                continue
            name = (t.merchant_name or t.original_description or "").lower()
            for bucket, keywords, label in _DEDUCTION_RULES:
                if any(k in name for k in keywords):
                    if bucket not in buckets:
                        buckets[bucket] = DeductionCandidate(
                            bucket=bucket, label=label, amount=Decimal(0), transaction_ids=[]
                        )
                    buckets[bucket].amount += abs(t.amount)
                    buckets[bucket].transaction_ids.append(t.id)
                    break
        return list(buckets.values())
