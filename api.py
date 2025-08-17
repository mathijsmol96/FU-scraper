# Bestandsnaam: api.py

from fastapi import FastAPI
from curl_cffi import requests
import json

app = FastAPI()

@app.get("/scrape")
def run_funda_scraper():
    api_url = "https://www.funda.nl/api/v2/zoeken/"
    params = {
        "type": "koop",
        "selected_area": '["nl"]',
        "publication_date": "1",
        "availability": '["available"]',
        "sort": "date_down",
        "page": "1",
        "size": "150"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Referer": "https://www.funda.nl/"
    }
    
    try:
        response = requests.get(api_url, headers=headers, params=params, impersonate="chrome120")
        response.raise_for_status()
        data = response.json()
        
        all_properties = []
        for obj in data.get('objects', []):
            prop = {}
            prop['link'] = "https://www.funda.nl" + obj.get('detailUrl', '')
            prop['adres'] = obj.get('adres', 'N/A')
            prop['postcode'] = obj.get('postcode', 'N/A')
            prop['stad_dorp'] = obj.get('plaats', 'N/A')
            prop['prijs'] = obj.get('prijs', {}).get('prijsWeergave', 'N/A')
            prop['makelaar'] = obj.get('makelaarNaam', 'N/A')
            all_properties.append(prop)
            
        return {"status": "success", "count": len(all_properties), "data": all_properties}

    except Exception as e:
        return {"status": "error", "message": str(e)}