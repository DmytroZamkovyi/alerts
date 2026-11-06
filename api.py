"""Small async client for api.alerts.in.ua."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import ACTIVE_ENDPOINT, API_BASE, HISTORY_ENDPOINT, REQUEST_TIMEOUT


class AlertsApiError(Exception):
    """Generic API failure."""


class AlertsAuthError(AlertsApiError):
    """Token rejected (401)."""


class AlertsForbiddenError(AlertsApiError):
    """Access forbidden (403): token disabled or request from a blocked region."""


class AlertsRateLimitError(AlertsApiError):
    """Too many requests (429)."""


class AlertsApi:
    """Client with If-Modified-Since caching per endpoint."""

    def __init__(self, session: aiohttp.ClientSession, token: str, user_agent: str) -> None:
        self._session = session
        self._token = token
        self._ua = user_agent
        self._cache: dict[str, tuple[str, Any]] = {}

    async def _get(self, path: str) -> Any:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": self._ua,
        }
        cached = self._cache.get(path)
        if cached:
            headers["If-Modified-Since"] = cached[0]
        try:
            async with self._session.get(
                API_BASE + path,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 304 and cached:
                    return cached[1]
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    last_mod = resp.headers.get("Last-Modified")
                    if last_mod:
                        self._cache[path] = (last_mod, data)
                    return data
                text = (await resp.text())[:200]
                if resp.status == 401:
                    raise AlertsAuthError(f"401 Unauthorized: {text}")
                if resp.status == 403:
                    raise AlertsForbiddenError(f"403 Forbidden: {text}")
                if resp.status == 429:
                    raise AlertsRateLimitError("429 Too many requests")
                raise AlertsApiError(f"HTTP {resp.status}: {text}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise AlertsApiError(f"Connection error: {err!r}") from err

    async def active(self) -> dict[str, Any]:
        """Currently active alerts in the whole country."""
        data = await self._get(ACTIVE_ENDPOINT)
        if not isinstance(data, dict) or not isinstance(data.get("alerts"), list):
            raise AlertsApiError("Unexpected response of active alerts")
        return data

    async def history(self, oblast_uid: int) -> list[dict[str, Any]]:
        """Alerts of an oblast (with its raions and hromadas) for the last month."""
        data = await self._get(HISTORY_ENDPOINT.format(uid=oblast_uid))
        if not isinstance(data, dict) or not isinstance(data.get("alerts"), list):
            raise AlertsApiError("Unexpected response of alerts history")
        return data["alerts"]
