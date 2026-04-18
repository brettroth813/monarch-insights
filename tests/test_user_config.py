"""Coverage for the local user_config loader."""

from __future__ import annotations

import os
import textwrap
from decimal import Decimal

import pytest

from monarch_insights.config import (
    AllocationTarget,
    UserConfig,
    WatchlistEntry,
    load,
)


def _write_yaml(path, body: str) -> None:
    path.write_text(textwrap.dedent(body).strip() + "\n")


def test_load_missing_file_returns_empty_config(tmp_path, monkeypatch):
    # Isolate from any ambient config — point the search at a nonexistent path.
    monkeypatch.setenv("MONARCH_INSIGHTS_CONFIG", str(tmp_path / "does_not_exist.yaml"))
    cfg = load()
    assert isinstance(cfg, UserConfig)
    assert cfg.is_configured is False
    assert cfg.accounts == {}
    assert cfg.watchlist == []


def test_load_parses_full_example(tmp_path):
    path = tmp_path / "monarch_insights.yaml"
    _write_yaml(
        path,
        """
        filing_status: mfj
        primary_checking_account_id: ACT_demo_checking
        accounts:
          ACT_demo_checking:
            display_name: Demo Checking
            institution: Demo Bank
            is_primary_checking: true
          ACT_demo_brokerage:
            display_name: Demo Brokerage
            institution: Demo Broker
            is_primary_brokerage: true
        allocation_targets:
          us_stock:   {target_pct: 60, drift_threshold_pct: 5}
          intl_stock: {target_pct: 25, drift_threshold_pct: 3}
          bond:       {target_pct: 15}
        watchlist:
          - {symbol: vti, kind: buy_below, target_price: 240.50}
          - {symbol: NVDA, kind: alert_move, move_threshold_pct: 5}
        alerts:
          low_balance_floor: 1800
          concentration_threshold_pct: 15
          notify_service: notify.mobile_app_phone
        """,
    )
    cfg = load(path)
    assert cfg.is_configured
    assert cfg.filing_status == "mfj"
    assert cfg.primary_checking_account_id == "ACT_demo_checking"
    assert cfg.accounts["ACT_demo_checking"].display_name == "Demo Checking"
    assert cfg.accounts["ACT_demo_checking"].is_primary_checking is True
    assert cfg.accounts["ACT_demo_brokerage"].is_primary_brokerage is True

    assert cfg.allocation_targets["us_stock"] == AllocationTarget(Decimal("60"), Decimal("5"))
    assert cfg.allocation_targets["intl_stock"].drift_threshold_pct == Decimal("3")
    # Missing drift_threshold_pct defaults to 5.
    assert cfg.allocation_targets["bond"].drift_threshold_pct == Decimal("5")

    # Symbol gets upper-cased; decimal values preserve precision.
    assert cfg.watchlist[0] == WatchlistEntry(
        symbol="VTI", kind="buy_below", target_price=Decimal("240.50")
    )
    assert cfg.watchlist[1].move_threshold_pct == Decimal("5")

    assert cfg.alerts.low_balance_floor == Decimal("1800")
    assert cfg.alerts.concentration_threshold_pct == Decimal("15")
    assert cfg.alerts.notify_service == "notify.mobile_app_phone"


def test_env_override_takes_precedence(tmp_path, monkeypatch):
    path = tmp_path / "explicit.yaml"
    _write_yaml(path, "filing_status: single\n")
    monkeypatch.setenv("MONARCH_INSIGHTS_CONFIG", str(path))
    cfg = load()
    assert cfg.filing_status == "single"
    assert cfg.source_path == path


def test_explicit_path_beats_env(tmp_path, monkeypatch):
    env_path = tmp_path / "env.yaml"
    explicit_path = tmp_path / "explicit.yaml"
    _write_yaml(env_path, "filing_status: mfj\n")
    _write_yaml(explicit_path, "filing_status: single\n")
    monkeypatch.setenv("MONARCH_INSIGHTS_CONFIG", str(env_path))
    cfg = load(explicit_path)
    assert cfg.filing_status == "single"


def test_invalid_top_level_raises(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("- this is a list not a mapping\n")
    with pytest.raises(ValueError, match="YAML mapping"):
        load(path)


def test_watchlist_entries_without_symbol_are_skipped(tmp_path):
    path = tmp_path / "wl.yaml"
    _write_yaml(
        path,
        """
        watchlist:
          - {kind: alert_move}
          - {symbol: VOO, kind: alert_move}
        """,
    )
    cfg = load(path)
    assert len(cfg.watchlist) == 1
    assert cfg.watchlist[0].symbol == "VOO"


def test_account_display_name_fallback(tmp_path):
    path = tmp_path / "alias.yaml"
    _write_yaml(
        path,
        """
        accounts:
          ACT_one:
            display_name: One
        """,
    )
    cfg = load(path)
    assert cfg.account_display_name("ACT_one") == "One"
    assert cfg.account_display_name("ACT_missing") == "ACT_missing"
    assert cfg.account_display_name("ACT_missing", fallback="Fallback") == "Fallback"
