import logging
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    from duckduckgo_search import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False
    logger.warning("duckduckgo_search not installed. Search-based fallback will be disabled.")

def _get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

def scrape_ingamejob(query: str, location: str = "") -> pd.DataFrame:
    """Direct scraper for InGameJob.com"""
    search_url = f"https://ingamejob.com/en/jobs?search={query.replace(' ', '+')}"
    jobs = []
    try:
        resp = requests.get(search_url, headers=_get_headers(), timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = soup.select('.listing-job-info')
            for item in items:
                title_tag = item.select_one('h5 a')
                company_tag = item.select_one('strong')
                if title_tag:
                    jobs.append({
                        "company": company_tag.text.strip() if company_tag else "Unknown",
                        "position": title_tag.text.strip(),
                        "location": location or "Global/Remote",
                        "url": title_tag['href'] if title_tag['href'].startswith('http') else f"https://ingamejob.com{title_tag['href']}",
                        "description": "",
                        "source": "ingamejob"
                    })
    except Exception as e:
        logger.warning(f"InGameJob direct scrape failed: {e}")
    
    if not jobs:
        return scrape_via_search_engine("ingamejob.com", query, location)
    return pd.DataFrame(jobs)

def scrape_hitmarker(query: str, location: str = "") -> pd.DataFrame:
    """Direct scraper for Hitmarker.net"""
    search_url = f"https://hitmarker.net/jobs?keyword={query.replace(' ', '+')}"
    jobs = []
    try:
        resp = requests.get(search_url, headers=_get_headers(), timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                if '/jobs/' in href and len(href.split('/')) > 2:
                    title = link.text.strip()
                    if title and len(title) > 5 and not any(x in title.lower() for x in ['sign in', 'cookie', 'privacy']):
                        jobs.append({
                            "company": "Hitmarker Employer",
                            "position": title,
                            "location": location or "Remote",
                            "url": href if href.startswith('http') else f"https://hitmarker.net{href}",
                            "description": "",
                            "source": "hitmarker"
                        })
    except Exception as e:
        logger.warning(f"Hitmarker direct scrape failed: {e}")

    if not jobs:
        return scrape_via_search_engine("hitmarker.net", query, location)
    return pd.DataFrame(jobs)

def scrape_gamejobs(query: str, location: str = "") -> pd.DataFrame:
    """Direct scraper for GameJobs.work"""
    search_url = f"https://gamejobs.work/search?q={query.replace(' ', '+')}"
    jobs = []
    try:
        resp = requests.get(search_url, headers=_get_headers(), timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            cards = soup.select('a[href^="/job/"]')
            for card in cards:
                title = card.select_one('.position')
                company = card.select_one('.company')
                loc = card.select_one('.location')
                if title:
                    jobs.append({
                        "company": company.text.strip() if company else "Unknown",
                        "position": title.text.strip(),
                        "location": loc.text.strip() if loc else "Remote",
                        "url": f"https://gamejobs.work{card['href']}",
                        "description": "",
                        "source": "gamejobs"
                    })
    except Exception as e:
        logger.warning(f"GameJobs direct scrape failed: {e}")
    
    if not jobs:
        return scrape_via_search_engine("gamejobs.work", query, location)
    return pd.DataFrame(jobs)

def scrape_animatedjobs(query: str, location: str = "") -> pd.DataFrame:
    """Direct scraper for AnimatedJobs.com"""
    search_url = f"https://animatedjobs.com/?s={query.replace(' ', '+')}"
    jobs = []
    try:
        resp = requests.get(search_url, headers=_get_headers(), timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            posts = soup.select('article, .job_listing, .post')
            for post in posts:
                title_link = post.select_one('h1 a, h2 a, h3 a, .entry-title a')
                if title_link:
                    jobs.append({
                        "company": "Animation Studio",
                        "position": title_link.text.strip(),
                        "location": location or "Global",
                        "url": title_link['href'],
                        "description": "",
                        "source": "animatedjobs"
                    })
    except Exception as e:
        logger.warning(f"AnimatedJobs direct scrape failed: {e}")
    
    if not jobs:
        return scrape_via_search_engine("animatedjobs.com", query, location)
    return pd.DataFrame(jobs)

def scrape_via_search_engine(site_domain: str, query: str, location: str = "") -> pd.DataFrame:
    """Universal fallback via DDG"""
    if not HAS_DDG:
        return pd.DataFrame()
        
    search_query = f"site:{site_domain} {query} {location}".strip()
    jobs = []
    try:
        with DDGS() as ddgs:
            results = ddgs.text(search_query, max_results=10)
            if results:
                for r in results:
                    url = r.get('href', '')
                    if site_domain in url and len(url.split('/')) > 3:
                        jobs.append({
                            "company": "External",
                            "position": r.get('title', 'Job Posting'),
                            "location": location or "Remote",
                            "url": url,
                            "description": r.get('body', ''),
                            "source": site_domain
                        })
    except Exception:
        pass
    return pd.DataFrame(jobs)
