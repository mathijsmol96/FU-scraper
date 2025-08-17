# api.py
# FastAPI + jouw Selenium/BS4 scraper, geschikt voor Render

import time
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup

app = FastAPI(
    title="funda-scraper-api",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

BASE_URL = (
    'https://www.funda.nl/zoeken/koop?selected_area=["nl"]'
    '&publication_date="1"&availability=["available"]'
)

# ---------- Selenium driver (belangrijk voor Render) ----------
def _make_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()

    # Headless is noodzakelijk op Render
    if headless:
        # "new" headless werkt stabieler met recente Chrome
        opts.add_argument("--headless=new")

    # Essentieel in containers:
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    # Stabielere rendering/performantie:
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    # Minder ‘bot-achtig’
    opts.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    )
    opts.add_argument("--lang=nl-NL,nl")

    # Verberg automation banner
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(90)   # ruimer in cloud
    return driver


def _safe_get(driver: webdriver.Chrome, url: str, retries: int = 2) -> None:
    """Robuust naar een URL navigeren met 1 retry bij haperen."""
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            driver.get(url)
            return
        except Exception as e:
            last_err = e
            time.sleep(3)
    # als we hier komen: nog steeds fout
    if last_err:
        raise last_err


# ---------- Jouw scraper (identieke selectors/velden) ----------
def scrape_funda_today(max_pages: int = 1, headless: bool = True) -> List[Dict[str, Any]]:
    chrome = _make_driver(headless=headless)
    wait = WebDriverWait(chrome, 15)

    all_properties: List[Dict[str, Any]] = []
    try:
        # Start op de homepage om cookies af te vangen
        _safe_get(chrome, "https://www.funda.nl")

        # Cookie popup accepteren (als aanwezig)
        try:
            btn = wait.until(
                EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button"))
            )
            btn.click()
            time.sleep(1)
        except Exception:
            # Geen cookie pop-up of al geaccepteerd
            pass

        for page_number in range(1, max_pages + 1):
            url = f"{BASE_URL}&search_result={page_number}" if page_number > 1 else BASE_URL

            try:
                _safe_get(chrome, url)

                # Wacht tot resultaten-sectie zichtbaar is
                wait.until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div[class*='@container']"))
                )
                time.sleep(2)  # korte extra rust voor rendering

                html = chrome.page_source
                soup = BeautifulSoup(html, "html.parser")

                cards = soup.find_all("div", class_='@container border-b pb-3')
                if not cards:
                    # Geen kaarten meer -> klaar
                    break

                for card in cards:
                    data: Dict[str, Any] = {}

                    address_element = card.find('a', attrs={'data-testid': 'listingDetailsAddress'})
                    if address_element:
                        data['link'] = 'https://www.funda.nl' + address_element.get('href', '')

                        street_address_div = address_element.find('div', class_='flex font-semibold')
                        data['adres'] = (
                            street_address_div.get_text(strip=True, separator=' ')
                            if street_address_div else 'N/A'
                        )
                    else:
                        data['link'] = ''
                        data['adres'] = 'N/A'

                    location_div = card.find('div', class_='truncate text-neutral-80')
                    data['stad_dorp'] = location_div.get_text(strip=True) if location_div else 'N/A'

                    price_element = card.find('p', attrs={'data-testid': 'result-item-price'})
                    data['prijs'] = price_element.get_text(strip=True) if price_element else 'N/A'

                    # Makelaar (jouw “finale correctie”)
                    realtor_container = card.find('div', class_='flex w-full justify-between')
                    if realtor_container:
                        realtor_link = realtor_container.find('a')
                        data['makelaar'] = (
                            realtor_link.find('span').get_text(strip=True)
                            if realtor_link and realtor_link.find('span') else 'N/A'
                        )
                    else:
                        data['makelaar'] = 'N/A'

                    all_properties.append(data)

            except TimeoutException:
                # Te traag? volgende pagina proberen
                continue

    finally:
        try:
            chrome.quit()
        except Exception:
            pass

    return all_properties


# ---------- FastAPI endpoints ----------
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/scrape")
def scrape(
    pages: int = Query(1, ge=1, le=10, description="Aantal pagina's om te scrapen (1-10)"),
    headless: int = Query(1, description="1=headless (aanbevolen op Render), 0=zichtbaar")
):
    items = scrape_funda_today(max_pages=pages, headless=bool(headless))
    return JSONResponse(
        {
            "ok": True,
            "pages": pages,
            "count": len(items),
            "items": items,
        }
    )
