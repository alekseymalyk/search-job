import requests
headers = {"User-Agent": "Mozilla/5.0"}
sites = {
    "ingamejob": "https://ingamejob.com/en/jobs?search=3d+artist",
    "hitmarker": "https://hitmarker.net/jobs?keyword=3d+artist",
    "gamejobs": "https://gamejobs.work/search?q=3d+artist"
}
for name, url in sites.items():
    try:
        r = requests.get(url, headers=headers)
        with open(f"scratch/{name}_sample.html", "w") as f:
            f.write(r.text)
        print(f"Saved {name}")
    except:
        print(f"Failed {name}")
