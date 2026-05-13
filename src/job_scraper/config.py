"""
Central configuration for the Job Scraper pipeline.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── API / Scraper Constants ──
SITES: list[str] = ["linkedin", "indeed", "glassdoor", "zip_recruiter"]
COUNTRY_INDEED: str = "Netherlands"

SLEEP_BETWEEN_RUNS_SEC: int = 6
MAX_DESC_CHARS: int | None = None

# ── Paths ──
OUT_DIR       = PROJECT_ROOT / "output"
RAW_RUNS_DIR  = OUT_DIR / "runs_raw"
JOBS_CSV      = OUT_DIR / "jobs.csv"
FINAL_CSV     = OUT_DIR / "jobs_final.csv"

SPONSORS_CSV  = PROJECT_ROOT / "visa_sponsors.csv"
APPLIED_FILE  = PROJECT_ROOT / "submitted_applications.csv"

# ── Processing Settings ──
SPONSOR_MATCH_THRESHOLD: float = 0.70
TOP_N_FOR_LLM: int = 1000

# ── Valid Jobspy Countries ──
VALID_JOBSPY_COUNTRIES = {
    "argentina", "australia", "austria", "bahrain", "bangladesh", "belgium", 
    "bulgaria", "brazil", "canada", "chile", "china", "colombia", "costa rica", 
    "croatia", "cyprus", "czech republic", "czechia", "denmark", "ecuador", 
    "egypt", "estonia", "finland", "france", "germany", "greece", "hong kong", 
    "hungary", "india", "indonesia", "ireland", "israel", "italy", "japan", 
    "kuwait", "latvia", "lithuania", "luxembourg", "malaysia", "malta", "mexico", 
    "morocco", "netherlands", "new zealand", "nigeria", "norway", "oman", 
    "pakistan", "panama", "peru", "philippines", "poland", "portugal", "qatar", 
    "romania", "saudi arabia", "singapore", "slovakia", "slovenia", "south africa", 
    "south korea", "spain", "sweden", "switzerland", "taiwan", "thailand", 
    "türkiye", "turkey", "ukraine", "united arab emirates", "uk", "united kingdom", 
    "usa", "us", "united states", "uruguay", "venezuela", "vietnam", "worldwide"
}
