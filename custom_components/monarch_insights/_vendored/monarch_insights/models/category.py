"""Transaction categories, category groups, and tags."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field

from monarch_insights.models._base import MonarchModel


class CategoryGroupType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    OTHER = "other"

    @classmethod
    def _missing_(cls, value):  # type: ignore[override]
        return cls.OTHER


class CategoryGroup(MonarchModel):
    id: str
    name: str
    type: CategoryGroupType = CategoryGroupType.EXPENSE
    color: Optional[str] = None
    order: Optional[int] = None
    is_system: bool = Field(default=False, alias="isSystemGroup")


class Category(MonarchModel):
    id: str
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    order: Optional[int] = None
    group_id: Optional[str] = Field(default=None, alias="groupId")
    group_name: Optional[str] = Field(default=None, alias="groupName")
    group_type: CategoryGroupType = Field(
        default=CategoryGroupType.EXPENSE, alias="groupType"
    )
    is_system: bool = Field(default=False, alias="isSystemCategory")
    is_disabled: bool = Field(default=False, alias="isDisabled")
    rollover_period: Optional[str] = Field(default=None, alias="rolloverPeriod")


class Tag(MonarchModel):
    id: str
    name: str
    color: Optional[str] = None
    order: Optional[int] = None
    transaction_count: Optional[int] = Field(default=None, alias="transactionCount")
