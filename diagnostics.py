"""Diagnostics download."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import AlertsConfigEntry
from .const import CONF_TOKEN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AlertsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics (token redacted)."""
    c = entry.runtime_data
    diag = c.diag
    regions = {}
    for sid, region in c.regions.items():
        data = c.data.get(sid) if c.data else None
        regions[region.title] = {
            "uid": region.location.uid,
            "type": region.location.type,
            "oblast": region.location.oblast,
            "raion": region.location.raion,
            "stat_types": region.stat_types,
            "status": data.state.status if data else None,
            "types": data.state.types if data else None,
            "history_loaded": data.history_loaded if data else None,
        }
    return {
        "entry": async_redact_data(dict(entry.data), {CONF_TOKEN}),
        "options": dict(entry.options),
        "last_active_ok": diag.last_active_ok.isoformat() if diag.last_active_ok else None,
        "last_active_error": diag.last_active_error,
        "active_alerts_in_country": diag.active_count,
        "history": diag.last_history,
        "history_errors": diag.history_errors,
        "stored_alerts": len(c.store),
        "regions": regions,
    }
