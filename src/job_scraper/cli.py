"""
CLI entry point for the Job Scraper pipeline.

Usage:
    job-scraper                                         # full pipeline (default config)
    job-scraper scrape                                  # scrape only
    job-scraper filter                                  # filter stage 1 only
    job-scraper rank                                    # filter stage 2 only
    job-scraper -q "3D artist remote"                   # short keyword query
    job-scraper "знайди мені 100 компаній які шукають   # natural language query
                 3D hard-surface artist, remote, ЄС"
"""

import argparse
import sys
import traceback

from job_scraper import __version__, config
from job_scraper.scraper import run_scraper
from job_scraper.filter_stage1 import run_stage1
from job_scraper.filter_stage2 import run_stage2
from job_scraper.query_parser import parse_query


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="job-scraper",
        description="Scrape jobs from LinkedIn/Indeed → Filter → Rank → Export CSV",
        epilog=(
            "Natural language example:\n"
            '  job-scraper "знайди 100 компаній, 3D artist, remote, ЄС+США, 2 тижні"\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "-V", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    p.add_argument(
        "-q", "--query",
        type=str,
        default=None,
        help="Short keyword query (e.g. '3D artist remote')",
    )
    p.add_argument(
        "-w", "--workers",
        type=int,
        default=None,
        help=f"Number of concurrent threads (default: {config.MAX_WORKERS})",
    )
    p.add_argument(
        "text",
        nargs="*",
        help="Natural language query or subcommand (scrape/filter/rank/ui/all)",
    )

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Apply thread count override
    if args.workers:
        config.MAX_WORKERS = args.workers

    # Join positional args
    text = " ".join(args.text).strip() if args.text else ""

    # Check if it's a subcommand
    subcommands = {"scrape", "filter", "rank", "all", "ui"}
    if text.lower() in subcommands:
        command = text.lower()
        nl_query = None
    elif args.query:
        # Short query mode: -q "3D artist"
        command = "all"
        nl_query = args.query
    elif text:
        # Natural language mode: everything is the query
        command = "all"
        nl_query = text
    else:
        command = "all"
        nl_query = None

    # Parse natural language query if provided
    if nl_query:
        parsed = parse_query(nl_query)
        print("=" * 50)
        print("  PARSED QUERY")
        print("=" * 50)
        print(parsed.summary())
        print("=" * 50)

        # Apply parsed parameters to config / scraper args
        if parsed.job_title:
            config.KEYWORD_SPLITS = [parsed.job_title]
        if parsed.max_age_hours:
            config.HOURS_WINDOWS = [parsed.max_age_hours]
        if parsed.count:
            config.RESULTS_WANTED_PER_RUN = parsed.count

        # Store parsed data for scraper
        _scraper_kwargs = {
            "is_remote": parsed.remote,
            "locations": parsed.locations or None,
            "hours_windows": [parsed.max_age_hours] if parsed.max_age_hours else None,
            "keywords": [parsed.job_title] if parsed.job_title else None,
            "results_wanted": parsed.count,
        }
    else:
        _scraper_kwargs = {}

    # Execute
    if command == "ui":
        _start_ui()
    elif command == "scrape":
        _step_scrape(**_scraper_kwargs)
    elif command == "filter":
        _step_filter()
    elif command == "rank":
        _step_rank()
    elif command == "all":
        _run_all(**_scraper_kwargs)
    else:
        parser.print_help()
        sys.exit(1)


def _step_scrape(**kwargs) -> None:
    print("\n[STEP 1] Scraping jobs...")
    try:
        run_scraper(**kwargs)
    except Exception as e:
        print(f"Scraper failed: {e}")
        traceback.print_exc()
        sys.exit(1)


def _step_filter() -> None:
    print("\n[STEP 2] Filtering (hard rejects + sponsor matching)...")
    try:
        run_stage1()
    except Exception as e:
        print(f"Filter Stage 1 failed: {e}")
        traceback.print_exc()
        sys.exit(1)


def _step_rank() -> None:
    print("\n[STEP 3] Ranking (applied jobs similarity)...")
    try:
        run_stage2()
    except Exception as e:
        print(f"Ranking Stage 2 failed: {e}")
        traceback.print_exc()
        sys.exit(1)


def _run_all(**kwargs) -> None:
    print("=" * 50)
    print("  JOB SCRAPER PIPELINE")
    print("=" * 50)
    _step_scrape(**kwargs)
    _step_filter()
    _step_rank()
    print("\n" + "=" * 50)
    print("  PIPELINE COMPLETED")
    print(f"  Results: {config.STAGE2_OUT}")
    print("=" * 50)


def _start_ui() -> None:
    from job_scraper.web import start_ui
    start_ui()
