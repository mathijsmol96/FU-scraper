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
              version="1.0.0")


def _find_playwright_chrome_binary() -> str | None:
    for sp in site.getsitepackages():
        base = os.path.join(sp, "playwright", "driver", "package", ".local-browsers")
        matches = glob.glob(os.path.join(base, "chromium-*", "chrome-linux", "chrome"))
        if matches:
            return matches[0]
    return None


def _make_driver(headless: bool = True) -> webdriver.Chrome:
    chrome_binary = _find_playwright_chrome_binary()

    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,768")
    if headless:
        options.add_argument("--headless=new")

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if chrome_binary and os.path.exists(chrome_binary):
        options.binary_location = chrome_binary

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


def scrape_funda_today(max_pages: int = 10, headless: bool = True) -> List[Dict[str, Any]]:
    base_url = (
        "https://www.funda.nl/zoeken/koop"
        "?selected_area=[%22nl%22]"
        "&publication_date=%221%22"
        "&availability=[%22available%22]"
    )

    all_properties: List[Dict[str, Any]] = []
    driver = _make_driver(headless=headless)
    wait = WebDriverWait(driver, 20)

    try:
        driver.get("https://www.funda.nl")
        try:
            cookie_btn = wait.until(
                EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button"))
            )
            cookie_btn.click()
            time.sleep(1)
        except Exception:
            pass

        for page_number in range(1, max_pages + 1):
            url = f"{base_url}&search_result={page_number}" i_
