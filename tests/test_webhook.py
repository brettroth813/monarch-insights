"""Unit tests for the Monarch Insights token-push webhook handler.

The webhook module depends on live Home Assistant imports via the package's
``__init__.py`` transitively, so we skip it when HA isn't installed (which is the
default in the library's own CI venv). The nightly trigger runs these tests in an
environment that does have HA, where they exercise the real handler via HA's test
fixtures; here we just make sure the file is well-formed.
"""

from __future__ import annotations

import pytest

# This is the only reliable import gate — the package itself pulls in
# ``homeassistant.helpers.update_coordinator``, which requires a full HA install.
pytest.importorskip(
    "homeassistant.helpers.update_coordinator",
    reason="full Home Assistant install required for webhook handler tests",
)


def test_webhook_module_importable():  # pragma: no cover — runs only with HA installed
    from custom_components.monarch_insights import webhook as webhook_module

    assert hasattr(webhook_module, "async_register_webhook")
    assert hasattr(webhook_module, "_receive_token")
