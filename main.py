import os
import re
import asyncio
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

# -------------------------------------------------------------
# 1. RENDER HEALTH CHECK SERVER
# -------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Scraper active and integrated with ExtraPe.")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# -------------------------------------------------------------
# 2. CONFIGURATION
# -------------------------------------------------------------
EXTRAPE_TOKEN = os.environ.get("EXTRAPE_TOKEN", "")
DISCOUNT_THRESHOLD = 70       
CHECK_INTERVAL_SECONDS = 180   

SEARCH_URLS = [
    "https://www.flipkart.com/search?q=smartwatches&p%5B%5D=facets.discount_range_v1%3D70%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=headphones&p%5B%5D=facets.discount_range_v1%3D70%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=shoes&p%5B%5D=facets.discount_range_v1%3D70%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=t-shirts&p%5B%5D=facets.discount_range_v1%3D70%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=backpacks&p%5B%5D=facets.discount_range_v1%3D70%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=sunglasses&p%5B%5D=facets.discount_range_v1%3D70%2525%2Bor%2Bmore"
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

price_history = {}

def extract_numeric(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0

# -------------------------------------------------------------
# 3. EXTRAPE CONVERT & AUTO-POST
# -------------------------------------------------------------
async def push_deal_to_extrape(session: AsyncSession, product_url: str, title: str, price: int, discount: int):
    if not EXTRAPE_TOKEN:
        print("[-] EXTRAPE_TOKEN not found in environment!", flush=True)
        return

    endpoint = "https://www.extrape.com/handler/convertText"
    encoded_url = urllib.parse.quote(product_url, safe="")
    
    deal_payload = {
        "inputText": encoded_url,
        "bitlyConvert": False,
        "advanceMode": False
    }

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.extrape.com",
        "Referer": "https://www.extrape.com/make-links",
        "Authorization": f"Bearer {EXTRAPE_TOKEN}",
        "Cookie": f"accessToken={EXTRAPE_TOKEN}"
    }

    try:
        resp = await session.post(endpoint, json=deal_payload, headers=req_headers, timeout=15.0)
        
        if resp.status_code == 200:
            print(f"[✓] Successfully pushed to ExtraPe: {title[:25]}... (₹{price} / {discount}% off)", flush=True)
        else:
            print(f"[-] ExtraPe rejected (HTTP {resp.status_code}): {resp.text[:120]}", flush=True)

    except Exception as err:
        print(f"[-] Error calling convertText: {err}", flush=True)

# -------------------------------------------------------------
# 4. SCRAPING ENGINE
# -------------------------------------------------------------
async def scan_flipkart_page(session: AsyncSession, url: str):
    category = url.split("q=")[1].split("&")[0]
    try:
        resp = await session.get(url, headers=HEADERS, impersonate="chrome124", timeout=20.0)
        if resp.status_code != 200:
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div[data-id], div.slAVV4, div._75nlfW, div._1AtVbE")
        found_drops = 0

        for card in cards:
            link_tag = card.select_one("a[href*='/p/']")
            if not link_tag or not link_tag.get("href"):
                continue

            raw_href = link_tag["href"]
            clean_url = f"https://www.flipkart.com{raw_href.split('?')[0]}"

            card_text = card.get_text(" ", strip=True)
            if any(term in card_text.lower() for term in ["out of stock", "sold out", "currently unavailable"]):
                continue

            cur_price_el = card.select_one("div.Nx9bqj, div._30jeq3")
            cur_price = extract_numeric(cur_price_el.get_text()) if cur_price_el else 0
            if cur_price == 0:
                continue

            disc_el = card.select_one("div.UkUFwK span, div._3Ay6Sb span")
            discount = 0
            if disc_el:
                m = re.search(r"(\d+)%", disc_el.get_text())
                if m:
                    discount = int(m.group(1))

            mrp_el = card.select_one("div.yRaY8j, div._3I9_wc")
            mrp = extract_numeric(mrp_el.get_text()) if mrp_el else 0
            if (mrp <= cur_price or mrp == 0) and discount > 0 and discount < 100:
                mrp = round(cur_price / (1 - (discount / 100)))

            if discount == 0 and mrp > cur_price:
                discount = round(((mrp - cur_price) / mrp) * 100)

            title_tag = card.select_one("div.KzDlHZ, a.wjcEIp, a.WKTcLC, div._4rR01T, a.s1Q9rs")
            title = title_tag.get_text(strip=True) if title_tag else (link_tag.get("title") or "Flipkart Deal")

            # Genuine Price Drop Logic
            is_genuine_drop = False
            if clean_url not in price_history:
                if discount >= DISCOUNT_THRESHOLD:
                    is_genuine_drop = True
            else:
                if cur_price < price_history[clean_url]:
                    is_genuine_drop = True

            price_history[clean_url] = cur_price

            if is_genuine_drop:
                found_drops += 1
                await push_deal_to_extrape(session, clean_url, title, cur_price, discount)
                await asyncio.sleep(4)

        print(f"[*] {category}: Processed {len(cards)} items -> {found_drops} price drops triggered.", flush=True)

    except Exception as err:
        print(f"[-] Scrape error on {category}: {err}", flush=True)

async def main():
    print("[*] Bot running: Token-authenticated convertText active...", flush=True)
    threading.Thread(target=run_health_server, daemon=True).start()
    print("[+] Port 10000 bound.", flush=True)

    async with AsyncSession() as session:
        while True:
            print("[*] Starting sweep...", flush=True)
            for url in SEARCH_URLS:
                await scan_flipkart_page(session, url)
                await asyncio.sleep(3)

            print(f"[*] Sweep done. Pausing for {CHECK_INTERVAL_SECONDS}s...", flush=True)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main())
