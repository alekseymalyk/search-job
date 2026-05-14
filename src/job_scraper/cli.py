"""
CLI entry point for the Job Scraper pipeline.
"""

import argparse
import sys
import traceback
import logging
import warnings
from urllib3.exceptions import InsecureRequestWarning

# Early warning suppression
warnings.filterwarnings("ignore", category=InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message="The `dict` method is deprecated")
warnings.filterwarnings("ignore", message="This package (`duckduckgo_search`) has been renamed")
logging.captureWarnings(True)

from job_scraper import __version__, config
from job_scraper.scraper import run_scraper
from job_scraper.processing import process_jobs
from job_scraper.query_parser import parse_query, ParsedQuery


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
        default=3,
        help="Number of concurrent threads (default: 3)",
    )
    p.add_argument(
        "text",
        nargs="*",
        help="Natural language query or subcommand (scrape/filter/ui/all)",
    )

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    text = " ".join(args.text).strip() if args.text else ""

    subcommands = {"scrape", "filter", "all", "ui"}
    if text.lower() in subcommands:
        command = text.lower()
        nl_query = None
    elif args.query:
        command = "all"
        nl_query = args.query
    elif text:
        command = "all"
        nl_query = text
    else:
        command = "all"
        nl_query = None

    if nl_query:
        parsed = parse_query(nl_query)
        parsed.workers = args.workers
        G = "\033[92m"; C = "\033[96m"; D = "\033[90m"; B = "\033[1m"; R = "\033[0m"
        print(f"\n{B}{'─' * 50}{R}")
        print(f"  {C}🧠 PARSED QUERY{R}")
        print(f"{B}{'─' * 50}{R}")
        print(f"  🎯 Title:    {B}{parsed.job_title or '(default)'}{R}")
        print(f"  📊 Results:  {parsed.count}")
        print(f"  🏠 Remote:   {G + '✓ Yes' + R if parsed.remote else D + '✗ No' + R}")
        print(f"  🌍 Locations: {', '.join(parsed.locations[:5]) + (f' +{len(parsed.locations)-5} more' if len(parsed.locations) > 5 else '') if parsed.locations else D + 'default' + R}")
        print(f"  📅 Max age:  {parsed.max_age_hours}h ({parsed.max_age_hours // 24}d)")
        print(f"  ⚡ Workers:  {parsed.workers}")
        print(f"{B}{'─' * 50}{R}")
    else:
        parsed = ParsedQuery(workers=args.workers)

    if command == "ui":
        _start_ui()
    elif command == "scrape":
        _step_scrape(parsed)
    elif command == "filter":
        _step_filter(parsed)
    elif command == "all":
        _run_all(parsed)
    else:
        parser.print_help()
        sys.exit(1)


def _step_scrape(parsed: ParsedQuery) -> None:
    try:
        run_scraper(parsed)
    except Exception as e:
        print(f"\033[91m  ✗ Scraper failed: {e}\033[0m")
        traceback.print_exc()
        sys.exit(1)


def _step_filter(parsed: ParsedQuery) -> None:
    try:
        process_jobs(parsed)
    except Exception as e:
        print(f"\033[91m  ✗ Filter/Processing failed: {e}\033[0m")
        traceback.print_exc()
        sys.exit(1)


def _run_all(parsed: ParsedQuery) -> None:
    B = "\033[1m"; G = "\033[92m"; C = "\033[96m"; R = "\033[0m"
    print(f"\n{B}{'═' * 50}{R}")
    print(f"  {C}🔍 JOB SCRAPER PIPELINE{R}")
    print(f"{B}{'═' * 50}{R}")
    
    _step_scrape(parsed)
    _step_filter(parsed)
    
    print(f"\n{B}{'═' * 50}{R}")
    print(f"  {G}✓ PIPELINE COMPLETED{R}")
    print(f"  {C}📄{R} Results: {config.FINAL_CSV}")
    print(f"{B}{'═' * 50}{R}")


def _start_ui() -> None:
    from job_scraper.web import start_ui
    start_ui()
