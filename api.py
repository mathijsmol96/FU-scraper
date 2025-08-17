# api.py

import time
import json
import uuid
import threading
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup

app = FastAPI(
    title="funda-scraper-api",
    version="1.0.2",
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- Exact jouw URL (URL-encoded) ---
BASE_URL = (
    "https://www.funda.nl/zoeken/koop"
    "?selected_area=[%22nl%22]"
    "&publication_date=%221%22"
    "&availability=[%22available%22]"
)

JOBS: Dict[str, Dict[str, Any]] = {}

def _make_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=nl-NL,nl")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
    opts.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.set_capability("pageLoadStrategy", "eager")
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(120)
    return driver

def _safe_get(driver: webdriver.Chrome, url: str, retries: int = 3, sleep_s: float = 4.0) -> None:
    last_err: Optional[Exception] = None
    for _ in range(max(1, retries)):
        try:
            driver.get(url)
            return
        except Exception as e:
            last_err = e
            time.sleep(sleep_s)
    if last_err:
        raise last_err

def _extract_price(card) -> str:
    # 1) jouw oorspronkelijke selector
    el = card.find("p", attrs={"data-testid": "result-item-price"})
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)
    # 2) CSS fallback (sommige varianten)
    el = card.select_one("[data-testid='result-item-price']")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)
    # 3) brute fallback: pak een element dat een euroteken bevat
    span_with_euro = card.find(lambda tag: tag.name in ("p", "span", "div")
                               and tag.get_text() and "€" in tag.get_text())
    if span_with_euro:
        return span_with_euro.get_text(strip=True)
    return "N/A"

def scrape_funda_today(max_pages: int = 1, headless: bool = True) -> List[Dict[str, Any]]:
    chrome = _make_driver(headless=headless)
    wait = WebDriverWait(chrome, 15)
    all_properties: List[Dict[str, Any]] = []
    try:
        _safe_get(chrome, "https://www.funda.nl")
        try:
            btn = wait.until(EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button")))
            btn.click()
            time.sleep(1)
        except Exception:
            pass

        for page_number in range(1, max_pages + 1):
            url = BASE_URL if page_number == 1 else f"{BASE_URL}&search_result={page_number}"
            try:
                _safe_get(chrome, url)
                try:
                    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div[class*='@container']")))
                except TimeoutException:
                    pass

                time.sleep(2)
                soup = BeautifulSoup(chrome.page_source, "html.parser")
                cards = soup.find_all("div", class_='@container border-b pb-3')
                if not cards:
                    # soft retry 1x
                    _safe_get(chrome, url)
                    time.sleep(2)
                    soup = BeautifulSoup(chrome.page_source, "html.parser")
                    cards = soup.find_all("div", class_='@container border-b pb-3')
                    if not cards:
                        break

                for card in cards:
                    data: Dict[str, Any] = {}
                    address_element = card.find('a', attrs={'data-testid': 'listingDetailsAddress'})
                    if address_element:
                        data['link'] = 'https://www.funda.nl' + (address_element.get('href') or '')
                        street_address_div = address_element.find('div', class_='flex font-semibold')
                        data['adres'] = street_address_div.get_text(strip=True, separator=' ') if street_address_div else 'N/A'
                    else:
                        data['link'] = ''
                        data['adres'] = 'N/A'

                    location_div = card.find('div', class_='truncate text-neutral-80')
                    data['stad_dorp'] = location_div.get_text(strip=True) if location_div else 'N/A'

                    data['prijs'] = _extract_price(card)

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
                continue
    finally:
        try:
            chrome.quit()
        except Exception:
            pass
    return all_properties

def _run_job(job_id: str, pages: int, headless: bool) -> None:
    try:
        JOBS[job_id]["status"] = "running"
        items = scrape_funda_today(max_pages=pages, headless=headless)
        JOBS[job_id]["count"] = len(items)
        out_path = f"/tmp/funda_{job_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        JOBS[job_id]["file"] = out_path
        JOBS[job_id]["status"] = "done"
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = repr(e)

@app.get("/")
def root():
    return {"ok": True, "message": "Use /docs for API docs."}

@app.get("/health")
def health():
    return {"ok": True}

# NU: pages 1..10 toegestaan (alles in één overzicht)
@app.get("/scrape")
def scrape(pages: int = Query(1, ge=1, le=10), headless: int = Query(1)):
    items = scrape_funda_today(max_pages=pages, headless=bool(headless))
    return {"ok": True, "count": len(items), "items": items}

# Shortcut: altijd 10 pagina's (één call)
@app.get("/scrape/all")
def scrape_all(headless: int = Query(1)):
    items = scrape_funda_today(max_pages=10, headless=bool(headless))
    return {"ok": True, "count": len(items), "items": items}

# Background job (blijft handig als Render alsnog te traag is)
@app.get("/scrape/start")
def scrape_start(pages: int = Query(10, ge=1, le=10), headless: int = Query(1)):
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "queued", "file": "", "count": 0, "error": ""}
    t = threading.Thread(target=_run_job, args=(job_id, pages, bool(headless)), daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id, "pages": pages}

@app.get("/scrape/status/{job_id}")
def scrape_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_id not found")
    return {"ok": True, **job}

@app.get("/scrape/result/{job_id}")
def scrape_result(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_id not found")
    if job["status"] != "done":
        return {"ok": False, "status": job["status"], "error": job.get("error", "")}
    with open(job["file"], "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"ok": True, "count": job["count"], "items": data}
