# api.py — FastAPI + Selenium scraper voor Funda (vandaag geplaatst)

import os
import glob
import site
import time
from typing import List, Dict, Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup


app = FastAPI(title="funda-scraper-api",
              description="Scrapet alle vandaag geplaatste koopwoningen op Funda",
              version="1.1.0")


# --- vind Playwright's Chromium (die we tijdens build installeren) ---
def _find_playwright_chrome_binary() -> str | None:
    for sp in site.getsitepackages():
        base = os.path.join(sp, "playwright", "driver", "package", ".local-browsers")
        for pat in ("chromium-*",):
            candidate = glob.glob(os.path.join(base, pat, "chrome-linux", "chrome"))
            if candidate:
                return candidate[0]
    return None


# --- maak Selenium driver met 'menselijke' settings ---
def _make_driver(headless: bool = True) -> webdriver.Chrome:
    chrome_binary = _find_playwright_chrome_binary()
    proxy = os.getenv("PROXY_URL") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")

    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    )

    options = Options()
    if chrome_binary and os.path.exists(chrome_binary):
        options.binary_location = chrome_binary

    # cloud-friendly
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,768")
    options.add_argument("--lang=nl-NL,nl")
    options.add_argument("--disable-blink-features=AutomationControlled")
    if headless:
        options.add_argument("--headless=new")
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")

    # minder “automation”-sporen
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)

    # Echte headers + navigator tweaks via CDP
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {"userAgent": UA, "platform": "Windows"}
        )
        driver.execute_cdp_cmd(
            "Network.setExtraHTTPHeaders",
            {
                "headers": {
                    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7"
                }
            },
        )
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['nl-NL','nl']});
                """
            },
        )
    except Exception:
        # CDP kan soms mislukken; dan gaan we gewoon verder
        pass

    return driver


def scrape_funda_today(max_pages: int = 10, headless: bool = True) -> Dict[str, Any]:
    base_url = (
        "https://www.funda.nl/zoeken/koop"
        "?selected_area=[%22nl%22]"
        "&publication_date=%221%22"
        "&availability=[%22available%22]"
    )

    all_properties: List[Dict[str, Any]] = []
    driver = _make_driver(headless=headless)
    wait = WebDriverWait(driver, 20)
    blocked = False
    debug_title = ""
    debug_url = ""

    try:
        # 1) cookies op hoofddomein proberen
        driver.get("https://www.funda.nl")
        try:
            btn = wait.until(EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button")))
            btn.click()
            time.sleep(1)
        except Exception:
            print("Geen cookie pop-up gevonden (of al geaccepteerd).")

        # 2) pagina's lopen
        for page_number in range(1, max_pages + 1):
            url = f"{base_url}&search_result={page_number}" if page_number > 1 else base_url
            driver.get(url)
            time.sleep(1.5)

            debug_title = driver.title
            debug_url = driver.current_url

            # check of we op een 'bijna op de pagina' / challenge pagina zitten
            if "bijna op de pagina" in debug_title.lower() or "helpdesk@funda.nl" in driver.page_source:
                blocked = True
                break

            try:
                # wacht tot listings zichtbaar zijn
                wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[data-testid='listingDetailsAddress'], p[data-testid='result-item-price']")
                    )
                )
            except Exception:
                # niets gevonden => waarschijnlijk geblokkeerd of leeg
                break

            soup = BeautifulSoup(driver.page_source, "html.parser")
            cards = soup.find_all("div", class_='@container border-b pb-3')
            if not cards:
                # fallback: soms andere markup -> pak anchors op data-testid
                anchors = soup.select("a[data-testid='listingDetailsAddress']")
                if not anchors:
                    break
                # maak synthetische 'cards' uit anchors
                cards = [a.parent.parent if a.parent else a for a in anchors]

            for card in cards:
                data: Dict[str, Any] = {}

                address_a = card.find('a', attrs={'data-testid': 'listingDetailsAddress'})
                if address_a and address_a.get('href'):
                    data['link'] = 'https://www.funda.nl' + address_a['href']
                    street_div = address_a.find('div', class_='flex font-semibold')
                    data['adres'] = street_div.get_text(strip=True, separator=' ') if street_div else 'N/A'
                else:
                    data['link'] = 'N/A'
                    data['adres'] = 'N/A'

                location_div = card.find('div', class_='truncate text-neutral-80')
                data['stad_dorp'] = location_div.get_text(strip=True) if location_div else 'N/A'

                price_p = card.find('p', attrs={'data-testid': 'result-item-price'})
                data['prijs'] = price_p.get_text(strip=True) if price_p else 'N/A'

                realtor_container = card.find('div', class_='flex w-full justify-between')
                if realtor_container:
                    realtor_link = realtor_container.find('a')
                    data['makelaar'] = (
                        realtor_link.find('span').get_text(strip=True)
                        if realtor_link and realtor_link.find('span')
                        else 'N/A'
                    )
                else:
                    data['makelaar'] = 'N/A'

                all_properties.append(data)

    finally:
        driver.quit()

    return {
        "blocked": blocked,
        "debug": {"title": debug_title, "url": debug_url},
        "items": all_properties,
        "count": len(all_properties),
    }


@app.get("/")
def root():
    return {"service": "funda-scraper-api", "endpoints": ["/health", "/scrape", "/docs"]}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/scrape")
def scrape(
    pages: int = Query(10, ge=1, le=50, description="Aantal resultaatpagina's om te scrapen"),
    headless: bool = Query(True, description="Draai Chromium headless (True=sneller)")
):
    result = scrape_funda_today(max_pages=pages, headless=headless)
    return JSONResponse(content={"ok": True, **result})
