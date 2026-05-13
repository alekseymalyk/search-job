"""
Stage 1: Scrape jobs from LinkedIn & Indeed (multi-threaded).

Iterates over locations × time windows × keyword splits, runs them in parallel
via ThreadPoolExecutor, saves raw CSVs, then merges + deduplicates into jobs.csv.
"""

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import List, Tuple

import pandas as pd
from jobspy import scrape_jobs

from job_scraper import config

_print_lock = Lock()


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
    # Track which target names are already taken (in original columns OR pending renames)
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

    # Safety: drop any duplicate columns that slipped through
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


# ───────────────────────── single run ─────────────────────────

def scrape_one_run(
    search_term: str,
    hours_old: int,
    location: str,
    run_tag: str,
    is_remote: bool = False,
    results_wanted: int | None = None,
) -> pd.DataFrame:
    _tprint(f"\n--- RUN {run_tag} ---")
    _tprint(f"  Location: {location} | Max age: {hours_old}h | Remote: {is_remote}")
    _tprint(f"  Query: {search_term}")

    run_start = time.time()

    kwargs = dict(
        site_name=config.SITES,
        search_term=search_term,
        location=location,
        hours_old=hours_old,
        results_wanted=results_wanted or config.RESULTS_WANTED_PER_RUN,
        linkedin_fetch_description=True,
        verbose=2,
    )
    if is_remote:
        kwargs["is_remote"] = True
    if not is_remote:
        kwargs["country_indeed"] = config.COUNTRY_INDEED

    df = scrape_jobs(**kwargs)
    run_duration = time.time() - run_start

    if df is None or len(df) == 0:
        _tprint(f"  [{run_tag}] 0 rows")
        return pd.DataFrame()

    df = pd.DataFrame(df)
    df = normalize_columns(df)

    df["run_query"] = search_term
    df["run_hours_old"] = hours_old
    df["run_location"] = location
    df["scrape_ts_utc"] = datetime.now(timezone.utc).isoformat()

    out = config.RAW_RUNS_DIR / f"run_{run_tag}.csv"
    df.to_csv(out, index=False)

    try:
        csv_bytes = int(os.path.getsize(out))
    except Exception:
        csv_bytes = 0

    non_empty = df["description"].apply(has_nonempty_description).sum()
    _tprint(f"  [{run_tag}] {len(df)} rows ({non_empty} with desc) | {run_duration:.1f}s | {csv_bytes / 1024:.0f}KB")

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

    plan = _build_run_plan(locations, hours_windows, keywords, is_remote, results_wanted)
    total = len(plan)
    print(f"\nScraping plan: {total} runs, {config.MAX_WORKERS} threads")

    script_start = time.time()
    all_dfs: list[pd.DataFrame] = []

    if config.MAX_WORKERS <= 1:
        # Sequential mode
        for task in plan:
            try:
                df = scrape_one_run(
                    search_term=task["search_term"],
                    hours_old=task["hours_old"],
                    location=task["location"],
                    run_tag=task["run_tag"],
                    is_remote=task["is_remote"],
                    results_wanted=task["results_wanted"],
                )
                if not df.empty:
                    all_dfs.append(df)
            except Exception as e:
                _tprint(f"  Run failed ({task['run_tag']}): {e}")
            time.sleep(config.SLEEP_BETWEEN_RUNS_SEC)
    else:
        # Multi-threaded mode
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
            futures = {}
            for task in plan:
                f = pool.submit(
                    scrape_one_run,
                    search_term=task["search_term"],
                    hours_old=task["hours_old"],
                    location=task["location"],
                    run_tag=task["run_tag"],
                    is_remote=task["is_remote"],
                    results_wanted=task["results_wanted"],
                )
                futures[f] = task["run_tag"]

            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                tag = futures[future]
                try:
                    df = future.result()
                    if not df.empty:
                        all_dfs.append(df)
                    _tprint(f"  [{done_count}/{total}] {tag} ✓")
                except Exception as e:
                    _tprint(f"  [{done_count}/{total}] {tag} ✗ {e}")

    if not all_dfs:
        print("All runs returned 0 results")
        return

    merged = pd.concat(all_dfs, ignore_index=True)
    merged = merged[merged["description"].apply(has_nonempty_description)].copy()
    merged = dedupe_jobs(merged)

    config.JOBS_CSV.parent.mkdir(exist_ok=True)
    merged.to_csv(config.JOBS_CSV, index=False)

    elapsed = time.time() - script_start
    print(f"\nSaved {len(merged)} jobs → {config.JOBS_CSV}")
    print(f"Total time: {elapsed / 60:.1f} min")
