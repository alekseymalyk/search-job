import requests
from bs4 import BeautifulSoup

def test_gamejobs():
    try:
        r = requests.get("https://gamejobs.work/", headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, 'html.parser')
        jobs = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/job/' in href or 'gamejobs.work' in href:
                title = a.get_text(strip=True)
                if title and len(title) > 5:
                    jobs.append(title)
        print("Gamejobs sample:", jobs[:5])
    except Exception as e:
        print("Gamejobs error:", e)

def test_animated():
    try:
        r = requests.get("https://animatedjobs.com/", headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, 'html.parser')
        jobs = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'job' in href or 'career' in href:
                title = a.get_text(strip=True)
                if title and len(title) > 5:
                    jobs.append(title)
        print("Animated sample:", jobs[:5])
    except Exception as e:
        print("Animated error:", e)

test_gamejobs()
test_animated()
