"""Home Assistant integration for Monarch Insights.

HACS copies this package (``custom_components/monarch_insights``) into
``/config/custom_components/`` at install time. The insight library is vendored under
``_vendored/monarch_insights/`` so a single copy gets shipped and imports like
``from monarch_insights.client.api import MonarchClient`` resolve without requiring the
package on PyPI.

The sys.path insertion at module load is the *only* place we mutate global state; it
happens exactly once per process and is a no-op on subsequent calls.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Bootstrap: make the vendored library importable before anything else in this package
# tries to ``from monarch_insights...`` import it. Runs at most once per Python process.
_VENDORED = Path(__file__).resolve().parent / "_vendored"
if _VENDORED.is_dir() and str(_VENDORED) not in sys.path:
    sys.path.insert(0, str(_VENDORED))

from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

from .const import DOMAIN, PLATFORMS  # noqa: E402
from .coordinator import MonarchInsightsCoordinator  # noqa: E402

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure a single Monarch Insights instance.

    Creates the coordinator, runs the first refresh, forwards to the sensor platform,
    and registers the ``monarch_insights.refresh`` service. Any error during the first
    refresh is propagated so Home Assistant marks the entry ``setup_retry`` rather than
    silently loading a broken integration.
    """
    coordinator = MonarchInsightsCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _refresh(call):
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "refresh", _refresh)
    _LOGGER.info("monarch_insights setup complete for entry %s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a previously set-up entry and clear its coordinator from ``hass.data``."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
