# api.py — FastAPI + Playwright (sync) met robuuste scraping en foutafhandeling
from fastapi import FastAPI, Query
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


def _new_context(p):
    """
    Maakt een browser context die op echte Chrome lijkt en NL-headers gebruikt.
    Extra flags helpen in container-omgevingen zoals Render.
    """
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )

    # Echte UA + NL headers. Dit voorkomt vaak blokkades / lege pagina's.
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="nl-NL",
        extra_http_headers={
            "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        viewport={"width": 1366, "height": 768},
    )
    return browser, context


def _click_cookie_consent(page):
    # Probeer populaire cookie/consent knoppen; negeer errors.
    candidates = [
        "#didomi-notice-agree-button",
        "button[aria-label='Akkoord']",
        "button:has-text('Akkoord')",
        "button:has-text('Accepteren')",
        "button:has-text('Accepteer')",
    ]
    for sel in candidates:
        try:
            page.click(sel, timeout=2000)
            return
        except Exception:
            pass


def _parse_listings(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")

    # 1) Probeer data-testid container (meestal het stabielst)
    cards = soup.select("article[data-testid='search-result-item']")
    # 2) Fallback op div met zelfde testid
    if not cards:
        cards = soup.select("div[data-testid='search-result-item']")
    # 3) Laatste redmiddel: tailwind-achtige container (kan wisselen)
    if not cards:
        cards = soup.find_all("div", class_="@container border-b pb-3")

    results: List[Dict[str, Any]] = []

    for card in cards:
        data: Dict[str, Any] = {}

        # Link + adres
        link_el = card.select_one("a[data-testid='listingDetailsAddress']") or card.find("a")
        href = link_el.get("href", "") if link_el else ""
        if href and href.startswith("/"):
            href = "https://www.funda.nl" + href
        data["link"] = href or ""

        # Adres-tekst
        # 1) Probeer testid-address
        address_text = ""
        addr = card.select_one("[data-testid='listingDetailsAddress']")
        if addr:
            address_text = addr.get_text(strip=True, separator=" ")
        # 2) Fallback op iets als 'flex font-semibold'
        if not address_text:
            street_div = card.find("div", class_="flex font-semibold")
            if street_div:
                address_text = street_div.get_text(strip=True, separator=" ")
        # 3) Als nog leeg: pak de link-tekst
        if not address_text and link_el:
            address_text = link_el.get_text(strip=True, separator=" ")
        data["adres"] = address_text or "N/B"

        # Plaats
        plaats = ""
        sub = card.select_one("[data-testid='result-item-subtitle']")
        if sub:
            plaats = sub.get_text(strip=True)
        if not plaats:
            loc_div = card.find("div", class_="truncate text-neutral-80")
            if loc_div:
                plaats = loc_div.get_text(strip=True)
        data["stad_dorp"] = plaats or "N/B"

        # Prijs
        prijs_el = card.select_one("[data-testid='result-item-price']")
        data["prijs"] = prijs_el.get_text(strip=True) if prijs_el else "N/B"

        # Makelaar (kan ontbreken)
        makelaar = ""
        # soms zit het in een container met link naar de makelaar
        realtor_container = card.find("div", class_="flex w-full justify-between")
        if realtor_container:
            a = realtor_container.find("a")
            if a:
                span = a.find("span")
                if span:
                    makelaar = span.get_text(strip=True)
        data["makelaar"] = makelaar or "N/B"

        results.append(data)

    return results


def scrape_funda(max_pages: int = 1) -> Dict[str, Any]:
    """
    Scraper die altijd JSON-structuur teruggeeft.
    Bij fouten krijg je een 'error' veld, i.p.v. 500 HTML.
    """
    base_url = (
        "https://www.funda.nl/zoeken/koop"
        "?selected_area=[%22nl%22]"
        "&publication_date=%221%22"
        "&availability=[%22available%22]"
    )

    last_url = None
    all_items: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        try:
            browser, context = _new_context(p)
            page = context.new_page()

            # 1) homepage: cookies wegklikken
            page.goto("https://www.funda.nl", wait_until="domcontentloaded", timeout=45000)
            _click_cookie_consent(page)

            # 2) result pages
            for i in range(1, max_pages + 1):
                last_url = f"{base_url}&search_result={i}" if i > 1 else base_url
                page.goto(last_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1200)  # even ademruimte voor renderen

                # Probeer te wachten tot er íets van resultaten staat
                try:
                    page.wait_for_selector("[data-testid='search-result-item'], article[data-testid='search-result-item']",
                                           timeout=4000)
                except Exception:
                    # niet fataal; we parsen gewoon wat er is
                    pass

                html = page.content()
                items = _parse_listings(html)

                if not items:
                    # Mogelijk anti-bot / lege pagina -> zet debug-info
                    title = page.title()
                    all_items.extend([])  # niets, maar we geven debug terug
                    return {
                        "count": 0,
                        "items": [],
                        "debug": {
                            "last_url": last_url,
                            "page_title": title,
                            "note": "Geen kaarten gevonden. Mogelijk selectors veranderd of anti-bot.",
                        },
                    }

                all_items.extend(items)

            context.close()
            browser.close()

            return {"count": len(all_items), "items": all_items, "debug": {"last_url": last_url}}

        except Exception as e:
            # Zorg dat je ALTIJD JSON terugkrijgt
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exceptio
