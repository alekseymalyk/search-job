import requests
from bs4 import BeautifulSoup

def check_ingamejob():
    url = "https://ingamejob.com/en/jobs?search=Unity+Developer"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    print(f"Fetching {url}...")
    resp = requests.get(url, headers=headers, timeout=15)
    print(f"Status: {resp.status_code}")
    
    with open("scratch/ingamejob_search_debug.html", "w") as f:
        f.write(resp.text)
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    # Looking for job items. Usually they have a class like 'job-item' or 'vacancy'
    # Based on previous research, let's look for all links containing '/jobs/' but not just the search page
    links = soup.find_all('a', href=True)
    job_links = [l for l in links if '/en/jobs/' in l['href'] and len(l['href'].split('/')) > 4]
    print(f"Found {len(job_links)} potential job links")
    for l in job_links[:5]:
        print(f"- {l.text.strip()}: {l['href']}")

if __name__ == "__main__":
    check_ingamejob()
