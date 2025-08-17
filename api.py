# api.py — FastAPI laagje om je scraper
from fastapi import FastAPI, Query
from run_scraper import get_basic_data

app = FastAPI(title="funda-scraper-api")

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/scrape")
def scrape(pages: int = Query(10, ge=1, le=20, description="Aantal pagina's om te scrapen")):
    data = get_basic_data(max_pages=pages)
    return {"ok": True, "count": len(data), "results": data}
