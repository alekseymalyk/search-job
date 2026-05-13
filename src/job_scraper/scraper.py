"""
Stage 1: Scrape jobs from LinkedIn & Indeed (multi-threaded).

Iterates over locations × time windows × keyword splits, runs them in parallel
via ThreadPoolExecutor, saves raw CSVs, then merges + deduplicates into jobs.csv.
"""

import logging
import os
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

import pandas as pd
from jobspy import scrape_jobs

from job_scraper import config

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


def _tprint(*args, **kwargs):
    """Thread-safe print."""
    with _print_lock:
        print(*args, **kwargs)


# ───────────────────────── helpers ─────────────────────────

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
    keywords = [title]

    # Split compound titles: "3D hard-surface artist" → also try "3D artist"
    words = title.split()
    if len(words) >= 3:
        # Try first + last word
        short = f"{words[0]} {words[-1]}"
        if short.lower() != title.lower():
            keywords.append(short)

    # Common synonyms for broader matching
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


# ───────────────────────── single run ─────────────────────────

def scrape_one_run(
    search_term: str,
    hours_old: int,
    location: str,
    run_tag: str,
    is_remote: bool = False,
    results_wanted: int | None = None,
) -> pd.DataFrame:
    run_start = time.time()

    kwargs = dict(
        site_name=config.SITES,
        search_term=search_term,
        location=location,
        hours_old=hours_old,
        results_wanted=results_wanted or config.RESULTS_WANTED_PER_RUN,
        linkedin_fetch_description=True,
        verbose=0,
    )
    if is_remote:
        kwargs["is_remote"] = True
    if not is_remote:
        kwargs["country_indeed"] = config.COUNTRY_INDEED

    df = scrape_jobs(**kwargs)
    run_duration = time.time() - run_start

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


# ───────────────────────── orchestrator ─────────────────────────

def _build_run_plan(
    locations: list[str] | None = None,
    hours_windows: list[int] | None = None,
    keywords: list[str] | None = None,
    is_remote: bool = False,
    results_wanted: int | None = None,
) -> list[dict]:
    """Build a list of scraping runs."""
    locs = locations or [
        f"{city}, {config.COUNTRY_INDEED}"
        for city in config.PROVINCE_TO_BIGGEST_CITY.values()
    ]
    hours_list = hours_windows or config.HOURS_WINDOWS
    kw_list = keywords or config.KEYWORD_SPLITS

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
                    "is_remote": is_remote,
                    "results_wanted": results_wanted,
                })
    return plan


def run_scraper(
    locations: list[str] | None = None,
    hours_windows: list[int] | None = None,
    keywords: list[str] | None = None,
    is_remote: bool = False,
    results_wanted: int | None = None,
) -> None:
    """Run the full scraping pipeline, optionally multi-threaded."""
    config.OUT_DIR.mkdir(exist_ok=True)
    config.RAW_RUNS_DIR.mkdir(exist_ok=True)

    # Expand keywords for better coverage
    if keywords:
        expanded = []
        for kw in keywords:
            expanded.extend(expand_keywords(kw))
        # Deduplicate while preserving order
        seen = set()
        keywords = []
        for kw in expanded:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                keywords.append(kw)

    plan = _build_run_plan(locations, hours_windows, keywords, is_remote, results_wanted)
    total = len(plan)

    print(f"\n{_ANSI_BOLD}{'═' * 56}{_ANSI_RESET}")
    print(f"{_ANSI_BOLD}  🔍  SCRAPING  │  {total} runs  │  {config.MAX_WORKERS} threads{_ANSI_RESET}")
    if keywords:
        print(f"{_ANSI_DIM}  Keywords: {', '.join(keywords)}{_ANSI_RESET}")
    print(f"{_ANSI_BOLD}{'═' * 56}{_ANSI_RESET}\n")

    script_start = time.time()
    all_dfs: list[pd.DataFrame] = []
    stats = {"ok": 0, "empty": 0, "fail": 0, "total_rows": 0}

    if config.MAX_WORKERS <= 1:
        for i, task in enumerate(plan, 1):
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
            time.sleep(config.SLEEP_BETWEEN_RUNS_SEC)
    else:
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
            futures = {}
            for task in plan:
                f = pool.submit(
                    scrape_one_run,
                    **{k: task[k] for k in ["search_term", "hours_old", "location", "run_tag", "is_remote", "results_wanted"]},
                )
                futures[f] = task

            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                task = futures[future]
                try:
                    df = future.result()
                    rows = len(df)
                    if not df.empty:
                        all_dfs.append(df)
                        stats["ok"] += 1
                        stats["total_rows"] += rows
                        _tprint(f"  {_ANSI_GREEN}✓{_ANSI_RESET} [{done_count}/{total}] {task['location']:<20s} │ {rows:>4d} rows │ {task['search_term']}")
                    else:
                        stats["empty"] += 1
                        _tprint(f"  {_ANSI_DIM}·{_ANSI_RESET} [{done_count}/{total}] {task['location']:<20s} │    0 rows │ {task['search_term']}")
                except Exception as e:
                    stats["fail"] += 1
                    _tprint(f"  {_ANSI_RED}✗{_ANSI_RESET} [{done_count}/{total}] {task['location']:<20s} │ ERROR     │ {e}")

    elapsed = time.time() - script_start

    if not all_dfs:
        print(f"\n{_ANSI_YELLOW}  ⚠  No results found. Try broader keywords or longer time window.{_ANSI_RESET}\n")
        return

    # Filter out truly empty DFs before concat
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
