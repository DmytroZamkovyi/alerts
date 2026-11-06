# Alerts UA — air raid alerts in Home Assistant

[Українською](README.uk.md)

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DmytroZamkovyi&repository=alerts&category=integration)

Air raid and other alerts in Ukraine from [alerts.in.ua](https://alerts.in.ua): alert state, level and threats, durations, statistics and events for automations. Track several regions, each at any level: oblast, raion, city or hromada.

> Data is provided by alerts.in.ua without guarantees. Do not use this integration as your only danger warning: official sirens and apps come first.

## Installation

1. HACS → three dots → "Custom repositories" → URL of this repository, category "Integration".
2. Install "Alerts UA", restart Home Assistant.
3. Settings → Devices & services → "Add integration" → "Alerts UA".
4. Enter an alerts.in.ua API token. Tokens are free and issued on request via the form on alerts.in.ua (developers section).
5. On the integration page press "Add region": choose an oblast, then a region inside it (whole oblast, raion, city or hromada), optionally a name and the alert types for statistics.

## How a region's alert is determined

- An alert **covers** a region when it is declared for the region itself or for something that contains it: an oblast alert turns on all its raions and hromadas, a raion alert turns on its hromadas. A city and its namesake hromada are treated as one region.
- When an alert is only in part of the region (e.g. one hromada of the oblast), the region status is "partial" and the alert binary sensors stay off.

## Entities (one device per region)

Entity ids are stable: `<domain>.alerts_<uid>_<key>`, where `uid` is the alerts.in.ua location code (e.g. `31` for Kyiv).

| Entity | Meaning |
|---|---|
| `binary_sensor.alerts_<uid>_air_raid` | Air raid alert. Attributes: `level` (`red`/`yellow`), `threats`, `threat_titles`, `threat_details`, `started_at`, `status`, `covering_locations`, `partial_locations`, `notes` |
| `binary_sensor.alerts_<uid>_artillery_shelling`, `_urban_fights`, `_chemical`, `_nuclear` | Other alert types, attribute `started_at` |
| `sensor.alerts_<uid>_status` | `none` / `partial` / `active` (any type) |
| `sensor.alerts_<uid>_level` | Air raid level: `none` / `red` / `yellow` |
| `sensor.alerts_<uid>_threats` | Number of threats; attributes `threats`, `titles`, `text`, `details` |
| `sensor.alerts_<uid>_alert_start` | Start of the current alert |
| `sensor.alerts_<uid>_state_duration` | How long the current state (alert or calm) lasts, minutes |
| `sensor.alerts_<uid>_last_end` | Last all clear |
| `sensor.alerts_<uid>_last_duration` | Duration of the last finished alert, minutes |
| `sensor.alerts_<uid>_count_24h`, `_7d`, `_30d` | Number of alerts in the last 24 hours / 7 / 30 days (rolling) |
| `sensor.alerts_<uid>_duration_24h`, `_7d`, `_30d` | Total alert time in the period (shown in hours); attribute `longest_min` |
| `sensor.alerts_<uid>_history_updated` | Diagnostic, disabled by default |
| `event.alerts_<uid>_events` | Region events, see below |

Start, duration and statistics sensors count only the alert types chosen for the region (air raid by default). Overlapping alerts are merged.

## Events

Entity `event.alerts_<uid>_events` and bus event `alerts_event` (with `event_type`): `alert_started`, `alert_ended` (`ended_at`, `duration_min`), `alert_updated` (level or threats changed: `previous_level`, `added_threats`, `removed_threats`), `partial_started`, `partial_ended`. Common fields: `region`, `uid`, `alert_type`, `status`, `level`, `threats`, `threat_titles`, `partial_locations`, `started_at`, `at`.

## Options

- **Polling interval** (default 30 s, minimum 15 s): one request for all regions. API limit is 8–10 requests per minute.
- **History refresh interval** (default 30 min): month history for statistics, one request per oblast (limit 2 per minute, requests are spaced).
- A region can be renamed and its statistics types changed (three dots next to the region → "Reconfigure").
- If the token stops working, Home Assistant asks for a new one.

A single failed poll does not make entities unavailable; they become unavailable after 10 minutes without data.

## Location directory

Location codes and hierarchy (hromada → raion → oblast) are in `locations.json`, taken from the public alerts.in.ua location list.

## License

MIT.
