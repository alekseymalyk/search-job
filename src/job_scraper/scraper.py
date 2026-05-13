"""
Stage 1: Scrape jobs from LinkedIn & Indeed (multi-threaded).

Iterates over locations × time windows × keyword splits, runs them in parallel
via ThreadPoolExecutor, saves raw CSVs, then merges + deduplicates into jobs.csv.
"""

import logging
import os
import re
import time
import random
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

import pandas as pd
from jobspy import scrape_jobs

from job_scraper import config
from job_scraper.query_parser import ParsedQuery

# ── Suppress noisy third-party output ──
logging.getLogger("jobspy").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("tls_client").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=FutureWarning)

_print_lock = Lock()
_ANSI_GREEN = "\033[92m"
_ANSI_RED = "\033[91m"
_ANSI_YELLOW = "\033[93m"
_ANSI_CYAN = "\033[96m"
_ANSI_DIM = "\033[90m"
_ANSI_BOLD = "\033[1m"
_ANSI_RESET = "\033[0m"

# ── Default settings for generic scans ──
DEFAULT_LOCATIONS = [
    "Eindhoven, Netherlands", "Amsterdam, Netherlands", "Enschede, Netherlands",
    "Rotterdam, Netherlands", "Utrecht, Netherlands"
]
DEFAULT_HOURS_WINDOWS = [48, 168, 336]
DEFAULT_KEYWORDS = [
    "finance OR fintech OR payments OR banking OR treasury OR pricing OR revenue",
    "operations OR ops OR business operations OR process OR workflow OR execution",
    "sales OR commercial OR account OR customer OR client OR partnerships OR growth",
    "marketing OR brand OR campaign OR go-to-market OR gtm OR acquisition",
    "supply chain OR logistics OR procurement OR sourcing OR demand planning",
    "business OR strategy OR planning OR insights OR analytics",
    "product OR implementation OR onboarding OR rollout OR delivery",
]


def _tprint(*args, **kwargs):
    """Thread-safe print."""
    with _print_lock:
        print(*args, **kwargs)


# ───────────────────────── HELPERS ─────────────────────────

def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename provider-specific columns to a unified schema."""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["company", "position", "location", "url", "description", "source"])

    df = df.copy()
    rename_map = {}
    taken = set(df.columns)

    def _try_rename(src: str, dst: str) -> None:
        if src in df.columns and dst not in taken:
            rename_map[src] = dst
            taken.add(dst)

    _try_rename("title", "position")
    _try_rename("job_url", "url")
    _try_rename("job_url_direct", "url")
    _try_rename("company_name", "company")
    _try_rename("job_location", "location")
    _try_rename("job_description", "description")
    _try_rename("site", "source")
    _try_rename("job_board", "source")

    df = df.rename(columns=rename_map)
    df = df.loc[:, ~df.columns.duplicated()]

    for col in ["company", "position", "location", "url", "description", "source"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)

    if config.MAX_DESC_CHARS is not None:
        df["description"] = df["description"].str.slice(0, int(config.MAX_DESC_CHARS))

    return df


def has_nonempty_description(s: str) -> bool:
    if s is None:
        return False
    s = str(s).strip()
    return bool(s and s.lower() not in {"nan", "none", "null"})


def dedupe_jobs(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate jobs, keeping the entry with the longest description."""
    df = df.copy()
    df["company_norm"] = df["company"].astype(str).str.lower().str.strip()
    df["position_norm"] = df["position"].astype(str).str.lower().str.strip()
    df["location_norm"] = df["location"].astype(str).str.lower().str.strip()
    df["url_norm"] = df["url"].astype(str).str.strip()

    def make_key(r) -> str:
        primary_ok = bool(r["company_norm"]) and bool(r["position_norm"]) and bool(r["location_norm"])
        if primary_ok:
            return f"{r['company_norm']}||{r['position_norm']}||{r['location_norm']}"
        if r["url_norm"]:
            return r["url_norm"]
        return f"{r['company_norm']}||{r['position_norm']}||{r['location_norm']}||{r.name}"

    df["dedupe_key"] = df.apply(make_key, axis=1)
    df["__desc_len"] = df["description"].astype(str).str.len()
    df["__has_url"] = df["url_norm"].ne("").astype(int)

    df = df.sort_values(
        by=["dedupe_key", "__has_url", "__desc_len"],
        ascending=[True, False, False],
    )
    df = df.drop_duplicates(subset="dedupe_key", keep="first")

    return df.drop(columns=[
        "company_norm", "position_norm", "location_norm", "url_norm",
        "dedupe_key", "__desc_len", "__has_url",
    ])


def expand_keywords(title: str) -> list[str]:
    """Generate search keyword variations from a job title for better coverage."""
    if not title:
        return []
        
    keywords = [title]
    words = title.split()
    if len(words) >= 3:
        short = f"{words[0]} {words[-1]}"
        if short.lower() != title.lower():
            keywords.append(short)

    synonyms = {
        "artist": ["designer", "modeler"],
        "developer": ["engineer", "programmer"],
        "manager": ["lead", "coordinator"],
        "analyst": ["specialist", "consultant"],
        "designer": ["artist", "creator"],
    }
    last = words[-1].lower() if words else ""
    if last in synonyms:
        base = " ".join(words[:-1])
        for syn in synonyms[last]:
            keywords.append(f"{base} {syn}")

    return keywords


# ───────────────────────── SINGLE RUN ─────────────────────────

def scrape_one_run(
    search_term: str,
    hours_old: int,
    location: str,
    run_tag: str,
    is_remote: bool = False,
    results_wanted: int = 100,
) -> pd.DataFrame:
    run_start = time.time()

    loc_lower = location.lower().strip()
    if loc_lower in ("czech republic", "czechia"):
        country_indeed = "czechia"
    elif loc_lower in config.VALID_JOBSPY_COUNTRIES:
        country_indeed = loc_lower
    else:
        country_indeed = config.COUNTRY_INDEED

    kwargs = dict(
        site_name=config.SITES,
        search_term=search_term,
        location=location,
        hours_old=hours_old,
        results_wanted=results_wanted,
        linkedin_fetch_description=True,
        country_indeed=country_indeed,
        verbose=0,
    )
    if is_remote:
        kwargs["is_remote"] = True

    max_retries = 3
    df = None
    last_err = None

    for attempt in range(max_retries):
        try:
            df = scrape_jobs(**kwargs)
            break
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if "max retries exceeded" in err_str or "nodename nor servname" in err_str or "429" in err_str or "invalid country" in err_str:
                if "invalid country" in err_str:
                    kwargs["country_indeed"] = "worldwide"
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(2, 5) * (attempt + 1))
                    continue
            raise last_err

    if df is None or len(df) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(df)
    df = normalize_columns(df)

    df["run_query"] = search_term
    df["run_hours_old"] = hours_old
    df["run_location"] = location
    df["scrape_ts_utc"] = datetime.now(timezone.utc).isoformat()

    out = config.RAW_RUNS_DIR / f"run_{run_tag}.csv"
    df.to_csv(out, index=False)

    return df


# ───────────────────────── ORCHESTRATOR ─────────────────────────

def _build_run_plan(query: ParsedQuery) -> list[dict]:
    """Build a list of scraping runs based on the parsed query."""
    locs = query.locations if query.locations else DEFAULT_LOCATIONS
    hours_list = [query.max_age_hours] if query.max_age_hours else DEFAULT_HOURS_WINDOWS
    
    if query.job_title:
        expanded = expand_keywords(query.job_title)
        seen = set()
        kw_list = []
        for kw in expanded:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                kw_list.append(kw)
    else:
        kw_list = DEFAULT_KEYWORDS

    plan = []
    run_id = 0
    for loc in locs:
        loc_slug = slugify(loc)
        for hours in hours_list:
            for kw in kw_list:
                run_id += 1
                plan.append({
                    "run_id": run_id,
                    "run_tag": f"{run_id:04d}_{loc_slug}_{hours}h",
                    "search_term": f"({kw})" if " OR " in kw else kw,
                    "hours_old": hours,
                    "location": loc,
                    "is_remote": query.remote,
                    "results_wanted": query.count,
                })
                
    random.shuffle(plan)
    return plan


def run_scraper(query: ParsedQuery) -> None:
    """Run the full scraping pipeline based on the ParsedQuery."""
    config.OUT_DIR.mkdir(exist_ok=True)
    config.RAW_RUNS_DIR.mkdir(exist_ok=True)

    plan = _build_run_plan(query)
    total = len(plan)

    print(f"\n{_ANSI_BOLD}{'═' * 56}{_ANSI_RESET}")
    print(f"{_ANSI_BOLD}  🔍  SCRAPING  │  {total} runs  │  {query.workers} threads{_ANSI_RESET}")
    print(f"{_ANSI_BOLD}{'═' * 56}{_ANSI_RESET}\n")

    script_start = time.time()
    all_dfs: list[pd.DataFrame] = []
    stats = {"ok": 0, "empty": 0, "fail": 0, "total_rows": 0}

    def execute_task(i: int, task: dict):
        try:
            df = scrape_one_run(**{k: task[k] for k in ["search_term", "hours_old", "location", "run_tag", "is_remote", "results_wanted"]})
            rows = len(df)
            if not df.empty:
                all_dfs.append(df)
                stats["ok"] += 1
                stats["total_rows"] += rows
                _tprint(f"  {_ANSI_GREEN}✓{_ANSI_RESET} [{i}/{total}] {task['location']:<20s} │ {rows:>4d} rows │ {task['search_term']}")
            else:
                stats["empty"] += 1
                _tprint(f"  {_ANSI_DIM}·{_ANSI_RESET} [{i}/{total}] {task['location']:<20s} │    0 rows │ {task['search_term']}")
        except Exception as e:
            stats["fail"] += 1
            _tprint(f"  {_ANSI_RED}✗{_ANSI_RESET} [{i}/{total}] {task['location']:<20s} │ ERROR     │ {e}")


    if query.workers <= 1:
        for i, task in enumerate(plan, 1):
            execute_task(i, task)
            time.sleep(config.SLEEP_BETWEEN_RUNS_SEC)
    else:
        with ThreadPoolExecutor(max_workers=query.workers) as pool:
            futures = {}
            for task in plan:
                f = pool.submit(execute_task, len(futures) + 1, task)
                futures[f] = task
            for future in as_completed(futures):
                pass # all printing is handled inside execute_task

    elapsed = time.time() - script_start

    if not all_dfs:
        print(f"\n{_ANSI_YELLOW}  ⚠  No results found. Try broader keywords or longer time window.{_ANSI_RESET}\n")
        return

    all_dfs = [df for df in all_dfs if len(df) > 0]
    merged = pd.concat(all_dfs, ignore_index=True)
    merged = merged[merged["description"].apply(has_nonempty_description)].copy()
    merged = dedupe_jobs(merged)

    config.JOBS_CSV.parent.mkdir(exist_ok=True)
    merged.to_csv(config.JOBS_CSV, index=False)

    print(f"\n{_ANSI_BOLD}{'─' * 56}{_ANSI_RESET}")
    print(f"  {_ANSI_GREEN}✓{_ANSI_RESET} With results: {stats['ok']}  │  {_ANSI_DIM}Empty: {stats['empty']}{_ANSI_RESET}  │  {_ANSI_RED if stats['fail'] else _ANSI_DIM}Failed: {stats['fail']}{_ANSI_RESET}")
    print(f"  {_ANSI_CYAN}📄{_ANSI_RESET} Raw rows: {stats['total_rows']}  →  After dedup: {_ANSI_BOLD}{len(merged)}{_ANSI_RESET}")
    print(f"  {_ANSI_CYAN}💾{_ANSI_RESET} Saved: {config.JOBS_CSV}")
    print(f"  {_ANSI_CYAN}⏱ {_ANSI_RESET} Time: {elapsed:.1f}s ({elapsed / 60:.1f} min)")
    print(f"{_ANSI_BOLD}{'─' * 56}{_ANSI_RESET}\n")
