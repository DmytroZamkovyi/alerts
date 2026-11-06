"""Config flow: token, options and region subentries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import AlertsApi, AlertsApiError, AlertsAuthError, AlertsForbiddenError
from .const import (
    ALERT_AIR_RAID,
    ALERT_TYPES,
    CONF_HISTORY_INTERVAL,
    CONF_OBLAST,
    CONF_SCAN_INTERVAL,
    CONF_STAT_TYPES,
    CONF_TOKEN,
    CONF_UID,
    DEFAULT_HISTORY_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_HISTORY_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_HISTORY_INTERVAL,
    MIN_SCAN_INTERVAL,
    SUBENTRY_REGION,
)
from .locations import Directory, directory

CONF_NAME = "name"
USER_AGENT = "HomeAssistant-alerts-integration"

TYPE_ORDER = {"raion": 0, "city": 1, "hromada": 2}


async def _validate_token(hass, token: str) -> str | None:
    """Return an error key or None."""
    api = AlertsApi(async_get_clientsession(hass), token, USER_AGENT)
    try:
        await api.active()
    except AlertsAuthError:
        return "invalid_auth"
    except AlertsForbiddenError:
        return "forbidden"
    except AlertsApiError:
        return "cannot_connect"
    return None


def _token_schema(default: str = "") -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_TOKEN, default=default): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            )
        }
    )


class AlertsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Main flow: API token."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the token."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            error = await _validate_token(self.hass, token)
            if error is None:
                return self.async_create_entry(
                    title="Тривоги (alerts.in.ua)", data={CONF_TOKEN: token}
                )
            errors["base"] = error
        return self.async_show_form(step_id="user", data_schema=_token_schema(), errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Token rejected: ask for a new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter a new token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            error = await _validate_token(self.hass, token)
            if error is None:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_TOKEN: token}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=_token_schema(), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            error = await _validate_token(self.hass, token)
            if error is None:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data_updates={CONF_TOKEN: token}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure", data_schema=_token_schema(), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options: polling intervals."""
        return AlertsOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Regions are subentries."""
        return {SUBENTRY_REGION: RegionSubentryFlow}


class AlertsOptionsFlow(OptionsFlow):
    """Polling intervals."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_HISTORY_INTERVAL: int(user_input[CONF_HISTORY_INTERVAL]),
                }
            )
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_HISTORY_INTERVAL,
                    default=opts.get(CONF_HISTORY_INTERVAL, DEFAULT_HISTORY_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_HISTORY_INTERVAL,
                        max=MAX_HISTORY_INTERVAL,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


def _stat_types_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=ALERT_TYPES,
            multiple=True,
            mode=SelectSelectorMode.LIST,
            translation_key="alert_type",
        )
    )


class RegionSubentryFlow(ConfigSubentryFlow):
    """Add or change a tracked region."""

    def __init__(self) -> None:
        self._dir: Directory | None = None
        self._oblast: int | None = None

    async def _directory(self) -> Directory:
        if self._dir is None:
            self._dir = await self.hass.async_add_executor_job(directory)
        return self._dir

    def _configured_uids(self, skip: str | None = None) -> set[int]:
        return {
            int(sub.data[CONF_UID])
            for sid, sub in self._get_entry().subentries.items()
            if sub.subentry_type == SUBENTRY_REGION and sid != skip and CONF_UID in sub.data
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Step 1: oblast."""
        d = await self._directory()
        if user_input is not None:
            self._oblast = int(user_input[CONF_OBLAST])
            return await self.async_step_location()
        options = [SelectOptionDict(value=str(loc.uid), label=loc.name) for loc in d.tops()]
        schema = vol.Schema(
            {
                vol.Required(CONF_OBLAST): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2: the exact location inside the oblast and statistics settings."""
        d = await self._directory()
        assert self._oblast is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            uid = int(user_input.get(CONF_UID, self._oblast))
            loc = d.get(uid)
            types = user_input.get(CONF_STAT_TYPES) or [ALERT_AIR_RAID]
            if loc is None:
                errors["base"] = "unknown_location"
            elif uid in self._configured_uids():
                return self.async_abort(reason="already_configured")
            else:
                title = (user_input.get(CONF_NAME) or "").strip() or loc.name
                return self.async_create_entry(
                    title=title,
                    data={CONF_UID: uid, CONF_STAT_TYPES: types},
                    unique_id=str(uid),
                )

        oblast = d.get(self._oblast)
        assert oblast is not None
        fields: dict[Any, Any] = {}
        children = sorted(
            d.children(oblast.uid),
            key=lambda loc: (TYPE_ORDER.get(loc.type, 9), d.label(loc)),
        )
        if children:
            options = [SelectOptionDict(value=str(oblast.uid), label=f"{oblast.name} (уся)")]
            options += [SelectOptionDict(value=str(loc.uid), label=d.label(loc)) for loc in children]
            fields[vol.Required(CONF_UID, default=str(oblast.uid))] = SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN, sort=False)
            )
        fields[vol.Optional(CONF_NAME)] = TextSelector()
        fields[vol.Required(CONF_STAT_TYPES, default=[ALERT_AIR_RAID])] = _stat_types_selector()
        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={"oblast": oblast.name},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change name and statistics types of a region."""
        sub = self._get_reconfigure_subentry()
        if user_input is not None:
            title = (user_input.get(CONF_NAME) or "").strip() or sub.title
            return self.async_update_and_abort(
                self._get_entry(),
                sub,
                title=title,
                data={
                    **sub.data,
                    CONF_STAT_TYPES: user_input.get(CONF_STAT_TYPES) or [ALERT_AIR_RAID],
                },
            )
        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=sub.title): TextSelector(),
                vol.Required(
                    CONF_STAT_TYPES,
                    default=sub.data.get(CONF_STAT_TYPES, [ALERT_AIR_RAID]),
                ): _stat_types_selector(),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)
