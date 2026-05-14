import requests
from bs4 import BeautifulSoup

def fetch(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, 'html.parser')
    links = soup.find_all('a', href=True)
    count = 0
    for a in links:
        href = a['href']
        if '/job/' in href or '/jobs/' in href:
            print(href[:50], a.get_text(strip=True)[:50])
            count += 1
            if count > 5: break

print("--- GameJobs ---")
fetch("https://gamejobs.work/")
print("--- AnimatedJobs ---")
fetch("https://animatedjobs.com/")
