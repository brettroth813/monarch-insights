"""Document references — links to PDFs/images stored locally, in Drive, or as Gmail msgs."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class DocType(str, Enum):
    DIV_1099 = "1099-DIV"
    INT_1099 = "1099-INT"
    B_1099 = "1099-B"
    NEC_1099 = "1099-NEC"
    MISC_1099 = "1099-MISC"
    W2 = "W-2"
    K1 = "K-1"
    BROKERAGE_STATEMENT = "brokerage_statement"
    BANK_STATEMENT = "bank_statement"
    CREDIT_CARD_STATEMENT = "credit_card_statement"
    PAYSTUB = "paystub"
    RECEIPT = "receipt"
    CLOSING_DOCUMENT = "closing_document"
    INVOICE = "invoice"
    OTHER = "other"

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        return cls.OTHER


class StorageKind(str, Enum):
    LOCAL = "local"
    DRIVE = "drive"
    GMAIL = "gmail"
    URL = "url"


@dataclass
class Document:
    id: str
    title: str
    doc_type: DocType
    storage_kind: StorageKind
    storage_ref: str
    tax_year: int | None = None
    institution: str | None = None
    sha256: str | None = None
    notes: str | None = None
    metadata: dict = field(default_factory=dict)
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_local_path(
        cls,
        path: Path,
        doc_type: DocType | str,
        title: str | None = None,
        tax_year: int | None = None,
        institution: str | None = None,
    ) -> Document:
        path = Path(path)
        return cls(
            id=str(uuid.uuid4()),
            title=title or path.name,
            doc_type=DocType(doc_type) if isinstance(doc_type, str) else doc_type,
            storage_kind=StorageKind.LOCAL,
            storage_ref=str(path.resolve()),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
            tax_year=tax_year,
            institution=institution,
        )

    @classmethod
    def from_drive_id(cls, drive_id: str, **kwargs) -> Document:
        return cls(
            id=str(uuid.uuid4()),
            storage_kind=StorageKind.DRIVE,
            storage_ref=drive_id,
            **kwargs,
        )

    @classmethod
    def from_gmail_message(cls, msg_id: str, **kwargs) -> Document:
        return cls(
            id=str(uuid.uuid4()),
            storage_kind=StorageKind.GMAIL,
            storage_ref=msg_id,
            **kwargs,
        )

    def to_storage_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "doc_type": self.doc_type.value,
            "storage_kind": self.storage_kind.value,
            "storage_ref": self.storage_ref,
            "tax_year": self.tax_year,
            "institution": self.institution,
            "sha256": self.sha256,
            "notes": self.notes,
            "metadata": self.metadata,
            "added_at": int(self.added_at.timestamp()),
        }
