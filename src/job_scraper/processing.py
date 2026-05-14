"""
Job processing and filtering.

Applies blocklists, cleans data, matches visa sponsors, 
and ranks jobs by relevance.
"""

import re
from collections import Counter
from rapidfuzz import fuzz
from pathlib import Path

import pandas as pd

from job_scraper import config
from job_scraper.query_parser import ParsedQuery
from job_scraper.ai_enrichment import enrich_jobs_dataframe

# ── Constants from config are used directly ──

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

# Precompile regexes
RE_COMPANY_NORM = re.compile(r"[&/_,\-\.\(\)\[\]\{\}\|:+]")
RE_TITLE_NORM_1 = re.compile(r"\(.*?\)")
RE_TITLE_NORM_2 = re.compile(r"\b(m\/f\/d|m\/v\/x|m\/f|f\/m|jr\.?|junior|associate|entry[-\s]?level)\b")
RE_TITLE_NORM_3 = re.compile(r"[^a-z0-9\s]")
RE_TOKENIZE_1 = re.compile(r"[^a-z0-9\s]")
RE_SPACES = re.compile(r"\s+")

def normalize_company(name: str) -> str:
    s = RE_COMPANY_NORM.sub(" ", str(name).lower())
    s = RE_SPACES.sub(" ", s).strip()
    return " ".join(t for t in s.split() if t not in LEGAL_STOPWORDS and len(t) > 1)

def normalize_title(title: str) -> str:
    t = RE_TITLE_NORM_1.sub(" ", str(title).lower())
    t = RE_TITLE_NORM_2.sub(" ", t)
    return RE_SPACES.sub(" ", RE_TITLE_NORM_3.sub(" ", t)).strip()

def seq_ratio(a: str, b: str) -> float:
    return fuzz.ratio(a or "", b or "") / 100.0

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
    t = RE_SPACES.sub(" ", RE_TOKENIZE_1.sub(" ", str(text).lower())).strip()
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

def process_jobs(parsed: ParsedQuery = None, task_id: str = None) -> None:
    """Main function that filters and ranks jobs."""
    import logging
    from job_scraper.logger import get_task_logger
    logger = get_task_logger(task_id) if task_id else logging.getLogger(__name__)

    # Default columns to write if empty
    empty_cols = ["company", "position", "location", "url", "description", "source"]

    if not config.JOBS_CSV.exists():
        logger.info(f"Missing input: {config.JOBS_CSV}")
        pd.DataFrame(columns=empty_cols).to_csv(config.FINAL_CSV, index=False)
        return

    try:
        jobs = pd.read_csv(config.JOBS_CSV)
    except pd.errors.EmptyDataError:
        logger.info("Jobs CSV has no columns to parse. Skipping processing.")
        pd.DataFrame(columns=empty_cols).to_csv(config.FINAL_CSV, index=False)
        return

    if jobs.empty:
        logger.info("Jobs CSV is empty. Skipping processing.")
        pd.DataFrame(columns=empty_cols).to_csv(config.FINAL_CSV, index=False)
        return

    # Normalize basic columns to prevent KeyError
    for col in ["position", "description", "location", "company", "url"]:
        if col not in jobs.columns:
            jobs[col] = ""
    jobs["position"] = jobs["position"].fillna("").astype(str)
    jobs["description"] = jobs["description"].fillna("").astype(str)
    jobs["location"] = jobs["location"].fillna("").astype(str)
    jobs["company"] = jobs["company"].fillna("").astype(str)

    # 1. Hard Reject Filter
    logger.info("  ▸ Stage: Filtering & Sponsor check...")
    
    sponsor_map = {}  # {normalized_name: raw_name}
    if Path(config.SPONSORS_CSV).exists():
        try:
            sponsors = pd.read_csv(config.SPONSORS_CSV)
            raw_names = sponsors.iloc[:, 0].dropna().astype(str).tolist()
            sponsor_map = {
                normalize_company(name): name
                for name in raw_names
                if name and name.lower() != "nan"
            }
        except pd.errors.EmptyDataError:
            pass

    # Pre-compile filters for vectorization where possible
    def contains_any_re(patterns):
        if not patterns: return None
        escaped = [re.escape(p) for p in patterns]
        # Use non-capturing group (?:...) to avoid pandas UserWarning
        return re.compile("(?i)(?:" + "|".join(escaped) + ")")

    title_block_re = contains_any_re(config.TITLE_BLOCK_PATTERNS)
    all_block_lists_re = [contains_any_re(p) for p in config.ALL_BLOCK_LISTS if p]
    loc_block_re = contains_any_re(config.LOCATION_BLOCK_PATTERNS)
    desc_block_re = contains_any_re(config.DESC_BLOCK_PATTERNS)

    reject_counts = Counter()

    # Vectorized fast filters
    mask_keep = pd.Series(True, index=jobs.index)
    
    if config.REQUIRE_NONEMPTY_DESCRIPTION:
        empty_mask = jobs["description"].str.strip() == ""
        reject_counts["desc_empty"] += empty_mask.sum()
        mask_keep &= ~empty_mask

    if title_block_re:
        tb_mask = jobs["position"].str.contains(title_block_re.pattern, regex=True, flags=re.IGNORECASE)
        reject_counts["title_block"] += tb_mask.sum()
        mask_keep &= ~tb_mask

    for abl_re in all_block_lists_re:
        if abl_re:
            abl_mask = jobs["position"].str.contains(abl_re.pattern, regex=True, flags=re.IGNORECASE)
            reject_counts["title_non_business"] += abl_mask.sum()
            mask_keep &= ~abl_mask

    if loc_block_re:
        lb_mask = jobs["location"].str.contains(loc_block_re.pattern, regex=True, flags=re.IGNORECASE)
        reject_counts["location_block"] += lb_mask.sum()
        mask_keep &= ~lb_mask

    if desc_block_re:
        db_mask = jobs["description"].str.contains(desc_block_re.pattern, regex=True, flags=re.IGNORECASE)
        reject_counts["desc_block"] += db_mask.sum()
        mask_keep &= ~db_mask

    # Strict title/remote filters
    if parsed and parsed.job_title:
        expected_tokens = set(tokenize(parsed.job_title))
        if expected_tokens:
            def match_title(title):
                return bool(expected_tokens & set(tokenize(title)))
            title_match_mask = jobs["position"].apply(match_title)
            reject_counts["irrelevant_title"] += (~title_match_mask).sum()
            mask_keep &= title_match_mask

    if parsed and parsed.remote:
        not_remote_mask = (
            jobs["location"].str.lower().str.contains(r"on-site|onsite|hybrid", regex=True) |
            jobs["position"].str.lower().str.contains(r"on-site|hybrid", regex=True)
        )
        reject_counts["not_remote"] += not_remote_mask.sum()
        mask_keep &= ~not_remote_mask

    # Experience Level check
    is_junior_search = False
    if parsed and parsed.job_title:
        jt_low = parsed.job_title.lower()
        if "junior" in jt_low or "jr" in jt_low or "entry" in jt_low:
            is_junior_search = True
            
    if is_junior_search:
        exp_mask = jobs["description"].apply(requires_2plus_years)
        reject_counts["exp_too_high"] += exp_mask.sum()
        mask_keep &= ~exp_mask

    # Apply fast filters
    df = jobs[mask_keep].copy()

    # Apply slow filters (sponsor match & scoring) only on remaining
    if not df.empty:
        def process_row(row):
            comp = str(row["company"])
            title_l = str(row["position"]).lower()
            desc_l = str(row["description"]).lower()
            
            sp_name, sp_score = best_match_company(comp, sponsor_map) if sponsor_map else ("", 1.0)
            
            score = sp_score * 10.0
            for keyword, boost in config.TITLE_BOOSTS.items():
                if keyword in title_l:
                    score += boost
            for keyword, boost in config.DESC_BOOSTS.items():
                if keyword in desc_l:
                    score += boost
                    
            return pd.Series({
                "sponsor_match": sp_name,
                "sponsor_score": round(sp_score, 3),
                "rank_score": round(score, 2)
            })

        new_cols = df.apply(process_row, axis=1)
        df = pd.concat([df, new_cols], axis=1)
        
        if sponsor_map:
            sponsor_miss_mask = df["sponsor_score"] < config.SPONSOR_MATCH_THRESHOLD
            reject_counts["sponsor_miss"] += sponsor_miss_mask.sum()
            df = df[~sponsor_miss_mask].copy()

    logger.info("Rejections:")
    for reason, count in reject_counts.most_common():
        if count > 0:
            logger.info(f"  {reason}: {count}")

    if df.empty:
        pd.DataFrame().to_csv(config.FINAL_CSV, index=False)
        logger.info(f"Saved 0 jobs to {config.FINAL_CSV}")
        return

    # 2. Ranking against applied history
    logger.info("  ▸ Stage: Ranking against history...")
    if Path(config.APPLIED_FILE).exists():
        applied = pd.read_csv(config.APPLIED_FILE)
        a_comp_col = _find_col(applied, ["Company", "company", "Employer"])
        a_pos_col = _find_col(applied, ["Position", "position", "Title", "Job Title"])
        a_desc_col = _find_col(applied, ["Description", "description", "Job Description"])

        applied_map = {
            normalize_company(r): r
            for r in applied[a_comp_col].dropna().astype(str).str.strip()
            if r and r.lower() != "nan"
        }
        applied_titles = applied[a_pos_col].dropna().astype(str).map(normalize_title).tolist()
        kw_profile = build_keyword_profile(applied[a_desc_col], top_k=300)

        # Batch scoring
        df["applied_company_match"] = ""
        df["applied_company_score"] = 0.0
        df["applied_company_boost"] = 0.0
        df["applied_title_similarity"] = 0.0
        df["applied_title_boost"] = 0.0
        df["applied_keyword_overlap"] = 0.0
        df["applied_keyword_boost"] = 0.0
        df["final_rank_score"] = df["rank_score"]

        # Only process if we actually have history
        if applied_map or applied_titles or kw_profile:
            def score_row(row):
                comp, pos, desc = str(row["company"]), str(row["position"]), str(row["description"])
                m_name, m_score = best_match_company(comp, applied_map) if applied_map else ("", 0.0)
                c_boost = W_COMPANY * (1.0 if m_score >= 0.9 else 0.66 if m_score >= 0.8 else 0.33 if m_score >= 0.7 else 0.0)

                ts = best_title_similarity(pos, applied_titles) if applied_titles else 0.0
                t_boost = W_TITLE * (1.0 if ts >= 0.9 else 0.66 if ts >= 0.8 else 0.33 if ts >= 0.7 else 0.0)

                ko = keyword_overlap_score(desc, kw_profile) if kw_profile else 0.0
                k_boost = W_KEYWORDS * (1.0 if ko >= 0.08 else 0.66 if ko >= 0.05 else 0.33 if ko >= 0.03 else 0.0)

                return pd.Series({
                    "applied_company_match": m_name,
                    "applied_company_score": round(m_score, 3),
                    "applied_company_boost": round(c_boost, 2),
                    "applied_title_similarity": round(ts, 3),
                    "applied_title_boost": round(t_boost, 2),
                    "applied_keyword_overlap": round(ko, 4),
                    "applied_keyword_boost": round(k_boost, 2),
                    "final_rank_score": round(row["rank_score"] + c_boost + t_boost + k_boost, 2)
                })

            updates = df.apply(score_row, axis=1)
            df.update(updates)
    else:
        df["final_rank_score"] = df["rank_score"]

    df = df.sort_values("final_rank_score", ascending=False)
    
    limit = parsed.count if (parsed and parsed.count > 0) else 5000
    df = df.head(limit)

    # 3. AI Enrichment (Process only top N to save tokens/time)
    if config.ENABLE_AI_ENRICHMENT and config.OPENAI_API_KEY:
        logger.info(f"  ▸ Stage: AI Enrichment for top {min(len(df), config.AI_MAX_JOBS)} jobs...")
        top_df = df.head(config.AI_MAX_JOBS).copy()
        bottom_df = df.iloc[config.AI_MAX_JOBS:].copy()
        
        top_df = enrich_jobs_dataframe(top_df, logger)
        df = pd.concat([top_df, bottom_df], ignore_index=True)

    config.FINAL_CSV.parent.mkdir(exist_ok=True)
    df.to_csv(config.FINAL_CSV, index=False)
    logger.info(f"Saved: {config.FINAL_CSV} (rows: {len(df)})")
