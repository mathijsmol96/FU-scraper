# api.py — volledige API met Playwright (sync) + no-sandbox
from fastapi import FastAPI, Query
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


def scrape_funda(max_pages: int = 1) -> List[Dict[str, Any]]:
    """
    Heel eenvoudige scraper om de basis te demonstreren.
    Past mogelijk aan als Funda de HTML wijzigt.
    """
    results: List[Dict[str, Any]] = []

    # Basiszoek-URL (actuele koop, NL, beschikbaar)
    base_url = (
        "https://www.funda.nl/zoeken/koop"
        "?selected_area=[%22nl%22]"
        "&publication_date=%221%22"
        "&availability=[%22available%22]"
    )

    with sync_playwright() as p:
        # Belangrijk: --no-sandbox voor Render-omgevingen
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        page = context.new_page()

        # Cookies accepteren (als aanwezig)
        page.goto("https://www.funda.nl", wait_until="domcontentloaded")
        try:
            page.click("#didomi-notice-agree-button", timeout=4000)
        except Exception:
            pass

        # Pagina's doorlopen
        for i in range(1, max_pages + 1):
            url = f"{base_url}&search_result={i}" if i > 1 else base_url
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)  # klein moment zodat de kaarten laden

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Kaarten vinden (selectors kunnen variëren in de tijd)
            cards = soup.find_all("div", class_="@container border-b pb-3")
            if not cards:
                break

            for card in cards:
                data: Dict[str, Any] = {}

                # Link + adres
                address_link = card.find("a", attrs={"data-testid": "listingDetailsAddress"})
                if address_link:
                    data["link"] = "https://www.funda.nl" + address_link.get("href", "")
                    street_div = address_link.find("div", class_="flex font-semibold")
                    data["adres"] = street_div.get_text(strip=True, separator=" ") if street_div else "N/B"
                else:
                    data["link"] = ""
                    data["adres"] = "N/B"

                # Plaats
                loc_div = card.find("div", class_="truncate text-neutral-80")
                data["stad_dorp"] = loc_div.get_text(strip=True) if loc_div else "N/B"

                # Prijs
                price = card.find("p", attrs={"data-testid": "result-item-price"})
                data["prijs"] = price.get_text(strip=True) if price else "N/B"

                # Makelaar (kan ontbreken)
                realtor_container = card.find("div", class_="flex w-full justify-between")
                if realtor_container:
                    realtor_link = realtor_container.find("a")
                    data["makelaar"] = (
                        realtor_link.find("span").get_text(strip=True) if realtor_link else "N/B"
                    )
                else:
                    data["makelaar"] = "N/B"

                results.append(data)

        context.close()
        browser.close()

    return results


@app.get("/scrape")
def scrape(max_pages: int = Query(1, ge=1, le=10)):
    data = scrape_funda(max_pages=max_pages)
    return {"count": len(data), "items": data}
