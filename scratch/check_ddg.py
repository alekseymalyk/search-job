from duckduckgo_search import DDGS
with DDGS() as ddgs:
    results = ddgs.text("python", max_results=5)
    print(f"Results: {len(list(results))}")
    for r in results:
        print(r['title'])
