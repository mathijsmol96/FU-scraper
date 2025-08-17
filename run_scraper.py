# run_scraper.py — Finale versie (Render-ready, jouw logica ongewijzigd)
import os
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

def get_basic_data(max_pages: int | None = None):
    # Om te kunnen sturen vanuit env (Render)
    HEADLESS = os.getenv("HEADLESS", "1") == "1"
    MAX_PAGES = int(os.getenv("MAX_PAGES", "10")) if max_pages is None else int(max_pages)

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("start-maximized")

    # Nodig in Linux/containers
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1366,850")
    if HEADLESS:
        chrome_options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 15)

    base_url = (
        "https://www.funda.nl/zoeken/koop"
        "?selected_area=[%22nl%22]&publication_date=%221%22&availability=[%22available%22]"
    )
    all_properties = []

    try:
        driver.get("https://www.funda.nl")
        print("Pagina geopend, wacht op de cookie-knop...")
        try:
            cookie_button = wait.until(EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button")))
            cookie_button.click()
            print("Cookies geaccepteerd.")
            time.sleep(1)
        except Exception:
            print("Geen cookie pop-up gevonden (of al geaccepteerd).")

        for page_number in range(1, MAX_PAGES + 1):
            url = f"{base_url}&search_result={page_number}" if page_number > 1 else base_url
            driver.get(url)
            print(f"Verzamel basisdata van pagina {page_number}...")

            try:
                wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div[class*='@container']")))
                time.sleep(2)

                html = driver.page_source
                soup = BeautifulSoup(html, "html.parser")

                property_cards = soup.find_all("div", class_='@container border-b pb-3')

                if not property_cards:
                    print("Geen woningen meer gevonden op deze pagina. Stoppen.")
                    break

                print(f"{len(property_cards)} woningen gevonden op deze pagina.")

                for card in property_cards:
                    data = {}
                    address_element = card.find("a", attrs={"data-testid": "listingDetailsAddress"})
                    if address_element:
                        data["link"] = "https://www.funda.nl" + address_element["href"]
                        street_address_div = address_element.find("div", class_="flex font-semibold")
                        data["adres"] = street_address_div.get_text(strip=True, separator=" ") if street_address_div else "N/A"

                    location_div = card.find("div", class_="truncate text-neutral-80")
                    data["stad_dorp"] = location_div.get_text(strip=True) if location_div else "N/A"

                    price_element = card.find("p", attrs={"data-testid": "result-item-price"})
                    data["prijs"] = price_element.get_text(strip=True) if price_element else "N/A"

                    # Finale makelaar-correctie
                    realtor_container = card.find("div", class_="flex w-full justify-between")
                    if realtor_container:
                        realtor_link = realtor_container.find("a")
                        data["makelaar"] = realtor_link.find("span").get_text(strip=True) if realtor_link else "N/A"
                    else:
                        data["makelaar"] = "N/A"

                    all_properties.append(data)

            except Exception as e:
                print(f"Fout op pagina {page_number}, mogelijk de laatste. Stoppen. Fout: {e}")
                break
    finally:
        driver.quit()

    return all_properties

if __name__ == "__main__":
    print("Start de basisdata-verzamelaar...")
    basic_data = get_basic_data()
    with open("funda_basic_data.json", "w", encoding="utf-8") as f:
        json.dump(basic_data, f, ensure_ascii=False, indent=4)
    print(f"\nKlaar! {len(basic_data)} woningen opgeslagen in 'funda_basic_data.json'")
