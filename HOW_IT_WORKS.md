# Як реалізовано Indeed Job Parser

## 1. Потік даних

```text
config.toml
    ↓
collector.py → JobSpy → Indeed
    ↓ raw dict
normalizer.py → стабільна JobRecord
    ↓
eligibility.py → eligible / unknown / rejected
    ↓
repository.py → SQLite
    ↓
exporter.py → CSV / JSON / report.md
```

CLI `indeed-jobs run --config ...` лише запускає цей потік і друкує JSON-підсумок. Бізнес-логіка не захована в CLI, тому її можна тестувати або викликати з іншої програми.

## 2. Конфіг

`config.py` читає TOML стандартним `tomllib` із Python 3.11. Шляхи до бази та output обчислюються відносно самого config-файлу, а не поточної директорії shell. Це робить запуск однаковим із cron і вручну.

- `country` передається в `country_indeed` JobSpy;
- `location` — місто або країна для пошуку;
- `distance_km` конвертується в милі;
- `days_old` конвертується в години;
- кожен query запускається незалежно, тому помилка одного запиту не стирає успішні результати інших.

## 3. Нормалізація

`normalizer.py` перетворює нестабільний словник JobSpy у `JobRecord` із фіксованими полями.

Для Indeed URL зберігаються тільки identity-параметри `jk` або `vjk`. Tracking-параметри видаляються. `dedupe_key` — SHA-256 від джерела та стабільного ID/URL, тому повторне спостереження оновлює ту саму вакансію.

Це дедуплікація **в межах Indeed**. Вона не вважає Indeed- і LinkedIn-оголошення однією вакансією лише через схожі title/company. Для майбутнього об'єднання джерел потрібно зберігати обидва source listings і окремо визначати спільну логічну вакансію за company, title, location, description та application URL.

Зарплата зберігається роздільно:

- `salary_min`;
- `salary_max`;
- `salary_currency`;
- `salary_period`.

Якщо Indeed не показує зарплату, поля залишаються `NULL`; система не вигадує значення.

## 4. Eligibility до 5 років

`eligibility.py` спочатку перевіряє **назву**, а не ключові слова в описі.

Рішення:

- `eligible` — Middle/Medior у назві або явна вимога не більше 5 років;
- `unknown` — релевантна назва, але вимога до досвіду не вказана;
- `rejected` — нерелевантна роль, Junior/Lead/Principal/Staff/management, Senior без доказу ≤5 років або явна вимога 6+ років.

`unknown` не перейменовується в Middle. Його можна включати або виключати через `include_unknown`.

Senior допускається лише тоді, коли опис прямо містить вимогу до 5 років включно. Це захищає від ситуації, коли високий score піднімає вакансію з вимогою 10+ років.

## 5. SQLite

`repository.py` створює три таблиці:

### `jobs`

Поточний стан унікальної вакансії. `dedupe_key` має UNIQUE index. Повторний збір виконує UPSERT і зберігає `first_seen_at`, оновлюючи `last_seen_at`.

### `ingestion_runs`

Один рядок на запуск: конфіг, час, статус, кількість отриманих/eligible/unknown/rejected та помилки.

### `job_observations`

Історія кожної появи вакансії у конкретному запуску плюс raw payload. Завдяки цьому можна перевірити, що саме повернув Indeed до нормалізації.

Налаштування SQLite:

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

WAL дозволяє читати базу під час короткого запису парсера. Writer усе одно один — це відповідає локальному cron-сценарію.

## 6. Експорти

Після кожного запуску створюються:

- `jobs-all.*` — усі рішення, включно з rejected;
- `jobs-selected.*` — eligible та, якщо дозволено, unknown;
- `report.md` — компактний людський список.

SQLite зберігає історію між запусками, а файли показують саме останній запуск.

## 7. Обробка помилок

Кожен search query виконується окремо. Якщо один запит падає через rate limit або мережу:

- інші результати зберігаються;
- run отримує статус `partial`;
- текст помилки записується в `ingestion_runs`;
- CLI повертає ненульовий exit code.

Немає proxy rotation, CAPTCHA bypass, сесій користувача або збереження credentials.

## 8. Тести

Тести не ходять у мережу. Вони підставляють fake JobSpy-функцію та перевіряють:

- параметри пошуку;
- незалежність query;
- canonical URL і dedupe key;
- правила досвіду;
- UPSERT та observations;
- аудит ingestion run;
- CSV/JSON/Markdown exports;
- CLI JSON summary.

Окремо виконується малий live smoke test із `config/smoke.toml`.
