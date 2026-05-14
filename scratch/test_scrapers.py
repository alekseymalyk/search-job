import requests
from bs4 import BeautifulSoup

def test_site(name, url):
    print(f"Testing {name}: {url}")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {resp.status_code}")
        print(f"Content length: {len(resp.text)}")
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Look for common job board elements
            titles = soup.find_all(['h1', 'h2', 'h3', 'a'])
            print(f"Found {len(titles)} potential title elements")
    except Exception as e:
        print(f"Error: {e}")
    print("-" * 20)

test_site("Hitmarker", "https://hitmarker.net/jobs?keyword=game+designer")
test_site("InGameJob", "https://ingamejob.com/en/jobs?search=game+designer")
test_site("GameJobs.work", "https://gamejobs.work/search?q=game+designer")
