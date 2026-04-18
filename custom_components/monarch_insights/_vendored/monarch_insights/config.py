"""User-config loader — reads a local YAML file with the operator's real-world mappings.

The library is deliberately agnostic of any specific user. Institution names, account
aliases, filing status, allocation targets, watchlist symbols, etc. live outside the
repo in a file the operator keeps on their own machine. This keeps the codebase:

* Shareable — generic fixtures + clean test data, no personal banking footprint committed.
* Reusable — anyone can deploy it by dropping their own ``monarch_insights.yaml`` in place.
* Private — your Pi never ships your institution list to GitHub.

Search order for the config file (first match wins):

1. ``MONARCH_INSIGHTS_CONFIG`` environment variable (explicit override).
2. ``/config/monarch_insights.yaml`` — Home Assistant OS config dir.
3. ``~/.config/monarch-insights/user.yaml`` — standard XDG config path for CLI use.
4. ``./monarch_insights.yaml`` — local dev / repo root.

Missing file is not an error — ``load()`` returns an empty :class:`UserConfig`. Modules
that need a value (e.g. primary checking account ID for balance forecasting) should ask
for it explicitly and surface a helpful error when it's not configured.

Example ``monarch_insights.yaml``:

.. code-block:: yaml

    filing_status: single
    primary_checking_account_id: ACT_...

    accounts:
      ACT_...:
        display_name: Chase Checking
        institution: Chase
      ACT_...:
        display_name: Schwab Brokerage
        institution: Charles Schwab
        is_primary_brokerage: true

    allocation_targets:
      us_stock:   {target_pct: 60, drift_threshold_pct: 5}
      intl_stock: {target_pct: 25, drift_threshold_pct: 5}
      bond:       {target_pct: 15, drift_threshold_pct: 5}

    watchlist:
      - symbol: NVDA
        kind: alert_move
        move_threshold_pct: 5
      - symbol: VTI
        kind: buy_below
        target_price: 240

    alerts:
      low_balance_floor: 1500
      concentration_threshold_pct: 15
      notify_service: notify.mobile_app_your_phone
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from monarch_insights.observability import get_logger

log = get_logger(__name__)


DEFAULT_SEARCH_PATHS: tuple[Path, ...] = (
    Path("/config/monarch_insights.yaml"),
    Path.home() / ".config" / "monarch-insights" / "user.yaml",
    Path.cwd() / "monarch_insights.yaml",
)


@dataclass
class AccountAlias:
    """Human-readable alias for a Monarch account id the user cares about.

    Lets docs + notifications say "Chase Checking" while the library internally uses
    the Monarch account UUID.
    """

    display_name: str
    institution: str | None = None
    is_primary_checking: bool = False
    is_primary_brokerage: bool = False
    notes: str | None = None


@dataclass
class WatchlistEntry:
    """One symbol the user wants signals / alerts on."""

    symbol: str
    kind: str = "alert_move"  # buy_below | sell_above | alert_move
    target_price: Decimal | None = None
    move_threshold_pct: Decimal | None = None
    notes: str | None = None


@dataclass
class AllocationTarget:
    """Target % + drift tolerance for a single asset bucket."""

    target_pct: Decimal
    drift_threshold_pct: Decimal = Decimal("5")


@dataclass
class AlertSettings:
    """Knobs for the alert engine."""

    low_balance_floor: Decimal | None = None
    concentration_threshold_pct: Decimal = Decimal("10")
    price_move_threshold_pct: Decimal = Decimal("5")
    notify_service: str | None = None  # e.g. ``notify.mobile_app_phone``


@dataclass
class UserConfig:
    """Aggregate of every operator-specific setting the library cares about."""

    filing_status: str | None = None  # single | mfj | mfs | hoh
    primary_checking_account_id: str | None = None
    accounts: dict[str, AccountAlias] = field(default_factory=dict)
    allocation_targets: dict[str, AllocationTarget] = field(default_factory=dict)
    watchlist: list[WatchlistEntry] = field(default_factory=list)
    alerts: AlertSettings = field(default_factory=AlertSettings)
    raw: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    @property
    def is_configured(self) -> bool:
        """``True`` when we found and parsed a config file (vs falling back to defaults)."""
        return self.source_path is not None

    def account_display_name(self, account_id: str, fallback: str | None = None) -> str:
        """Resolve a Monarch account id to the user's preferred label."""
        alias = self.accounts.get(account_id)
        if alias:
            return alias.display_name
        return fallback or account_id


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _resolve_path(explicit: Path | str | None) -> Path | None:
    """Find the config file. Explicit arg wins, then env var, then search paths."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("MONARCH_INSIGHTS_CONFIG")
    if env:
        return Path(env)
    for candidate in DEFAULT_SEARCH_PATHS:
        if candidate.is_file():
            return candidate
    return None


def _dec(value: Any) -> Decimal | None:
    """Lenient Decimal coercion — YAML may give us int/float/str/None."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _parse(raw: dict[str, Any], source: Path) -> UserConfig:
    cfg = UserConfig(source_path=source, raw=raw)
    cfg.filing_status = raw.get("filing_status")
    cfg.primary_checking_account_id = raw.get("primary_checking_account_id")

    for account_id, alias_data in (raw.get("accounts") or {}).items():
        alias_data = alias_data or {}
        cfg.accounts[account_id] = AccountAlias(
            display_name=alias_data.get("display_name") or account_id,
            institution=alias_data.get("institution"),
            is_primary_checking=bool(alias_data.get("is_primary_checking")),
            is_primary_brokerage=bool(alias_data.get("is_primary_brokerage")),
            notes=alias_data.get("notes"),
        )

    for bucket, t_data in (raw.get("allocation_targets") or {}).items():
        t_data = t_data or {}
        tp = _dec(t_data.get("target_pct"))
        if tp is None:
            continue
        cfg.allocation_targets[bucket] = AllocationTarget(
            target_pct=tp,
            drift_threshold_pct=_dec(t_data.get("drift_threshold_pct")) or Decimal("5"),
        )

    for wl_entry in raw.get("watchlist") or []:
        if not isinstance(wl_entry, dict) or not wl_entry.get("symbol"):
            continue
        cfg.watchlist.append(
            WatchlistEntry(
                symbol=str(wl_entry["symbol"]).upper(),
                kind=wl_entry.get("kind", "alert_move"),
                target_price=_dec(wl_entry.get("target_price")),
                move_threshold_pct=_dec(wl_entry.get("move_threshold_pct")),
                notes=wl_entry.get("notes"),
            )
        )

    alerts_raw = raw.get("alerts") or {}
    cfg.alerts = AlertSettings(
        low_balance_floor=_dec(alerts_raw.get("low_balance_floor")),
        concentration_threshold_pct=_dec(alerts_raw.get("concentration_threshold_pct")) or Decimal("10"),
        price_move_threshold_pct=_dec(alerts_raw.get("price_move_threshold_pct")) or Decimal("5"),
        notify_service=alerts_raw.get("notify_service"),
    )

    return cfg


def load(path: Path | str | None = None) -> UserConfig:
    """Load the user config YAML if present; return an empty :class:`UserConfig` if not.

    Args:
        path: Optional explicit path. When omitted we search
            :data:`DEFAULT_SEARCH_PATHS` and the ``MONARCH_INSIGHTS_CONFIG`` env var.

    Returns:
        Parsed :class:`UserConfig`. A missing file yields an empty config with
        ``is_configured == False``.
    """
    resolved = _resolve_path(path)
    if resolved is None or not resolved.is_file():
        log.info("config.load.no_file")
        return UserConfig()

    try:
        import yaml  # lazy import — callers that don't load config don't need pyyaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pyyaml is required to load monarch_insights.yaml. "
            "Install via `pip install pyyaml`."
        ) from exc

    with resolved.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{resolved} must contain a YAML mapping at the top level")

    log.info(
        "config.load.parsed",
        extra={
            "source": str(resolved),
            "accounts": len(raw.get("accounts") or {}),
            "watchlist": len(raw.get("watchlist") or []),
            "buckets": len(raw.get("allocation_targets") or {}),
        },
    )
    return _parse(raw, resolved)
