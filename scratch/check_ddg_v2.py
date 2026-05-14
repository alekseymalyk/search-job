from duckduckgo_search import DDGS
import logging

# Some versions need this
logging.basicConfig(level=logging.INFO)

with DDGS() as ddgs:
    results = ddgs.text("python", max_results=5)
    print(f"Results type: {type(results)}")
    res_list = list(results)
    print(f"Results count: {len(res_list)}")
    for r in res_list:
        print(f"- {r.get('title')}")
