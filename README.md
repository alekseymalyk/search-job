# 🔍 Job Scraper

Автоматизированный многопоточный пайплайн для скрейпинга вакансий с **LinkedIn** и **Indeed**.
Понимает запросы на **украинском**, **русском** и **английском** языках.

## ⚡ Быстрый старт (одна команда)

```bash
# 1. Установи uv (если ещё нет):
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Запусти — всё подтянется автоматически:
uv run job-scraper

# Или через main.py:
uv run python main.py
```

> `uv run` сам создаст `.venv`, установит зависимости и запустит.
> Никаких `pip install`, `venv`, `requirements.txt` — **одна команда**.

---

## 🧠 Естественный язык

Пиши запрос как обычный текст — парсер сам вытащит параметры:

```bash
uv run python main.py "знайди мені 100 компаній які шукають 3D hard-surface artist. Шукай виключно remote позиції, шукай у країнах ЄС, США та Канади. Відфільтруй за зарплатнею. Максимум двох тиждневої давнини."
```

Что будет распознано:

```
  Job title:     3D hard-surface artist
  Results:       100
  Remote only:   True
  Locations:     Austria, Belgium, ..., Poland, ..., United States, Canada
  Max age:       336h (14d)
  Salary filter: True
```

### Примеры запросов

```bash
# Украинский
uv run python main.py "знайди 50 вакансій 3D artist, remote, ЄС, 2 тижні"

# Русский
uv run python main.py "найди 200 вакансий data analyst, удалённо, США и Канада, 7 дней"

# English
uv run python main.py "find 100 companies looking for product manager, remote, EU and USA"

# Короткий запрос
uv run python main.py -q "3D artist remote"
```

---

## 🚀 Установка

### macOS / Linux

```bash
# Установка uv:
curl -LsSf https://astral.sh/uv/install.sh | sh
# или:
brew install uv

# Перейди в проект и запусти:
cd Job_Scraper
uv run job-scraper
```

### Windows (PowerShell)

```powershell
# Установка uv:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# или:
winget install --id=astral-sh.uv -e
# или:
pip install uv

# Перейди в проект и запусти:
cd Job_Scraper
uv run job-scraper
```

### Windows (cmd)

```cmd
pip install uv
cd Job_Scraper
uv run job-scraper
```

> **Windows:** перезапусти терминал после установки `uv`.

---

## 🎯 Команды

| Команда | Описание |
|---------|----------|
| `uv run job-scraper` | Полный пайплайн (scrape → filter → rank) |
| `uv run job-scraper scrape` | Только скрейпинг |
| `uv run job-scraper filter` | Только фильтрация (Stage 1) |
| `uv run job-scraper rank` | Только ранжирование (Stage 2) |
| `uv run job-scraper "текст"` | Естественный язык |
| `uv run job-scraper -q "query"` | Короткий запрос |
| `uv run job-scraper -w 5` | Указать число потоков |
| `uv run job-scraper --version` | Версия |
| `uv run job-scraper --help` | Справка |

> Все команды также работают через `uv run python main.py ...`

---

## ⚡ Многопоточность

По умолчанию скрейпер запускает **3 потока** параллельно.
Можно изменить:

```bash
# 5 потоков
uv run job-scraper -w 5 "find 100 3D artist remote EU"

# Однопоточный режим (безопаснее для LinkedIn)
uv run job-scraper -w 1

# Или в config.py:
MAX_WORKERS: int = 3
```

---

## ⚙️ Конфигурация

Все настройки — `src/job_scraper/config.py`:

| Параметр | Описание | По умолчанию |
|----------|----------|-------------|
| `SITES` | Сайты для скрейпинга | `["linkedin", "indeed"]` |
| `MAX_WORKERS` | Число потоков | `3` |
| `PROVINCE_TO_BIGGEST_CITY` | Города для поиска | 5 городов NL |
| `HOURS_WINDOWS` | Временные окна | `[48, 168, 336]` |
| `KEYWORD_SPLITS` | Поисковые запросы | 7 бизнес-запросов |
| `RESULTS_WANTED_PER_RUN` | Макс. результатов | `3000` |
| `SLEEP_BETWEEN_RUNS_SEC` | Пауза между запросами | `6` сек |
| `SPONSOR_MATCH_THRESHOLD` | Порог спонсоров виз | `0.70` |

### Дополнительные файлы (опционально)

| Файл | Назначение |
|------|-----------|
| `visa_sponsors.csv` | Компании-спонсоры виз (1 колонка) |
| `submitted_applications.csv` | Поданные заявки (Company, Position, Description) |

> Если отсутствуют — этапы фильтрации пропускаются с предупреждением.

---

## 📁 Структура проекта

```
Job_Scraper/
├── main.py                     # ← Точка входа
├── pyproject.toml              # Зависимости и entry point
├── uv.lock                     # Lock-файл
├── README.md
├── .gitignore
│
├── src/job_scraper/
│   ├── __init__.py             # Версия
│   ├── __main__.py             # python -m job_scraper
│   ├── cli.py                  # CLI (argparse)
│   ├── config.py               # Настройки и пути
│   ├── query_parser.py         # Парсер естественного языка
│   ├── scraper.py              # Скрейпинг (многопоточный)
│   ├── filter_stage1.py        # Фильтрация
│   └── filter_stage2.py        # Ранжирование
│
└── output/                     # Результаты (авто)
    ├── runs_raw/
    ├── jobs.csv
    ├── jobs_stage1.csv
    └── jobs_final.csv
```

---

## ❓ Проблемы

| Проблема | Решение |
|----------|---------|
| `uv: command not found` | Установи uv, перезапусти терминал |
| LinkedIn блокирует | Уменьши потоки: `-w 1`, увеличь `SLEEP_BETWEEN_RUNS_SEC` |
| Пустой результат | Проверь запрос или расширь `HOURS_WINDOWS` |
| `visa_sponsors.csv not found` | Это OK — фильтр просто пропускается |
