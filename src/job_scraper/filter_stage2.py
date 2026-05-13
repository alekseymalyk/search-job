"""
Stage 3: Rank jobs by similarity to previously submitted applications.

Reads jobs_stage1.csv + submitted_applications.csv →
compares companies, titles, keywords → outputs final ranked CSV.
"""

import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from job_scraper import config

# Ranking weights
W_COMPANY = 6.0
W_TITLE = 4.0
W_KEYWORDS = 2.0

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


def normalize_company(name: str) -> str:
    s = re.sub(r"[&/_,\-\.\(\)\[\]\{\}\|:+]", " ", str(name).lower()).strip()
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
    return [w for w in t.split() if len(w) >= 3 and w not in STOPWORDS]


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


def _find_col(df: pd.DataFrame, options: list[str]) -> str:
    for o in options:
        if o in df.columns:
            return o
    return df.columns[0]


def run_stage2() -> None:
    """Rank jobs by similarity to submitted applications."""
    if not config.STAGE1_OUT.exists():
        print(f"Missing Stage 1 file: {config.STAGE1_OUT}")
        return
    if not Path(config.APPLIED_FILE).exists():
        print(f"WARNING: {config.APPLIED_FILE} not found. Using Stage 1 results as final.")
        pd.read_csv(config.STAGE1_OUT).to_csv(config.STAGE2_OUT, index=False)
        return

    jobs = pd.read_csv(config.STAGE1_OUT)
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
    for _, r in jobs.iterrows():
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

    df = pd.DataFrame(results).sort_values("final_rank_score", ascending=False)
    if config.TOP_N_FOR_LLM:
        df = df.head(config.TOP_N_FOR_LLM)
    df.to_csv(config.STAGE2_OUT, index=False)
    print(f"Saved: {config.STAGE2_OUT} (rows: {len(df)})")
