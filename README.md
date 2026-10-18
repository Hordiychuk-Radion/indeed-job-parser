# Indeed Job Parser

Окремий локальний проєкт для конфігурованого збору вакансій Indeed, їх нормалізації, перевірки вимог до досвіду та збереження у SQLite, CSV і JSON.

Grafana навмисно не входить у цей репозиторій.

## Що відбувається під час запуску

```text
TOML-конфіг
    → окремий JobSpy-запит для кожного search query
    → нормалізація полів і Indeed URL
    → дедуплікація повторних Indeed-оголошень
    → класифікація eligible / unknown / rejected
    → UPSERT у SQLite та запис історії спостережень
    → CSV, JSON і Markdown-звіт
```

Основні модулі:

- `config.py` — читає й перевіряє TOML-конфіг;
- `collector.py` — викликає JobSpy лише для Indeed;
- `normalizer.py` — перетворює результат JobSpy у стабільну модель;
- `stack.py` — детерміновано виділяє технології з title та description у категорії;
- `eligibility.py` — перевіряє роль, рівень і вимоги до досвіду;
- `repository.py` — зберігає поточні вакансії та історію запусків у SQLite;
- `exporter.py` — створює CSV, JSON і `report.md`;
- `pipeline.py` — послідовно з'єднує всі етапи;
- `profiles.py` — знаходить і створює іменовані TOML-профілі;
- `europe.py` — послідовно збирає Data Engineer по підтримуваних європейських Indeed-доменах, зберігає snapshots і найбільші вибірки;
- `cli.py` — надає меню, профілі та розширені CLI-параметри.

## Швидкий старт

```bash
uv sync --all-groups
uv run indeed-jobs
```

Без параметрів відкривається коротке меню:

```text
1. Запустити збережений профіль
2. Створити новий профіль
3. Швидкий одноразовий пошук
4. Показати профілі
0. Вихід
```

Готовий профіль можна запустити однією короткою командою:

```bash
uv run indeed-jobs run data-engineer-middle-de
```

Переглянути всі профілі або створити новий через майстер:

```bash
uv run indeed-jobs profiles
uv run indeed-jobs create-profile
```

Профілі зберігаються як TOML-файли у `config/profiles/`. Майстер запитує професії, seniority, країну, місто, кількість, давність, радіус, remote та experience policy і створює окремі SQLite/output paths.

Одноразовий пошук можна задати прямо в терміналі. `--config` необов'язковий і за замовчуванням використовує `config/example.toml`:

```bash
uv run indeed-jobs run \
  --title "Data Engineer" \
  --seniority middle \
  --country "Germany" \
  --country-code DE \
  --location "Berlin" \
  --days-old 7 \
  --results 50
```

Кілька професій задаються повторенням `--title`:

```bash
uv run indeed-jobs run \
  --title "Data Engineer" \
  --title "ETL Developer" \
  --title "Data Platform Engineer" \
  --country "Czech Republic" \
  --country-code CZ \
  --location "Prague" \
  --remote-only
```

CLI-параметри діють тільки під час поточного запуску та не переписують TOML-файл. Пріоритет: **CLI → TOML → стандартні значення програми**.

CLI overrides працюють і поверх короткого профілю:

```bash
uv run indeed-jobs run data-engineer-middle-de \
  --location Hamburg \
  --days-old 7 \
  --results 100
```

Професія та рівень незалежні. Наприклад:

```bash
# Тільки Middle Data Engineer
uv run indeed-jobs run --title "Data Engineer" --seniority middle

# Тільки Senior Data Engineer; усе одно потрібна явна вимога ≤5 років
uv run indeed-jobs run --title "Data Engineer" --seniority senior

# Middle або Senior
uv run indeed-jobs run \
  --title "Data Engineer" \
  --seniority middle \
  --seniority senior
```

Або через Python-модуль:

```bash
uv run python -m indeed_job_parser run --config config/example.toml
```

### Data Engineer по Європі

Окрема команда перевіряє всі підтримувані JobSpy європейські Indeed-домени послідовно. За замовчуванням вона робить спроби з лімітами `100`, `500` і `1000`, зберігає кожну відповідь, а для країни залишає найбільший успішний batch. Менший повторний результат не перезаписує більший.

```bash
uv run indeed-jobs europe-data-engineer
```

Власна директорія, freshness-вікно та набір спроб:

```bash
uv run indeed-jobs europe-data-engineer \
  --output-dir output/europe-data-engineer \
  --database output/europe-data-engineer/jobs.db \
  --days-old 30 \
  --limit 100 \
  --limit 500
```

Стандартне `--days-old 3650` практично прибирає freshness-обмеження для активних вакансій. Команда не обіцяє, що Indeed поверне весь свій індекс: `results_wanted` є верхньою межею, а пагінація Indeed може бути нестабільною.

Europe-результати:

- `jobs-all.json` — дедуплікована сира пошукова видача після нормалізації;
- `jobs-selected.json` — тільки multilingual title-збіги Data Engineer; кожен запис має явний `url`, категоризований `stack` і плоский `stack_flat`;
- `report.md` — клікабельний список вакансій і частоти технологій, побудовані з `stack_flat`;
- `summary.json` — кількості, помилки по країнах і агрегований `technology_counts`;
- `snapshots/<country>/<run-id>/limit-*.json` — повна відповідь кожної спроби;
- `snapshots/<country>/largest-batch.json` — найбільша збережена вибірка країни.
- `jobs.db` — SQLite з описами, ingestion history, observations і нормалізованим стеком у `job_technologies`.

`stack` має стабільні категорії: `languages`, `cloud`, `data_platforms`,
`processing_streaming`, `orchestration_transformation`, `databases`, `devops` і
`analytics_bi`. Пошук словниковий і не вигадує технології, яких немає в тексті;
невідомі або не згадані інструменти залишають відповідну категорію порожньою.

Переглянути базу без написання SQL:

```bash
uv run indeed-jobs inspect-db \
  --database output/europe-data-engineer/jobs.db \
  --limit 10
```

Команда друкує JSON із кількістю вакансій, запусків і спостережень, розподілом
eligibility, частотою технологій та останніми вакансіями разом з description і stack.
Для графічного перегляду той самий `jobs.db` можна відкрити у DB Browser for SQLite.

Результати:

- `data/jobs.db` — SQLite з історією запусків, вакансій і спостережень;
- `output/jobs-all.json` та `.csv` — усі рішення поточного запуску;
- `output/jobs-selected.json` та `.csv` — `eligible` плюс дозволені `unknown`;
- `output/report.md` — короткий список із клікабельними посиланнями.

## Конфігурація

Скопіюйте `config/example.toml` і змініть країну, локацію, запити та фільтри. `distance_km` автоматично переводиться в милі, які очікує JobSpy.

```toml
[search]
country = "Czech Republic"
country_code = "CZ"
location = "Prague"
queries = ["QA Engineer", "Data Quality Analyst"]
results_per_query = 25
days_old = 14
distance_km = 80
remote_only = false
# job_type = "fulltime"

[filters]
max_experience_years = 5
include_unknown = true
allowed_seniority = ["middle"]
include_title_patterns = ["QA Engineer", "Data Quality Analyst"]
exclude_title_patterns = ["Junior", "Intern", "Lead", "Principal", "Staff", "Manager"]
# min_salary = 60000
# salary_currency = "CZK"
# salary_period = "monthly"

[storage]
database_path = "../data/jobs.db"
output_dir = "../output"
```

Якщо `include_title_patterns` не заданий, програма використовує значення `queries`. Тобто для звичайного випадку достатньо змінити `queries` або передати `--title`. Окремі patterns потрібні, коли пошуковий запит ширший за допустимі назви вакансій.

### Які фільтри автоматизовані

- **Пошук у JobSpy:** title/query, country, location, radius, freshness, result count, remote-only, job type.
- **Перевірка після збору:** допустимі та виключені title-фрази, seniority, максимум років досвіду, unknown-policy, мінімальна зарплата, валюта й salary period.
- `--exclude-title` можна повторювати так само, як `--title`.
- `--seniority` приймає `middle`, `senior` або `unspecified`; параметр можна повторити для кількох рівнів.
- Зарплата порівнюється лише в узгодженій валюті та періоді; відомі невідповідності отримують окрему причину відхилення.

Усі доступні параметри термінала:

```bash
uv run indeed-jobs run --help
```

## Команди розробника

```bash
uv run pytest
uv run python -m compileall -q src tests
```

Детальна архітектура та логіка рішень описані у [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md).

## Межі поточної версії

- Збирається тільки Indeed; LinkedIn у цьому репозиторії не викликається.
- Дедуплікація використовує Indeed ID або canonical URL і прибирає повтори тієї самої Indeed-вакансії між запитами та запусками.
- Кросджерельна дедуплікація Indeed ↔ LinkedIn ще не реалізована; її слід робити в окремому агрегаторі зі спільним контрактом даних.
- `unknown` означає, що явну вимогу до досвіду не знайдено, а не те, що вакансія гарантовано підходить.
- Фільтр зарплати застосовується тільки коли Indeed реально повернув зарплату у вказаній валюті. Відсутня зарплата не вигадується і не є причиною автоматичного відхилення.
- HTML scraping, логін, CAPTCHA bypass, proxy rotation та збереження облікових даних не використовуються.
- Europe-команда охоплює підтримувані JobSpy/Indeed країни, а не всі географічні країни Європи; нульова відповідь без помилки означає, що поточний Indeed connector не повернув вакансій для цього домену.
