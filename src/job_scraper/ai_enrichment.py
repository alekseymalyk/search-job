"""
AI Enrichment module.
Uses OpenAI to extract structured data (TL;DR, experience, visa, remote) from job descriptions.
"""
import logging
import pandas as pd
from pydantic import BaseModel, Field

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from job_scraper import config

class JobEnrichment(BaseModel):
    tldr: str = Field(description="1-2 sentences summarizing the role, core tech stack, and key highlights (e.g. 'Remote backend role focusing on FastApi')")
    min_experience_years: int | None = Field(description="Minimum years of experience required. null if not specified.")
    visa_sponsorship: bool | None = Field(description="True if the company explicitly mentions visa sponsorship or relocation assistance. False if explicitly denied. null if not mentioned.")
    is_remote: bool = Field(description="True if the job is fully remote.")

def enrich_jobs_dataframe(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    if not OpenAI or not config.OPENAI_API_KEY:
        logger.warning("OpenAI library not installed or OPENAI_API_KEY is missing. Skipping AI enrichment.")
        return df

    if df.empty:
        return df

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    
    # Initialize new columns
    df["ai_tldr"] = ""
    df["ai_min_experience_years"] = pd.NA
    df["ai_visa_sponsorship"] = pd.NA
    df["ai_is_remote"] = pd.NA
    
    try:
        from tqdm import tqdm
        tqdm.pandas(desc="AI Processing")
        _has_tqdm = True
    except ImportError:
        _has_tqdm = False
    
    def process_description(row):
        title = row.get("position", "")
        desc = row.get("description", "")
        if not desc or len(str(desc).strip()) < 50:
            return pd.Series({"ai_tldr": "", "ai_min_experience_years": None, "ai_visa_sponsorship": None, "ai_is_remote": False})
            
        prompt = f"Analyze the following job post for the position of '{title}'. Extract the requested information.\n\nDescription:\n{str(desc)[:5000]}"
        
        try:
            response = client.beta.chat.completions.parse(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are an expert technical recruiter analyzing job descriptions."},
                    {"role": "user", "content": prompt}
                ],
                response_format=JobEnrichment,
                temperature=0.0
            )
            parsed = response.choices[0].message.parsed
            return pd.Series({
                "ai_tldr": parsed.tldr,
                "ai_min_experience_years": parsed.min_experience_years,
                "ai_visa_sponsorship": parsed.visa_sponsorship,
                "ai_is_remote": parsed.is_remote
            })
        except Exception as e:
            logger.error(f"Failed to process AI for '{title}': {e}")
            return pd.Series({"ai_tldr": "", "ai_min_experience_years": None, "ai_visa_sponsorship": None, "ai_is_remote": None})

    logger.info(f"Running OpenAI {config.OPENAI_MODEL} on {len(df)} jobs...")
    
    # Apply processing row by row (tqdm gives a progress bar if available)
    if _has_tqdm:
        ai_results = df.progress_apply(process_description, axis=1)
    else:
        ai_results = df.apply(process_description, axis=1)
    
    # Update dataframe
    for col in ai_results.columns:
        df[col] = ai_results[col]
        
    return df
