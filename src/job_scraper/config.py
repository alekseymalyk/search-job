"""
Central configuration for the Job Scraper pipeline.

All paths are resolved relative to the project root (where pyproject.toml lives).
This means you can run the scraper from any directory.
"""

from pathlib import Path
from typing import Optional


# ===========================================================
#  PROJECT ROOT  —  auto-detected from this file's location
# ===========================================================

# src/job_scraper/config.py  →  go up 3 levels to reach project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ===========================================================
#  SCRAPER SETTINGS
# ===========================================================

SITES: list[str] = ["linkedin", "indeed"]
COUNTRY_INDEED: str = "Netherlands"

# Province → biggest city (municipality) mapping
PROVINCE_TO_BIGGEST_CITY: dict[str, str] = {
    "North Brabant": "Eindhoven",
    "North Holland": "Amsterdam",
    "Overijssel":    "Enschede",
    "South Holland": "Rotterdam",
    "Utrecht":       "Utrecht",
}

# Time windows (hours_old) — how far back to search
HOURS_WINDOWS: list[int] = [
    48,         # last 2 days
    24 * 7,     # last 7 days
    24 * 14,    # last 14 days
]

# Search queries — each string is a separate run.
# Modify these for different job searches.
KEYWORD_SPLITS: list[str] = [
    "finance OR fintech OR payments OR banking OR treasury OR pricing OR revenue",
    "operations OR ops OR business operations OR process OR workflow OR execution",
    "sales OR commercial OR account OR customer OR client OR partnerships OR growth",
    "marketing OR brand OR campaign OR go-to-market OR gtm OR acquisition",
    "supply chain OR logistics OR procurement OR sourcing OR demand planning",
    "business OR strategy OR planning OR insights OR analytics",
    "product OR implementation OR onboarding OR rollout OR delivery",
]

RESULTS_WANTED_PER_RUN: int = 3000
SLEEP_BETWEEN_RUNS_SEC: int = 6
MAX_DESC_CHARS: Optional[int] = None

# Threading — number of concurrent scraping threads (1 = sequential)
MAX_WORKERS: int = 3


# ===========================================================
#  PATHS  —  all relative to PROJECT_ROOT
# ===========================================================

OUT_DIR       = PROJECT_ROOT / "output"
RAW_RUNS_DIR  = OUT_DIR / "runs_raw"
JOBS_CSV      = OUT_DIR / "jobs.csv"

STAGE1_OUT    = OUT_DIR / "jobs_stage1.csv"
STAGE2_OUT    = OUT_DIR / "jobs_final.csv"


# ===========================================================
#  FILTER SETTINGS
# ===========================================================

SPONSORS_CSV  = PROJECT_ROOT / "visa_sponsors.csv"
APPLIED_FILE  = PROJECT_ROOT / "submitted_applications.csv"

SPONSOR_MATCH_THRESHOLD: float = 0.70
TOP_N_FOR_LLM: int = 1000
