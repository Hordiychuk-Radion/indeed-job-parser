# Як реалізовано Indeed Job Parser

## 1. Потік даних

```text
config.toml
    ↓
collector.py → JobSpy → Indeed
    ↓ raw dict
normalizer.py → JobRecord
    ↓
stack.py → technology stack + required/preferred/alternative evidence + concepts
    ↓
eligibility.py → eligible / unknown / rejected
    ↓
repository.py → SQLite: jobs / observations / job_technologies / job_concepts
    ↓
exporter.py → CSV / JSON / report.md
```

CLI, інтерактивне меню та короткі профілі лише формують шлях до TOML і runtime overrides, запускають цей потік та друкують JSON-підсумок. Бізнес-логіка не захована в CLI, тому її можна тестувати або викликати з іншої програми.

Окремий `europe.py` повторно використовує ті самі `collector.py` і `normalizer.py`, але оркеструє багато країн. Для кожної країни запити виконуються послідовно з кількома лімітами. Кожна спроба записується у власний snapshot, а `largest-batch.json` оновлюється лише тоді, коли нова унікальна вибірка більша. Після цього country batches дедуплікуються за звичайним `dedupe_key`; title-only multilingual фільтр прибирає результати, де `data` трапилося лише в описі, і формує JSON з явним `url` та клікабельний Markdown.

## 2. Конфіг

`config.py` читає TOML стандартним `tomllib` із Python 3.11. Шляхи до бази та output обчислюються відносно самого config-файлу, а не поточної директорії shell. Це робить запуск однаковим із cron і вручну.

- `country` передається в `country_indeed` JobSpy;
- `location` — місто або країна для пошуку;
- `distance_km` конвертується в милі;
- `days_old` конвертується в години;
- кожен query запускається незалежно, тому помилка одного запиту не стирає успішні результати інших.

Професія не захардкоджена в Python. `filters.include_title_patterns` визначає допустимі фрази в title, а `filters.exclude_title_patterns` — небажані рівні або ролі. Якщо include-список відсутній, ним автоматично стають `search.queries`.

CLI створює `ConfigOverrides` і передає його в pipeline. Значення з CLI замінюють конфіг лише в пам'яті на час одного запуску. `--title` одночасно замінює `search.queries` та `include_title_patterns`, тому швидкий перехід із QA на Data Engineer не потребує змін Python-коду.

`profiles.py` сканує `config/profiles/*.toml`. Назва файла без `.toml` є коротким ім'ям, тому `config/profiles/data-engineer-middle-de.toml` запускається як `indeed-jobs run data-engineer-middle-de`. Майстер `create-profile` генерує такий TOML, але далі він читається тим самим `config.py`; окремої прихованої системи налаштувань немає.

Запуск без аргументів відкриває цифрове меню. Воно дозволяє вибрати профіль, створити профіль або виконати одноразовий пошук. Одноразовий пошук створює `ConfigOverrides` у пам'яті й не записує новий TOML.

`--seniority` незалежно обмежує рівень до `middle`, `senior` або `unspecified`. Кілька значень можна передати повторенням параметра. Порожній список у TOML означає, що окремого seniority-обмеження немає й діють звичайні правила eligibility.

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

`eligibility.py` спочатку перевіряє **назву**, а не ключові слова в описі. Допустимі та виключені фрази надходять із конфігурації, тому одна й та сама логіка працює для QA, Data Engineer та інших професій.

Рішення:

- `eligible` — Middle/Medior у назві або явна вимога не більше 5 років;
- `unknown` — релевантна назва, але вимога до досвіду не вказана;
- `rejected` — нерелевантна роль, Junior/Lead/Principal/Staff/management, Senior без доказу ≤5 років або явна вимога 6+ років.

`unknown` не перейменовується в Middle. Його можна включати або виключати через `include_unknown`.

Senior допускається лише тоді, коли опис прямо містить вимогу до 5 років включно. Це захищає від ситуації, коли високий score піднімає вакансію з вимогою 10+ років.

## 5. SQLite

`repository.py` використовує одну SQLite-базу для Europe та country-запусків:

### `jobs`

Поточний стан унікальної вакансії. `dedupe_key` має UNIQUE index. Повторний збір виконує UPSERT і зберігає `first_seen_at`, оновлюючи `last_seen_at`.

### `ingestion_runs`

Один рядок на запуск: конфіг, час, статус, кількість отриманих/eligible/unknown/rejected та помилки.

### `job_observations`

Історія кожної появи вакансії у конкретному запуску плюс raw payload. Завдяки цьому можна перевірити, що саме повернув Indeed до нормалізації.

### `job_technologies`

Нормалізовані рядки `job_id + category + technology`. Для кожної технології
додатково зберігаються `requirement_type`, секція description та точний фрагмент
`evidence_text`. Класифікація детермінована: явні required-формулювання,
nice-to-have/preferred секції та явні альтернативи обробляються окремо; без
достатнього контексту використовується `mentioned`.

### `job_concepts`

Окремо зберігає загальні поняття (`ETL/ELT`, `NLP`, `Data Quality`, `Lakehouse`,
`Data Modeling` тощо) з таким самим evidence. Це не technology stack, тому
концепції не збільшують підрахунок конкретних інструментів.

### `search_scopes` і `scope_jobs`

`search_scopes` описує логічні витяги: `europe:data-engineer`, `country:DE`, `country:CZ` тощо. `scope_jobs` пов'язує вакансії з витягами та зберігає eligibility саме в межах цього витягу. Одна вакансія може входити одночасно до Europe і country scope без дублювання рядка в `jobs`.

Views `europe_jobs` і `country_jobs` дають готові списки для DB Browser. Повторний запуск замінює membership тільки свого scope й не стирає інші витяги.

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

Europe-збір також не запускає країни паралельно, щоб не створювати штучний burst запитів. Помилка однієї country/limit-спроби записується в її snapshot і не стирає результати інших країн. Значення `100/500/1000` є верхніми межами, а не гарантією кількості: якщо Indeed повернув менше на більшому ліміті, зберігається попередній більший batch.

Для вибраних Europe-вакансій `stack.py` перевіряє title і description за словником
технологій та записує у JSON два сумісні представлення: категоризований `stack` і
дедуплікований `stack_flat`. У SQLite той самий збір додатково записує контекстну
класифікацію та evidence, а concepts тримає окремо. `report.md` і `summary.json`
підраховують присутність технологій; для точного required/preferred аналізу слід
query-ити `job_technologies.requirement_type` та `evidence_text`.

Europe-збір замінює лише membership scope `europe:data-engineer`, тому country
scopes, їх observations і technologies не стираються. View `europe_jobs` містить
актуальний snapshot лише відібраних Europe-вакансій; відхилена пошукова видача
залишається у `jobs-all.json` і snapshots. `jobs.description`
містить актуальний нормалізований опис, `job_observations.raw_payload` — payload
конкретного спостереження, а `job_technologies` — нормалізовані пари
`category + technology`. Команда `indeed-jobs inspect-db` читає ці таблиці й
повертає машинозрозумілий JSON для ручної перевірки або наступного звіту.

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

## 9. Швидкі CLI overrides

Підтримуються:

- `--title` — можна повторювати;
- `--country`, `--country-code`, `--location`;
- `--results`, `--days-old`, `--distance-km`;
- `--remote-only` / `--no-remote-only`;
- `--job-type`;
- `--max-experience-years`;
- `--seniority middle|senior|unspecified` — можна повторювати;
- `--exclude-title` — можна повторювати;
- `--include-unknown` / `--no-include-unknown`;
- `--min-salary`, `--salary-currency`, `--salary-period`.

Приклад:

```bash
uv run indeed-jobs run \
  --title "Data Engineer" \
  --title "ETL Developer" \
  --country "Germany" \
  --country-code DE \
  --location "Berlin" \
  --days-old 7 \
  --results 50
```

## 10. Зручні профілі та меню

```bash
# Інтерактивне меню
uv run indeed-jobs

# Список профілів
uv run indeed-jobs profiles

# Створення профілю через питання
uv run indeed-jobs create-profile

# Короткий повторний запуск
uv run indeed-jobs run data-engineer-middle-de

# Тимчасова зміна поверх профілю
uv run indeed-jobs run data-engineer-middle-de --location Hamburg --days-old 7
```

Пріоритет не змінився: `CLI override → profile TOML → defaults`. Профіль не редагується під час запуску.

## 11. Europe Data Engineer

```bash
uv run indeed-jobs europe-data-engineer
```

Команда проходить усі європейські країни з `EUROPE_COUNTRIES`, які підтримує поточна версія JobSpy. Вона не використовує TOML-профіль або city filter: її мета — широкий source-level dataset Data Engineer із повним аудитом спроб. Явні вимоги понад 5 років не входять до Europe scope; невказаний досвід зберігається як `unknown` для review. Персональний Grafana shortlist додатково прибирає Junior/Lead/Principal/Staff/management і допускає Senior лише з підтвердженням ≤5 років.

## 12. Grafana report

`docker-compose.grafana.yml` спочатку запускає одноразовий `prepare-grafana-db`.
`scripts/prepare_grafana_database.py` використовує SQLite backup API, перевіряє snapshot
через `PRAGMA integrity_check` і атомарно кладе його в окремий Docker volume. Після цього
Grafana 13.2.4 стартує на `127.0.0.1:3001` та бачить snapshot як read-only
`/data/jobs.db`. Provisioning створює datasource `jobs-sqlite` для plugin
`frser-sqlite-datasource` і завантажує п'ять JSON dashboards із `grafana/dashboards/`.

```text
data/jobs.db
    ↓ SQLite backup API + integrity check
read-only reporting snapshot
    ↓ query-only SQLite datasource
Overview / Technology Demand / Geography / Candidate Fit / Vacancy Explorer
```

`scripts/build_grafana_dashboards.py` є відтворюваним джерелом dashboard JSON. Тести
перевіряють стабільні UID, datasource bindings, фільтри, URL/evidence contract і виконують
кожен panel SQL проти мінімальної SQLite-схеми. `scripts/verify_grafana.py` додатково читає
health, datasource, усі dashboards і реальну кількість вакансій через живий Grafana API.

Grafana не змінює job data: reporting volume монтується read-only, datasource provisioned як
non-editable, SQLite plugin додає query-only pragma, а anonymous user має лише Viewer.
Source-каталог `data/` доступний лише короткоживучому snapshot-контейнеру, бо читання WAL-бази
може потребувати сусідніх `-wal`/`-shm` файлів. Після нового parser run report оновлюється через
повторний `docker compose ... down` і `docker compose ... up -d`.
