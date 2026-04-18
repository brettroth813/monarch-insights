"""Shared base configuration for Monarch Insights pydantic models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MonarchModel(BaseModel):
    """Base for every model.

    Monarch returns mixed-case GraphQL keys (e.g. ``displayName``) that we want to expose
    in snake_case. Aliases are populated automatically and forbidden-extra is off so the
    schema can drift without breaking us.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        frozen=False,
        ser_json_timedelta="iso8601",
        str_strip_whitespace=True,
    )


def money(value: Any | None) -> Decimal | None:
    """Coerce a Monarch monetary field to Decimal without losing precision."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def parse_date(value: Any | None) -> date | None:
    """Best-effort coercion of strings/datetimes into ``date`` objects."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Cannot coerce {value!r} to date")


def parse_datetime(value: Any | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Cannot coerce {value!r} to datetime")


__all__ = ["MonarchModel", "money", "parse_date", "parse_datetime", "Field"]
