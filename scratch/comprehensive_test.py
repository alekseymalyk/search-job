import sys
import os
import pandas as pd
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from job_scraper.custom_scrapers import (
    scrape_hitmarker, scrape_ingamejob, scrape_gamejobs, scrape_animatedjobs
)
from job_scraper.scraper import scrape_one_run
from job_scraper.query_parser import ParsedQuery

def test_custom_scrapers():
    print("=== Testing Custom Scrapers (Search Based) ===")
    queries = ["3D Artist", "Game Designer", "Unity Developer"]
    sites = {
        "hitmarker": scrape_hitmarker,
        "ingamejob": scrape_ingamejob,
        "gamejobs": scrape_gamejobs,
        "animatedjobs": scrape_animatedjobs
    }
    
    for name, func in sites.items():
        print(f"\nTesting {name}...")
        try:
            df = func("Unity Developer", "USA")
            if not df.empty:
                print(f"  [OK] Found {len(df)} results")
                print(f"  [OK] Columns: {df.columns.tolist()}")
                print(f"  [OK] Sample: {df['position'].iloc[0][:50]} @ {df['source'].iloc[0]}")
            else:
                print(f"  [??] No results found (could be search indexing delay)")
        except Exception as e:
            print(f"  [FAIL] Error: {e}")

def test_jobspy_integration():
    print("\n=== Testing JobSpy Integration ===")
    try:
        # We test one run via scrape_one_run which uses jobspy
        df = scrape_one_run(
            search_term="Python Developer",
            hours_old=72,
            location="United Kingdom",
            run_tag="test_run",
            results_wanted=5,
            sites=["linkedin", "indeed"]
        )
        if not df.empty:
            print(f"  [OK] Found {len(df)} results from JobSpy")
            print(f"  [OK] Sources found: {df['source'].unique().tolist()}")
        else:
            print(f"  [??] No results found from JobSpy (possible blocking or empty region)")
    except Exception as e:
        print(f"  [FAIL] JobSpy Error: {e}")

if __name__ == "__main__":
    test_custom_scrapers()
    test_jobspy_integration()
