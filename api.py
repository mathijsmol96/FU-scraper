# api.py
from fastapi import FastAPI, Query
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

app = FastAPI(title="Funda Scraper API")

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True}

async def fetch_html(url: str, wait_selector: Optional[str] = None) -> str:
    """
    Laadt een pagina met Playwright en geeft de HTML terug.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            if wait_selector:
                await page.wait_for_selector(wait_selector, timeout=15_000)
            html = await page.content()
            return html
        finally:
            await context.close()
            await browser.close()

@app.get("/scrape")
async def scrape(
    url: str = Query("https://example.com", description="De pagina die je wilt ophalen"),
    wait_selector: Optional[str] = Query(None, description="Optioneel: CSS selector om op te wachten"),
) -> Dict[str, Any]:
    """
    Haalt de pagina op en geeft eenvoudige JSON terug (titel + eerste 50 links).
    """
    try:
        html = await fetch_html(url, wait_selector)
        soup = BeautifulSoup(html, "html.parser")

        title = (soup.title.string.strip() if soup.title and soup.title.string else None)
        links: List[Dict[str, Optional[str]]] = []
        for a in soup.select("a[href]"):
            href = a.get("href")
            text = a.get_text(strip=True) or None
            links.append({"href": href, "text": text})

        return {
            "ok": True,
            "url": url,
            "title": title,
            "link_count": len(links),
            "links": links[:50],
        }

    except PlaywrightTimeoutError as e:
        return {"ok": False, "error": "timeout", "detail": str(e), "url": url}
    except Exception as e:
        # <<< HIER zit het verschil: 'Exception' + dubbele punt, en netjes JSON teruggeven
        return {"ok": False, "error": "unexpected", "detail": str(e), "url": url}
