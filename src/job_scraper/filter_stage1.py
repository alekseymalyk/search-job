"""
Stage 2: Hard-reject filtering + visa sponsor matching.

Reads jobs.csv → applies blocklists, experience checks, sponsor matching →
outputs a ranked CSV (jobs_stage1.csv).
"""

import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from job_scraper import config

# ───────────────── blocklists ─────────────────

REQUIRE_NONEMPTY_DESCRIPTION = True

DESC_BLOCK_PATTERNS = [
    "traineeship", "internship", "bedrijf", "vergelijkbare", "leuk", "afgeronde",
    "ontwikkeling", "bieden", "minimaal", "houdt", "ontdekken", "voorbereid",
    "ben j", "aufgaben", "werken", "zakelijk", "EU citizenship",
    "inimum 3", "inimum 4", "inimum 5", "inimum 6", "inimum 7", "inimum 8",
    "für", "jij", "Tu es", "3-5", "Une", "-10", "5+",
    "Dutch and English", "English and Dutch",
]

TITLE_BLOCK_PATTERNS = [
    "intern", "internship", "trainee", "traineeship",
    "part-time", "part time", "für", "senior", "medior",
]

LOCATION_BLOCK_PATTERNS = ["germany"]

LOW_SKILL_TITLE_PATTERNS = [
    "barista", "waiter", "waitress", "server", "hospitality",
    "kitchen", "cook", "chef", "dishwasher",
    "retail", "cashier", "shop assistant", "store assistant",
    "cleaner", "cleaning", "housekeeping", "janitor",
    "security guard", "security officer",
    "courier", "delivery driver", "driver", "chauffeur",
    "warehouse", "order picker", "picker", "packer", "loader", "unloader",
    "forklift", "heftruck",
]

NON_BUSINESS_PATTERNS = [
    "engineer", "engineering", "electrician", "mechanic", "technician",
    "maintenance", "installer", "construction", "carpenter", "plumber",
    "welder", "machinist", "operator", "cnc",
    "nurse", "nursing", "doctor", "physician", "clinical", "pharmac",
    "dentist", "therapist", "radiology", "midwife", "caregiver",
    "teacher", "lecturer", "professor",
    "lawyer", "attorney", "jurist", "notary",
    "offshore", "drilling", "maritime", "seafarer", "shipyard", "vessel",
]

ALL_BLOCK_LISTS = [LOW_SKILL_TITLE_PATTERNS, NON_BUSINESS_PATTERNS]

EXP_REQUIRED_PATTERNS = [
    re.compile(r"\b(minimum|min\.|at\s+least|atleast|a\s+minimum\s+of)\s*(\d{1,2})\s*(\+|plus)?\s*(years?|yrs?|jaar)\b", re.I),
    re.compile(r"\b(\d{1,2})\s*(\+|plus)\s*(years?|yrs?|jaar)\b", re.I),
    re.compile(r"\b(\d{1,2})\s*(years?|yrs?|jaar)\b.{0,30}\bexperience\b", re.I),
    re.compile(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(years?|yrs?|jaar)\b", re.I),
]

LEGAL_STOPWORDS = {
    "bv", "b.v", "b.v.", "nv", "n.v", "n.v.", "ltd", "limited", "inc",
    "corp", "corporation", "llc", "plc", "gmbh", "ag", "sa", "s.a", "s.a.",
    "holding", "holdings", "group", "company", "co", "co.", "the",
    "netherlands", "nederland", "nl",
}


# ───────────────── helpers ─────────────────

def requires_2plus_years(description: str) -> bool:
    d = str(description)
    for rx in EXP_REQUIRED_PATTERNS:
        for m in rx.finditer(d):
            if m.lastindex and m.lastindex >= 2:
                try:
                    nums = [int(x) for x in re.findall(r"\d{1,2}", m.group(0))]
                    if nums and min(nums) >= 2:
                        return True
                except Exception:
                    continue
    return False


def normalize_company(name: str) -> str:
    s = re.sub(r"[&/_,\-\.\(\)\[\]\{\}\|:+]", " ", str(name).lower())
    s = re.sub(r"\s+", " ", s).strip()
    return " ".join(t for t in s.split() if t not in LEGAL_STOPWORDS and len(t) > 1)


def seq_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a or "", b or "").ratio()


def token_overlap(a: str, b: str) -> float:
    ta, tb = set((a or "").split()), set((b or "").split())
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


def best_sponsor_match(company: str, sponsors_raw: list[str]) -> tuple[str, float]:
    c = normalize_company(company)
    best_score, best_name = 0.0, ""
    for s_raw in sponsors_raw:
        s = normalize_company(s_raw)
        if not c or not s:
            continue
        score = 0.999 if (c in s or s in c) else max(seq_ratio(c, s), token_overlap(c, s))
        if score > best_score:
            best_score, best_name = score, s_raw
    return best_name, best_score


def contains_any(patterns: list[str], text: str) -> bool:
    t = str(text).lower()
    return any(p.lower() in t for p in patterns)


def is_nonempty(desc: str) -> bool:
    s = str(desc or "").strip()
    return bool(s and s.lower() not in {"nan", "none", "null"})


def normalize_text_key(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", str(s or "").lower()).strip()
    return re.sub(r"\s+", " ", s)


# ───────────────── main logic ─────────────────

def run_stage1() -> None:
    """Apply hard-reject filters and sponsor matching."""
    if not config.JOBS_CSV.exists():
        print(f"Missing input: {config.JOBS_CSV}")
        return

    jobs = pd.read_csv(config.JOBS_CSV)

    if not Path(config.SPONSORS_CSV).exists():
        print(f"WARNING: {config.SPONSORS_CSV} not found. Sponsor matching skipped.")
        sponsor_names: list[str] = []
    else:
        sponsors = pd.read_csv(config.SPONSORS_CSV)
        sponsor_names = sponsors.iloc[:, 0].dropna().astype(str).tolist()

    kept: list[dict] = []
    reject_counts: Counter = Counter()

    for _, row in jobs.iterrows():
        title, desc, loc, comp, url = [
            str(row.get(c, "")) for c in ["position", "description", "location", "company", "url"]
        ]

        if REQUIRE_NONEMPTY_DESCRIPTION and not is_nonempty(desc):
            reject_counts["desc_empty"] += 1; continue
        if contains_any(TITLE_BLOCK_PATTERNS, title):
            reject_counts["title_block"] += 1; continue
        if any(contains_any(p, title) for p in ALL_BLOCK_LISTS):
            reject_counts["title_non_business"] += 1; continue
        if contains_any(LOCATION_BLOCK_PATTERNS, loc):
            reject_counts["location_block"] += 1; continue
        if contains_any(DESC_BLOCK_PATTERNS, desc):
            reject_counts["desc_block"] += 1; continue
        if requires_2plus_years(desc):
            reject_counts["exp_2plus"] += 1; continue

        sp_name, sp_score = best_sponsor_match(comp, sponsor_names) if sponsor_names else ("", 1.0)
        if sp_score < config.SPONSOR_MATCH_THRESHOLD:
            reject_counts["sponsor_miss"] += 1; continue

        score = sp_score * 10.0
        t, d = title.lower(), desc.lower()
        if "analyst" in t: score += 1.5
        if "operations" in t or "operational" in t: score += 1.0
        if "implementation" in t or "onboarding" in t: score += 1.0
        if "account" in t: score += 0.75
        if any(x in t for x in ["commercial", "sales"]): score += 0.5
        if any(x in d for x in ["€", "eur", "salary"]): score += 0.5

        kept.append({
            "company": comp, "position": title, "location": loc,
            "url": url, "description": desc,
            "sponsor_match": sp_name, "sponsor_score": round(sp_score, 3),
            "rank_score": round(score, 2),
        })

    print(f"\nStage 1 rejections:")
    for reason, count in reject_counts.most_common():
        print(f"  {reason}: {count}")

    if not kept:
        pd.DataFrame().to_csv(config.STAGE1_OUT, index=False)
        print(f"Saved 0 jobs to {config.STAGE1_OUT}")
        return

    df = pd.DataFrame(kept)
    df["company_key"] = df["company"].map(normalize_company)
    df["title_key"] = df["position"].map(normalize_text_key)
    df["loc_key"] = df["location"].map(normalize_text_key)
    df["__has_url"] = df["url"].astype(str).str.strip().ne("").astype(int)
    df["__desc_len"] = df["description"].astype(str).str.len()
    df["dedupe_key"] = df["company_key"] + "||" + df["title_key"] + "||" + df["loc_key"]

    df = (df.sort_values(by=["rank_score", "__has_url", "__desc_len"], ascending=[False, False, False])
            .drop_duplicates(subset=["dedupe_key"], keep="first"))
    df = (df.drop(columns=["company_key", "title_key", "loc_key", "dedupe_key", "__has_url", "__desc_len"])
            .sort_values("rank_score", ascending=False))

    config.STAGE1_OUT.parent.mkdir(exist_ok=True)
    df.to_csv(config.STAGE1_OUT, index=False)
    print(f"Saved {len(df)} jobs → {config.STAGE1_OUT}")
