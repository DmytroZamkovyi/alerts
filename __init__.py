"""Alerts: air raid and other alerts in Ukraine from alerts.in.ua."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AlertsApi
from .const import CONF_TOKEN
from .coordinator import AlertsCoordinator
from .locations import directory

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.EVENT]

type AlertsConfigEntry = ConfigEntry[AlertsCoordinator]

USER_AGENT = "HomeAssistant-alerts-integration"


async def async_setup_entry(hass: HomeAssistant, entry: AlertsConfigEntry) -> bool:
    """Set up from a config entry."""
    locations = await hass.async_add_executor_job(directory)
    api = AlertsApi(async_get_clientsession(hass), entry.data[CONF_TOKEN], USER_AGENT)
    coordinator = AlertsCoordinator(hass, entry, api, locations)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start_history()
    entry.async_on_unload(coordinator.async_shutdown_extra)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: AlertsConfigEntry) -> None:
    """Reload on options or region changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AlertsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
