import logging
from jobspy import scrape_jobs

logging.basicConfig(level=logging.INFO)

jobs = scrape_jobs(
    site_name=["indeed"],
    search_term="3D artist",
    location="Poland",
    results_wanted=5,
    country_indeed="poland",
    is_remote=True
)

print("Jobs found:", len(jobs))
if not jobs.empty:
    print(jobs[['site', 'title', 'company']].head())
