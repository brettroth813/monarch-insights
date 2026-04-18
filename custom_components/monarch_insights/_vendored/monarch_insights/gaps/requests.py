"""Structured "additional information wanted" records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class RequestKind(str, Enum):
    COST_BASIS = "cost_basis"
    PAYSTUB = "paystub"
    RSU_GRANT = "rsu_grant"
    ACCOUNT_HISTORY = "account_history"
    TAX_DOCUMENT = "tax_doc"
    INCOME_SOURCE = "income_source"
    ALLOCATION_TARGET = "allocation_target"
    GOAL_DETAIL = "goal_detail"
    CATEGORIZATION = "categorization"
    RECURRING_REVIEW = "recurring_review"
    OTHER = "other"


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class InfoRequest:
    id: str
    kind: RequestKind
    summary: str
    severity: Severity = Severity.INFO
    suggested_action: str | None = None
    related_account_id: str | None = None
    related_ticker: str | None = None
    detail: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def new(cls, kind: RequestKind | str, summary: str, **kwargs) -> InfoRequest:
        return cls(
            id=str(uuid.uuid4()),
            kind=RequestKind(kind) if isinstance(kind, str) else kind,
            summary=summary,
            **kwargs,
        )

    def to_storage_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "summary": self.summary,
            "severity": self.severity.value,
            "suggested_action": self.suggested_action,
            "related_account_id": self.related_account_id,
            "related_ticker": self.related_ticker,
            "detail": self.detail,
            "created_at": int(self.created_at.timestamp()),
        }
