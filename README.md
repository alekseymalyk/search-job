# 🔍 Job Scraper

Автоматизированный пайплайн для скрейпинга вакансий с **LinkedIn** и **Indeed** — фильтрация, ранжирование, экспорт в CSV.

## ⚡ Быстрый старт (одна команда)

```bash
# 1. Установи uv (если ещё нет):
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Запусти — всё подтянется автоматически:
uv run job-scraper

# Или классически через main.py:
uv run python main.py
```

> `uv run` сам создаст виртуальное окружение, установит зависимости и запустит пайплайн.
> Никаких `pip install`, `venv`, `requirements.txt` — **одна команда**.

---

## 📋 Что делает проект

Трёхэтапный пайплайн:

```
LinkedIn/Indeed → [Scrape] → [Filter] → [Rank] → CSV
```

| Этап | Команда | Описание |
|------|---------|----------|
| **Scrape** | `uv run job-scraper scrape` | Собирает вакансии по городам × запросам × временным окнам |
| **Filter** | `uv run job-scraper filter` | Жёсткая фильтрация: стажировки, опыт 2+ лет, спонсоры виз |
| **Rank** | `uv run job-scraper rank` | Ранжирование по сходству с ранее поданными заявками |
| **Всё сразу** | `uv run job-scraper` | Полный пайплайн (по умолчанию) |

---

## 🚀 Установка и запуск

### macOS / Linux

```bash
# Установка uv (один раз):
curl -LsSf https://astral.sh/uv/install.sh | sh
# или через Homebrew (macOS):
brew install uv

# Перейди в проект и запусти:
cd Job_Scraper
uv run job-scraper
```

### Windows (PowerShell)

```powershell
# Установка uv (один раз):
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# или через winget:
winget install --id=astral-sh.uv -e
# или через pip:
pip install uv

# Перейди в проект и запусти:
cd Job_Scraper
uv run job-scraper
```

### Windows (cmd)

```cmd
REM Установка uv через pip:
pip install uv

REM Перейди в проект и запусти:
cd Job_Scraper
uv run job-scraper
```

> **Важно:** На Windows может потребоваться перезапустить терминал после установки `uv`,
> чтобы команда стала доступна в PATH.

---

## 🎯 Примеры использования

```bash
# Полный пайплайн с настройками по умолчанию:
uv run job-scraper

# Только скрейпинг (без фильтрации):
uv run job-scraper scrape

# Только фильтрация (если jobs.csv уже есть):
uv run job-scraper filter

# Только ранжирование:
uv run job-scraper rank

# Кастомный поисковый запрос:
uv run job-scraper --query "data analyst Amsterdam"
uv run job-scraper -q "python developer remote"

# Посмотреть версию:
uv run job-scraper --version

# Справка:
uv run job-scraper --help
```

---

## ⚙️ Конфигурация

Все настройки — в файле `src/job_scraper/config.py`:

| Параметр | Описание | По умолчанию |
|----------|----------|-------------|
| `SITES` | Сайты для скрейпинга | `["linkedin", "indeed"]` |
| `PROVINCE_TO_BIGGEST_CITY` | Города для поиска | 5 городов Нидерландов |
| `HOURS_WINDOWS` | Временные окна | `[48, 168, 336]` часов |
| `KEYWORD_SPLITS` | Поисковые запросы | 7 бизнес-запросов |
| `RESULTS_WANTED_PER_RUN` | Макс. результатов за запрос | `3000` |
| `SLEEP_BETWEEN_RUNS_SEC` | Пауза между запросами | `6` сек |
| `SPONSOR_MATCH_THRESHOLD` | Порог для спонсоров виз | `0.70` |

### Дополнительные файлы (опционально)

Положи в корень проекта `Job_Scraper/`:

| Файл | Назначение |
|------|-----------|
| `visa_sponsors.csv` | Список компаний-спонсоров виз (1 колонка с названиями) |
| `submitted_applications.csv` | Ранее поданные заявки (колонки: Company, Position, Description) |

> Если файлы отсутствуют — фильтрация просто пропускается с предупреждением.

---

## 📁 Структура проекта

```
Job_Scraper/
├── main.py                     # ← Точка входа (python main.py)
├── pyproject.toml              # Зависимости и entry point
├── uv.lock                     # Lock-файл (коммитится в git)
├── README.md
├── .gitignore
│
├── src/job_scraper/            # Исходный код (Python-пакет)
│   ├── __init__.py             # Версия пакета
│   ├── __main__.py             # python -m job_scraper
│   ├── cli.py                  # CLI (argparse)
│   ├── config.py               # Все настройки и пути
│   ├── scraper.py              # Этап 1: скрейпинг
│   ├── filter_stage1.py        # Этап 2: жёсткая фильтрация
│   └── filter_stage2.py        # Этап 3: ранжирование
│
├── visa_sponsors.csv           # (опционально) спонсоры виз
├── submitted_applications.csv  # (опционально) поданные заявки
│
└── output/                     # Результаты (создаётся автоматически)
    ├── runs_raw/               # Сырые данные по каждому запросу
    ├── jobs.csv                # Объединённые вакансии
    ├── jobs_stage1.csv         # После фильтрации
    └── jobs_final.csv          # Финальный ранжированный результат
```

---

## ❓ Частые проблемы

| Проблема | Решение |
|----------|---------|
| `uv: command not found` | Установи uv (см. раздел «Установка»), перезапусти терминал |
| `uv: The term 'uv' is not recognized` | Windows: перезапусти PowerShell после установки |
| LinkedIn блокирует запросы | Увеличь `SLEEP_BETWEEN_RUNS_SEC` в `config.py` |
| Пустой результат | Проверь ключевые слова в `KEYWORD_SPLITS` |
| `visa_sponsors.csv not found` | Это предупреждение — спонсорский фильтр просто пропускается |
