import asyncio
from app.tools.scrapers import scrape_all_parallel

query = "iPhone 15"
print(f"Scraping for: {query}")
results = scrape_all_parallel(query)
print(f"Total results: {len(results)}")
for r in results:
    if r.get("error"):
         print(f"Error from {r['site']}: {r['message']}")
    else:
         print(f"{r['site']}: {r['title']} - {r['price']}")
