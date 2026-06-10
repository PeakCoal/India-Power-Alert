"""
Endpoint discovery — loads gc-map-dashboard and clicks all region tabs.
Run: python3 discover_endpoints.py
"""

import json
import asyncio
from playwright.async_api import async_playwright

TARGET_URL = "https://npp.gov.in/dashBoard/gc-map-dashboard"

GENERATION_KEYWORDS = [
    "generation", "demand", "solar", "wind", "hydro", "nuclear",
    "thermal", "mw", "mu", "renewable", "region", "state"
]

async def discover():
    captured = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        async def handle_response(response):
            url = response.url
            if url in captured:
                return
            if any(ext in url for ext in [".js", ".css", ".png", ".jpg", ".ico", ".woff"]):
                return
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    body = await response.text()
                    if any(kw in body.lower() for kw in GENERATION_KEYWORDS):
                        captured[url] = {
                            "url": url,
                            "status": response.status,
                            "body_preview": body[:500],
                        }
            except Exception:
                pass

        page.on("response", handle_response)

        print(f"Loading: {TARGET_URL}")
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=45000)
        await asyncio.sleep(4)
        print("Page loaded. Inspecting all clickable elements...\n")

        # Print ALL links and buttons so we can see what's there
        elements = await page.query_selector_all("a, button, li, [onclick], [data-region], [data-id]")
        print(f"Found {len(elements)} clickable elements. Trying each...\n")

        for el in elements:
            try:
                text = (await el.inner_text()).strip()
                if not text or len(text) > 50:
                    continue
                if any(kw in text.lower() for kw in
                       ["northern", "western", "southern", "eastern", "north east",
                        "ner", "nr", "wr", "sr", "er", "region", "zone", "state",
                        "thermal", "hydro", "nuclear", "all india"]):
                    print(f"  Clicking: '{text}'")
                    await el.click()
                    await asyncio.sleep(2)
            except Exception:
                pass

        await asyncio.sleep(3)
        await browser.close()

    print(f"\n{'='*60}")
    print(f"Found {len(captured)} endpoints:\n")
    for i, item in enumerate(captured.values(), 1):
        print(f"[{i}] {item['url']}")
        print(f"    Status: {item['status']}")
        print(f"    Preview: {item['body_preview'][:300]}")
        print()

if __name__ == "__main__":
    asyncio.run(discover())
