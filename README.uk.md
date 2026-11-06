# Alerts UA — тривоги в Home Assistant

[English](README.md)

[![Відкрити в HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DmytroZamkovyi&repository=alerts&category=integration)

Інтеграція показує повітряні та інші тривоги в Україні за даними [alerts.in.ua](https://alerts.in.ua): стан тривоги, рівень і загрози, тривалість, статистику й події для автоматизацій. Регіонів може бути кілька, кожен будь-якого рівня: область, район, місто або громада.

> Дані надає alerts.in.ua без гарантій. Не використовуйте інтеграцію як єдине джерело попередження про небезпеку: офіційні сирени й застосунки важливіші.

## Встановлення

1. HACS → три крапки → «Custom repositories» → адреса цього репозиторію, категорія «Integration».
2. Встановити «Alerts UA», перезапустити Home Assistant.
3. Налаштування → Пристрої та служби → «Додати інтеграцію» → «Alerts UA».
4. Ввести токен API alerts.in.ua. Токен безкоштовний, його видають за запитом через форму на сайті alerts.in.ua (розділ для розробників).
5. На сторінці інтеграції натиснути «Додати регіон»: обрати область, потім регіон у ній (уся область, район, місто чи громада), за бажання назву й типи тривог для статистики.

## Як рахується тривога регіону

- Тривога **покриває** регіон, якщо вона оголошена на самому регіоні або на тому, що його містить: тривога в області вмикає тривогу всіх її районів і громад, тривога в районі вмикає тривогу громад району. Місто й однойменна громада («м. Харків» і «м. Харків та Харківська територіальна громада») вважаються одним регіоном.
- Якщо тривога лише в частині регіону (наприклад, в одній громаді області), стан регіону «Часткова», а бінарні сенсори тривоги вимкнені.

## Сутності (на кожен регіон окремий пристрій)

Ідентифікатори сталі й англійські: `<домен>.alerts_<uid>_<ключ>`, де `uid` це код регіону alerts.in.ua (наприклад, `31` для Києва).

| Сутність | Що показує |
|---|---|
| `binary_sensor.alerts_<uid>_air_raid` | Повітряна тривога. Атрибути: `level` (`red`/`yellow`), `threats`, `threat_titles`, `threat_details`, `started_at`, `status`, `covering_locations`, `partial_locations`, `notes` |
| `binary_sensor.alerts_<uid>_artillery_shelling`, `_urban_fights`, `_chemical`, `_nuclear` | Інші типи тривог, атрибут `started_at` |
| `sensor.alerts_<uid>_status` | `none` / `partial` / `active` (будь-який тип). Атрибути: `active_types`, `active_titles`, `covering_locations`, `partial_locations` |
| `sensor.alerts_<uid>_level` | Рівень повітряної тривоги: `none` / `red` / `yellow` |
| `sensor.alerts_<uid>_threats` | Кількість загроз. Атрибути: `threats` (коди), `titles`, `text` (рядок через кому), `details` |
| `sensor.alerts_<uid>_alert_start` | Початок поточної тривоги (порожньо без тривоги) |
| `sensor.alerts_<uid>_state_duration` | Скільки триває поточний стан (тривога чи тиша), хвилини |
| `sensor.alerts_<uid>_last_end` | Останній відбій; атрибут `started_at` |
| `sensor.alerts_<uid>_last_duration` | Тривалість останньої завершеної тривоги, хвилини |
| `sensor.alerts_<uid>_count_24h`, `_7d`, `_30d` | Кількість тривог за останні 24 години / 7 / 30 днів (ковзні вікна) |
| `sensor.alerts_<uid>_duration_24h`, `_7d`, `_30d` | Сумарна тривалість тривог за період (показується в годинах); атрибут `longest_min` |
| `sensor.alerts_<uid>_history_updated` | Діагностика: коли востаннє завантажено історію (типово вимкнено) |
| `event.alerts_<uid>_events` | Події регіону, див. нижче |

Сенсори початку, тривалості й статистики рахують лише типи тривог, обрані для регіону (типово тільки повітряна тривога). Тривоги, що перекриваються (наприклад, в області й у районі), зливаються в одну.

## Події

Сутність `event.alerts_<uid>_events` і подія шини `alerts_event` (з полем `event_type`):

| `event_type` | Коли |
|---|---|
| `alert_started` | Почалася тривога типу `alert_type` |
| `alert_ended` | Відбій; додатково `ended_at`, `duration_min` |
| `alert_updated` | Під час повітряної тривоги змінився рівень або набір загроз; `previous_level`, `added_threats`, `removed_threats` |
| `partial_started` / `partial_ended` | Тривога з'явилась / зникла лише в частині регіону |

Загальні поля: `region`, `uid`, `alert_type`, `status`, `level`, `threats`, `threat_titles`, `partial_locations`, `started_at`, `at`.

Приклад автоматизації:

```yaml
triggers:
  - trigger: state
    entity_id: event.alerts_31_events
    not_from: unavailable
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.event_type in ['alert_started', 'alert_ended'] }}"
actions:
  - action: notify.notify
    data:
      message: >
        {% set a = trigger.to_state.attributes %}
        {{ a.region }}: {{ 'тривога' if a.event_type == 'alert_started' else 'відбій' }}
        {%- if a.threat_titles %} ({{ a.threat_titles | join(', ') }}){% endif %}
```

## Налаштування

- **Інтервал опитування** (типово 30 с, від 15 с): один запит до alerts.in.ua на всі регіони. Ліміт API 8–10 запитів на хвилину.
- **Інтервал оновлення історії** (типово 30 хв): історія за місяць для статистики, по одному запиту на область (ліміт API 2 на хвилину; запити йдуть з паузою).
- Регіон можна перейменувати й змінити типи тривог для статистики (три крапки біля регіону → «Змінити»).
- Якщо токен перестав працювати, Home Assistant запропонує ввести новий.

Окрема помилка опитування не робить сутності недоступними; вони стають недоступними, якщо даних немає понад 10 хвилин.

## Довідник регіонів

Коди регіонів і їхня ієрархія (громада → район → область) лежать у `locations.json`; їх узято з публічного переліку локацій alerts.in.ua.

## Ліцензія

MIT.
