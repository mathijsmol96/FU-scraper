# api.py
from fastapi import FastAPI, Query
from curl_cffi import requests

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/scrape")
def run_funda_scraper(
    type: str = "koop",
    selected_area: str = '["nl"]',
    publication_date: str = "1",
    availability: str = '["available"]',
    sort: str = "date_down",
    page: int = 1,
    size: int = 150,
):
    api_url = "https://www.funda.nl/api/v2/zoeken/"
    params = {
        "type": type,
        "selected_area": selected_area,
        "publication_date": publication_date,
        "availability": availability,
        "sort": sort,
        "page": str(page),
        "size": str(size),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Referer": "https://www.funda.nl/",
    }

    try:
        resp = requests.get(api_url, headers=headers, params=params, impersonate="chrome120", timeout=45)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for obj in data.get("objects", []):
            results.append({
                "link": "https://www.funda.nl" + (obj.get("detailUrl") or ""),
                "adres": obj.get("adres", "N/A"),
                "postcode": obj.get("postcode", "N/A"),
                "stad_dorp": obj.get("plaats", "N/A"),
                "prijs": (obj.get("prijs") or {}).get("prijsWeergave", "N/A"),
                "makelaar": obj.get("makelaarNaam", "N/A"),
            })
        return {"status": "success", "count": len(results), "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}
