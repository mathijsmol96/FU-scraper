# api.py
from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def root():
    return {
        "service": "funda-scraper-api",
        "endpoints": ["/health", "/scrape"],
        "port_env": os.environ.get("PORT")
    }

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/scrape")
def scrape():
    # Lazy import so the app can start even if curl_cffi has issues
    try:
        from curl_cffi import requests
    except Exception as e:
        return {"status": "error", "stage": "import curl_cffi", "message": str(e)}

    api_url = "https://www.funda.nl/api/v2/zoeken/"
    params = {
        "type": "koop",
        "selected_area": '["nl"]',
        "publication_date": "1",
        "availability": '["available"]',
        "sort": "date_down",
        "page": "1",
        "size": "150",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Referer": "https://www.funda.nl/",
    }

    try:
        resp = requests.get(api_url, headers=headers, params=params, impersonate="chrome120", timeout=45)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"status": "error", "stage": "fetch funda", "message": str(e)}

    try:
        items = []
        for obj in data.get("objects", []):
            items.append({
                "link": "https://www.funda.nl" + (obj.get("detailUrl") or ""),
                "adres": obj.get("adres", "N/A"),
                "postcode": obj.get("postcode", "N/A"),
                "stad_dorp": obj.get("plaats", "N/A"),
                "prijs": (obj.get("prijs") or {}).get("prijsWeergave", "N/A"),
                "makelaar": obj.get("makelaarNaam", "N/A"),
            })
        return {"status": "success", "count": len(items), "data": items}
    except Exception as e:
        return {"status": "error", "stage": "parse funda", "message": str(e)}
