import requests
from bs4 import BeautifulSoup
import re

r = requests.get("https://hitmarker.net/jobs", headers={"User-Agent": "Mozilla/5.0"})
soup = BeautifulSoup(r.text, 'html.parser')
for a in soup.find_all('a', href=lambda h: h and h.startswith('https://hitmarker.net/jobs/')):
    print(a['href'])
    print(a.get_text(separator=' | ', strip=True))

print("=====================")
r2 = requests.get("https://ingamejob.com/en/jobs", headers={"User-Agent": "Mozilla/5.0"})
soup2 = BeautifulSoup(r2.text, 'html.parser')
for a in soup2.find_all('a', href=lambda h: h and '/en/job/' in h):
    print(a['href'])
    print(a.get_text(separator=' | ', strip=True))

