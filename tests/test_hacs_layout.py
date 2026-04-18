"""Structural tests that guard the HACS integration's on-disk layout.

These don't exercise HA itself — they just verify the invariants HACS + Home Assistant
enforce at install time, so regressions surface in CI instead of at the user's first
install attempt.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HA_ROOT = REPO / "custom_components" / "monarch_insights"
VENDORED = HA_ROOT / "_vendored" / "monarch_insights"
CANONICAL = REPO / "monarch_insights"


# ---------------------------------------------------------------------------
# manifest.json + hacs.json invariants
# ---------------------------------------------------------------------------


def test_hacs_json_present_and_valid():
    hacs = REPO / "hacs.json"
    assert hacs.exists(), "hacs.json is required at the repo root for HACS install"
    payload = json.loads(hacs.read_text())
    assert payload.get("name"), "hacs.json must include a human-readable name"
    # HACS uses ``content_in_root: false`` when the integration lives under
    # custom_components/, which is the default layout we use.
    assert payload.get("content_in_root") is False


def test_manifest_json_fields():
    manifest = HA_ROOT / "manifest.json"
    assert manifest.exists(), "custom_components/monarch_insights/manifest.json missing"
    payload = json.loads(manifest.read_text())
    for key in (
        "domain",
        "name",
        "version",
        "config_flow",
        "documentation",
        "issue_tracker",
        "iot_class",
        "integration_type",
        "codeowners",
        "requirements",
    ):
        assert key in payload, f"manifest.json missing required field: {key}"
    assert payload["domain"] == "monarch_insights"
    # Documentation URL should not still be the placeholder.
    assert "your-handle" not in payload["documentation"], (
        "manifest.documentation is still a placeholder — update to the real repo URL"
    )


def test_ha_entry_points_parse():
    """Every Python file the HA integration ships should parse cleanly."""
    for py in HA_ROOT.rglob("*.py"):
        source = py.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover — triggered only on real breakage
            pytest.fail(f"{py.relative_to(REPO)} failed to parse: {exc}")


# ---------------------------------------------------------------------------
# Vendored library must stay in sync with the canonical package
# ---------------------------------------------------------------------------


def _hash_tree(root: Path) -> dict[str, str]:
    """Return {relative_path: sha256} for every .py under ``root``."""
    out: dict[str, str] = {}
    for py in root.rglob("*.py"):
        # Skip byte-compiled artefacts and hidden files.
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(root).as_posix()
        out[rel] = hashlib.sha256(py.read_bytes()).hexdigest()
    return out


def test_vendored_tree_matches_canonical():
    """HACS ships the vendored copy; any drift means the integration uses stale code.

    Run ``python scripts/sync_vendored.py`` and re-commit if this fails.
    """
    canonical = _hash_tree(CANONICAL)
    vendored = _hash_tree(VENDORED)

    missing_in_vendored = sorted(set(canonical) - set(vendored))
    missing_in_canonical = sorted(set(vendored) - set(canonical))
    drifted = sorted(
        path
        for path in canonical.keys() & vendored.keys()
        if canonical[path] != vendored[path]
    )

    assert not missing_in_vendored, (
        f"vendored copy missing {len(missing_in_vendored)} files — "
        f"run `python scripts/sync_vendored.py`. First few: {missing_in_vendored[:5]}"
    )
    assert not missing_in_canonical, (
        "vendored has orphan files the canonical doesn't: "
        f"{missing_in_canonical[:5]}"
    )
    assert not drifted, (
        f"vendored copy has {len(drifted)} drifted files — "
        f"run `python scripts/sync_vendored.py`. First few: {drifted[:5]}"
    )


def test_integration_shim_bootstraps_sys_path():
    """The HA ``__init__.py`` must prepend _vendored to sys.path before importing."""
    init_text = (HA_ROOT / "__init__.py").read_text()
    assert "_vendored" in init_text, "HA __init__.py must reference _vendored"
    assert "sys.path.insert" in init_text, (
        "HA __init__.py must insert _vendored onto sys.path before any library import"
    )
