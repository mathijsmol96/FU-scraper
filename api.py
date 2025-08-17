from fastapi import FastAPI, Query
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError
from bs4 import BeautifulSoup

app = FastAPI()

@app.get("/")
def root():
    return {"service": "funda-scraper-api", "endpoints": ["/health", "/scrape"]}

@app.get("/health")
async def health():
    return {"ok": True}

SEARCH_URL = (
    "https://www.funda.nl/zoeken/koop"
    "?selected_area=%5B%22nl%22%5D&publication_date=%221%22&availability=%5B%22available%22%5D"
)

async def _scrape_listing_page(page, page_number: int):
    url = f"{SEARCH_URL}&search_result={page_number}" if page_number > 1 else SEARCH_URL
    # ga naar pagina en wacht kort; Render heeft strakke timeouts
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_selector("div[class*='@container']", timeout=15000)
    except PWTimeoutError:
        return []

    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", class_='@container border-b pb-3')

    results = []
    for card in cards:
        data = {}
        address_element = card.find('a', attrs={'data-testid': 'listingDetailsAddress'})
        if address_element:
            data['link'] = 'https://www.funda.nl' + address_element['href']
            street_address_div = address_element.find('div', class_='flex font-semibold')
            data['adres'] = street_address_div.get_text(strip=True, separator=' ') if street_address_div else 'N/A'
        location_div = card.find('div', class_='truncate text-neutral-80')
        data['stad_dorp'] = location_div.get_text(strip=True) if location_div else 'N/A'
        price_element = card.find('p', attrs={'data-testid': 'result-item-price'})
        data['prijs'] = price_element.get_text(strip=True) if price_element else 'N/A'
        realtor_container = card.find('div', class_='flex w-full justify-between')
        if realtor_container:
            realtor_link = realtor_container.find('a')
            data['makelaar'] = realtor_link.find('span').get_text(strip=True) if realtor_link else 'N/A'
        else:
            data['makelaar'] = 'N/A'
        results.append(data)
    return results

@app.get("/scrape")
async def scrape(max_pages: int = Query(3, ge=1, le=10)):
    # Houd het onder ~100s i.v.m. Render time-out
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        try:
            # cookies accepteren (Didomi)
            await page.goto("https://www.funda.nl", wait_until="domcontentloaded", timeout=30000)
            try:
                await page.click("#didomi-notice-agree-button", timeout=8000)
            except PWTimeoutError:
                pass

            items = []
            for n in range(1, max_pages + 1):
                batch = await _scrape_listing_page(page, n)
                if not batch:
                    break
                items.extend(batch)

            return {"status": "success", "count": len(items), "data": items}
        finally:
            await context.close()
            await browser.close()
