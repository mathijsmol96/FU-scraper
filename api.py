from fastapi import FastAPI
import asyncio
from bs4 import BeautifulSoup

app = FastAPI()

@app.get("/")
def root():
    return {"service": "funda-scraper-api", "endpoints": ["/health", "/scrape"]}

@app.get("/health")
def health():
    return {"ok": True}

def _has_all(classes, req):
    if not classes:
        return False
    setc = set(classes)
    return all(r in setc for r in req)

async def _scrape_with_playwright(max_pages: int = 10):
    from playwright.async_api import async_playwright

    base_url = 'https://www.funda.nl/zoeken/koop?selected_area=["nl"]&publication_date="1"&availability=["available"]'
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()

        # Cookie scherm wegklikken
        await page.goto("https://www.funda.nl", wait_until="domcontentloaded")
        try:
            await page.click("#didomi-notice-agree-button", timeout=5000)
        except:
            pass

        for page_number in range(1, max_pages + 1):
            url = f"{base_url}&search_result={page_number}" if page_number > 1 else base_url
            await page.goto(url, wait_until="networkidle")

            # Wachten tot er minimaal een listing zichtbaar is
            try:
                await page.wait_for_selector('a[data-testid="listingDetailsAddress"]', timeout=10000)
            except:
                break

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Robuuste selectie: vind containers met kaart-classes
            cards = []
            for div in soup.find_all("div"):
                classes = div.get("class", [])
                if _has_all(classes, {"border-b", "pb-3"}):
                    # Heet vaak '@container border-b pb-3', volgorde kan wisselen
                    cards.append(div)

            if not cards:
                # fallback: op basis van anchor zelf
                anchors = soup.select('a[data-testid="listingDetailsAddress"]')
                cards = [a.parent.parent if a and a.parent else a for a in anchors]  # best-effort

            for card in cards:
                try:
                    data = {}

                    address_element = card.find('a', attrs={'data-testid': 'listingDetailsAddress'})
                    if address_element and address_element.get('href'):
                        data['link'] = 'https://www.funda.nl' + address_element['href']
                        street_address_div = address_element.find('div', class_='flex font-semibold')
                        data['adres'] = street_address_div.get_text(strip=True, separator=' ') if street_address_div else 'N/A'
                    else:
                        continue  # zonder link geen listing

                    location_div = card.find('div', class_='truncate text-neutral-80')
                    data['stad_dorp'] = location_div.get_text(strip=True) if location_div else 'N/A'

                    price_element = card.find('p', attrs={'data-testid': 'result-item-price'})
                    data['prijs'] = price_element.get_text(strip=True) if price_element else 'N/A'

                    realtor_container = card.find('div', class_='flex w-full justify-between')
                    if realtor_container:
                        realtor_link = realtor_container.find('a')
                        data['makelaar'] = realtor_link.find('span').get_text(strip=True) if realtor_link and realtor_link.find('span') else 'N/A'
                    else:
                        data['makelaar'] = 'N/A'

                    results.append(data)
                except Exception:
                    continue

        await context.close()
        await browser.close()

    return results

@app.get("/scrape")
async def scrape(max_pages: int = 10):
    try:
        items = await _scrape_with_playwright(max_pages=max_pages)
        return {"status": "success", "count": len(items), "data": items}
    except Exception as e:
        return {"status": "error", "message": str(e)}
