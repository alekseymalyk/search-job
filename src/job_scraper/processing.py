"""
Job processing and filtering.

Applies blocklists, cleans data, matches visa sponsors, 
and ranks jobs by relevance.
"""

import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from job_scraper import config
from job_scraper.query_parser import ParsedQuery

# ───────────────── BLOCKLISTS & PATTERNS ─────────────────

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

STOPWORDS = {
    "the", "and", "or", "to", "of", "in", "for", "with", "on", "at",
    "as", "by", "from", "an", "a", "is", "are", "be", "been", "being",
    "this", "that", "you", "your", "we", "our", "they", "their", "it",
    "its", "will", "can", "may", "have", "has", "had", "do", "does",
    "not", "no", "if", "also", "more", "most", "some", "any", "about",
    "role", "position", "candidate", "responsible", "requirements",
    "experience", "years", "skills", "knowledge", "strong", "excellent",
    "team", "work", "working", "must", "include", "including",
    "de", "het", "een", "en", "van", "voor", "met", "op", "als", "bij",
}

W_COMPANY = 6.0
W_TITLE = 4.0
W_KEYWORDS = 2.0


# ───────────────── HELPERS ─────────────────

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

def normalize_title(title: str) -> str:
    t = re.sub(r"\(.*?\)", " ", str(title).lower())
    t = re.sub(r"\b(m\/f\/d|m\/v\/x|m\/f|f\/m|jr\.?|junior|associate|entry[-\s]?level)\b", " ", t)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", t)).strip()

def seq_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a or "", b or "").ratio()

def token_overlap(a: str, b: str) -> float:
    ta, tb = set((a or "").split()), set((b or "").split())
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0

def best_match_company(company_raw: str, applied_map: dict) -> tuple[str, float]:
    c = normalize_company(company_raw)
    best_raw, best_score = "", 0.0
    for a_norm, a_raw in applied_map.items():
        if not c or not a_norm:
            continue
        score = 0.999 if (c in a_norm or a_norm in c) else max(seq_ratio(c, a_norm), token_overlap(c, a_norm))
        if score > best_score:
            best_score, best_raw = score, a_raw
    return best_raw, best_score

def tokenize(text: str) -> list[str]:
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", str(text).lower())).strip()
    allowed_short = {"3d", "2d", "ui", "ux", "qa", "ai", "pr"}
    return [w for w in t.split() if (len(w) >= 3 or w in allowed_short) and w not in STOPWORDS]

def build_keyword_profile(desc_series: pd.Series, top_k: int = 300) -> set[str]:
    counter: Counter = Counter()
    for txt in desc_series.dropna().astype(str):
        counter.update(tokenize(txt))
    return {w for w, _ in counter.most_common(top_k)}

def keyword_overlap_score(job_desc: str, profile: set[str]) -> float:
    toks = set(tokenize(job_desc))
    return len(toks & profile) / max(1, len(toks)) if profile and toks else 0.0

def best_title_similarity(job_title: str, applied_titles: list[str]) -> float:
    jt = normalize_title(job_title)
    if not jt or not applied_titles:
        return 0.0
    best = 0.0
    for at in applied_titles:
        if not at:
            continue
        if jt in at or at in jt:
            return 0.999
        best = max(best, seq_ratio(jt, at))
    return best

def contains_any(patterns: list[str], text: str) -> bool:
    t = str(text).lower()
    return any(p.lower() in t for p in patterns)

def is_nonempty(desc: str) -> bool:
    s = str(desc or "").strip()
    return bool(s and s.lower() not in {"nan", "none", "null"})

def _find_col(df: pd.DataFrame, options: list[str]) -> str:
    for o in options:
        if o in df.columns:
            return o
    return df.columns[0]

# ───────────────── PROCESSING PIPELINE ─────────────────

def process_jobs(parsed: ParsedQuery = None) -> None:
    """Main function that filters and ranks jobs."""
    if not config.JOBS_CSV.exists():
        print(f"Missing input: {config.JOBS_CSV}")
        return

    jobs = pd.read_csv(config.JOBS_CSV)

    # 1. Hard Reject Filter
    print(f"\n\033[1m  ▸ Stage: Filtering & Sponsor check...\033[0m")
    
    sponsor_names = []
    if Path(config.SPONSORS_CSV).exists():
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
            
        # Strict job title validation if user specified a title
        if parsed and parsed.job_title:
            expected_tokens = set(tokenize(parsed.job_title))
            title_tokens = set(tokenize(title))
            # At least one important word from the searched title should be in the returned title
            if expected_tokens and not (expected_tokens & title_tokens):
                reject_counts["irrelevant_title"] += 1; continue

        # Strict remote validation
        if parsed and parsed.remote:
            loc_lower = loc.lower()
            desc_lower = desc.lower()
            title_lower = title.lower()
            # Reject if it explicitly says on-site or hybrid in title/location
            if "on-site" in loc_lower or "onsite" in loc_lower or "hybrid" in loc_lower or "on-site" in title_lower or "hybrid" in title_lower:
                reject_counts["not_remote"] += 1; continue

        sp_name, sp_score = best_match_company(comp, sponsor_names) if sponsor_names else ("", 1.0)
        
        # If sponsor matching is strictly needed and score < threshold, reject
        # We assume if SPONSORS_CSV exists, we only want sponsors (like previous stage1 logic).
        if sponsor_names and sp_score < config.SPONSOR_MATCH_THRESHOLD:
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

    print("Rejections:")
    for reason, count in reject_counts.most_common():
        print(f"  {reason}: {count}")

    if not kept:
        pd.DataFrame().to_csv(config.FINAL_CSV, index=False)
        print(f"Saved 0 jobs to {config.FINAL_CSV}")
        return

    df = pd.DataFrame(kept)

    # 2. Ranking against applied history
    print(f"\033[1m  ▸ Stage: Ranking against history...\033[0m")
    if Path(config.APPLIED_FILE).exists():
        applied = pd.read_csv(config.APPLIED_FILE)
        a_comp_col = _find_col(applied, ["Company ", "Company", "company", "Employer"])
        a_pos_col = _find_col(applied, ["Position", "position", "Title", "Job Title"])
        a_desc_col = _find_col(applied, ["Description", "description", "Job Description"])

        applied_map = {
            normalize_company(r): r
            for r in applied[a_comp_col].dropna().astype(str).str.strip()
            if r and r.lower() != "nan"
        }
        applied_titles = applied[a_pos_col].dropna().astype(str).map(normalize_title).tolist()
        kw_profile = build_keyword_profile(applied[a_desc_col], top_k=300)

        results = []
        for _, r in df.iterrows():
            comp, pos, desc = [str(r.get(c, "")) for c in ["company", "position", "description"]]
            base = float(r.get("rank_score", 0) or 0)

            m_name, m_score = best_match_company(comp, applied_map)
            c_boost = W_COMPANY * (1.0 if m_score >= 0.9 else 0.66 if m_score >= 0.8 else 0.33 if m_score >= 0.7 else 0.0)

            ts = best_title_similarity(pos, applied_titles)
            t_boost = W_TITLE * (1.0 if ts >= 0.9 else 0.66 if ts >= 0.8 else 0.33 if ts >= 0.7 else 0.0)

            ko = keyword_overlap_score(desc, kw_profile)
            k_boost = W_KEYWORDS * (1.0 if ko >= 0.08 else 0.66 if ko >= 0.05 else 0.33 if ko >= 0.03 else 0.0)

            r["applied_company_match"] = m_name
            r["applied_company_score"] = round(m_score, 3)
            r["applied_company_boost"] = round(c_boost, 2)
            r["applied_title_similarity"] = round(ts, 3)
            r["applied_title_boost"] = round(t_boost, 2)
            r["applied_keyword_overlap"] = round(ko, 4)
            r["applied_keyword_boost"] = round(k_boost, 2)
            r["final_rank_score"] = round(base + c_boost + t_boost + k_boost, 2)
            results.append(r)
        
        df = pd.DataFrame(results)
    else:
        # If no applied file, final score is just the base rank score
        df["final_rank_score"] = df["rank_score"]

    df = df.sort_values("final_rank_score", ascending=False)
    
    # Slice by requested count (or fallback to a large number like 5000 if not specified)
    limit = parsed.count if (parsed and parsed.count > 0) else 5000
    df = df.head(limit)

    config.FINAL_CSV.parent.mkdir(exist_ok=True)
    df.to_csv(config.FINAL_CSV, index=False)
    print(f"Saved: {config.FINAL_CSV} (rows: {len(df)})")
