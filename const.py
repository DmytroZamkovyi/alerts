"""Constants for the Alerts (alerts.in.ua) integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "alerts"

API_BASE = "https://api.alerts.in.ua"
ACTIVE_ENDPOINT = "/v1/alerts/active.json"
HISTORY_ENDPOINT = "/v1/regions/{uid}/alerts/month_ago.json"

CONF_TOKEN = "token"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_HISTORY_INTERVAL = "history_interval"

# Region subentry
SUBENTRY_REGION = "region"
CONF_UID = "uid"
CONF_OBLAST = "oblast"
CONF_STAT_TYPES = "stat_types"

DEFAULT_SCAN_INTERVAL = 30  # seconds; the API soft limit is 8-10 requests/min
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 300
DEFAULT_HISTORY_INTERVAL = 30  # minutes
MIN_HISTORY_INTERVAL = 10
MAX_HISTORY_INTERVAL = 180

# The history endpoint allows 2 requests per minute.
HISTORY_MIN_GAP = timedelta(seconds=35)
REQUEST_TIMEOUT = 15
RATE_LIMIT_BACKOFF = timedelta(minutes=2)

# alert_type values of the API
ALERT_AIR_RAID = "air_raid"
ALERT_TYPES = [
    "air_raid",
    "artillery_shelling",
    "urban_fights",
    "chemical",
    "nuclear",
]

# threat_type values of the API
THREAT_TYPES = [
    "tactic_aircraft_activity",
    "strategic_aircraft_activity",
    "mig31k_departure",
    "ballistic_missiles",
    "cruise_missiles",
    "unspecified_missiles",
    "drones",
    "guided_aerial_bombs",
    "air_defense",
    "unknown",
]

THREAT_TITLES_UK = {
    "tactic_aircraft_activity": "Активність тактичної авіації",
    "strategic_aircraft_activity": "Активність стратегічної авіації",
    "mig31k_departure": "Зліт МіГ-31К",
    "ballistic_missiles": "Балістичні ракети",
    "cruise_missiles": "Крилаті ракети",
    "unspecified_missiles": "Ракети",
    "drones": "Ударні БпЛА",
    "guided_aerial_bombs": "КАБи",
    "air_defense": "Робота ППО",
    "unknown": "Невідома загроза",
}

ALERT_TITLES_UK = {
    "air_raid": "Повітряна тривога",
    "artillery_shelling": "Загроза артобстрілу",
    "urban_fights": "Вуличні бої",
    "chemical": "Хімічна загроза",
    "nuclear": "Радіаційна загроза",
}

# Region status
STATUS_NONE = "none"
STATUS_PARTIAL = "partial"
STATUS_ACTIVE = "active"
STATUSES = [STATUS_NONE, STATUS_PARTIAL, STATUS_ACTIVE]

LEVEL_NONE = "none"
LEVELS = [LEVEL_NONE, "red", "yellow"]

# Event entity / bus event
EVENT_BUS = "alerts_event"
EV_STARTED = "alert_started"
EV_ENDED = "alert_ended"
EV_UPDATED = "alert_updated"
EV_PARTIAL_STARTED = "partial_started"
EV_PARTIAL_ENDED = "partial_ended"
EVENT_TYPES = [EV_STARTED, EV_ENDED, EV_UPDATED, EV_PARTIAL_STARTED, EV_PARTIAL_ENDED]

STAT_PERIODS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

ATTRIBUTION = "Дані: alerts.in.ua"
