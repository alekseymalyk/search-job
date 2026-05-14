"""
Central configuration for the Job Scraper pipeline.
"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── API / Scraper Constants ──
SITES: list[str] = ["linkedin", "indeed"]
COUNTRY_INDEED: str = "Netherlands"

SLEEP_BETWEEN_RUNS_SEC: int = 6
MAX_DESC_CHARS: int | None = None

# ── Paths ──
OUT_DIR       = PROJECT_ROOT / "output"
RAW_RUNS_DIR  = OUT_DIR / "runs_raw"
JOBS_CSV      = OUT_DIR / "jobs.csv"
FINAL_CSV     = OUT_DIR / "jobs_final.csv"
CONFIG_JSON   = PROJECT_ROOT / "scraper_config.json"

SPONSORS_CSV  = PROJECT_ROOT / "visa_sponsors.csv"
APPLIED_FILE  = PROJECT_ROOT / "submitted_applications.csv"

# ── Processing Settings ──
SPONSOR_MATCH_THRESHOLD: float = 0.70
TOP_N_FOR_LLM: int = 1000

# Load custom config if exists
_custom_config = {}
if CONFIG_JSON.exists():
    try:
        with open(CONFIG_JSON, "r", encoding="utf-8") as f:
            _custom_config = json.load(f)
    except Exception as e:
        print(f"Error loading {CONFIG_JSON}: {e}")

# ── AI Settings ──
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", _custom_config.get("openai_api_key", ""))
OPENAI_MODEL: str = _custom_config.get("openai_model", "gpt-4o-mini")
ENABLE_AI_ENRICHMENT: bool = _custom_config.get("enable_ai_enrichment", True)
ENABLE_AI_QUERY_PARSING: bool = _custom_config.get("enable_ai_query_parsing", True)
AI_MAX_JOBS: int = _custom_config.get("ai_max_jobs", 30)

# ── Heuristic Scoring Boosts ──
TITLE_BOOSTS: dict[str, float] = _custom_config.get("title_boosts", {
    "analyst": 1.5,
    "operations": 1.0,
    "operational": 1.0,
    "implementation": 1.0,
    "onboarding": 1.0,
    "account": 0.75,
    "commercial": 0.5,
    "sales": 0.5
})

DESC_BOOSTS: dict[str, float] = _custom_config.get("desc_boosts", {
    "€": 0.5,
    "eur": 0.5,
    "salary": 0.5
})


# ── Blocklists & Patterns ──
REQUIRE_NONEMPTY_DESCRIPTION = _custom_config.get("require_nonempty_description", True)

DESC_BLOCK_PATTERNS = _custom_config.get("desc_block_patterns", [
    "traineeship", "internship", "bedrijf", "vergelijkbare", "leuk", "afgeronde",
    "ontwikkeling", "bieden", "minimaal", "houdt", "ontdekken", "voorbereid",
    "ben j", "aufgaben", "werken", "zakelijk", "EU citizenship",
    "für", "jij", "Tu es", "Une",
    "Dutch and English", "English and Dutch",
])

TITLE_BLOCK_PATTERNS = _custom_config.get("title_block_patterns", [
    "intern", "internship", "trainee", "traineeship",
    "part-time", "part time"
])

LOCATION_BLOCK_PATTERNS = _custom_config.get("location_block_patterns", ["germany"])

LOW_SKILL_TITLE_PATTERNS = _custom_config.get("low_skill_title_patterns", [
    "barista", "waiter", "waitress", "server", "hospitality",
    "kitchen", "cook", "chef", "dishwasher",
    "retail", "cashier", "shop assistant", "store assistant",
    "cleaner", "cleaning", "housekeeping", "janitor",
    "security guard", "security officer",
    "courier", "delivery driver", "driver", "chauffeur",
    "warehouse", "order picker", "picker", "packer", "loader", "unloader",
    "forklift", "heftruck",
])

NON_BUSINESS_PATTERNS = _custom_config.get("non_business_patterns", [
    "electrical engineer", "mechanical engineer", "civil engineer",
    "structural engineer", "chemical engineer", "process engineer",
    "manufacturing engineer", "industrial engineer", "field engineer",
    "electrician", "mechanic", "technician",
    "maintenance", "installer", "construction", "carpenter", "plumber",
    "welder", "machinist", "operator", "cnc",
    "nurse", "nursing", "doctor", "physician", "clinical", "pharmac",
    "dentist", "therapist", "radiology", "midwife", "caregiver",
    "teacher", "lecturer", "professor",
    "lawyer", "attorney", "jurist", "notary",
    "offshore", "drilling", "maritime", "seafarer", "shipyard", "vessel",
])

ALL_BLOCK_LISTS = [LOW_SKILL_TITLE_PATTERNS, NON_BUSINESS_PATTERNS]

TECH_WORDS = _custom_config.get("tech_words", [
    "python", "java", "c++", "c#", "javascript", "typescript", "react", "angular", "vue", "node",
    "aws", "azure", "docker", "kubernetes", "sql", "blender", "maya", "zbrush", "unreal", "unity",
    "figma", "photoshop", "illustrator", "substance", "houdini", "cinema4d", "linux", "git", "agile", "scrum"
])

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
