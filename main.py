import os
import re
import json
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

# -------------------------------------------------------------
# 1. RENDER PORT LISTENER (Health Check)
# -------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# -------------------------------------------------------------
# 2. BOT CONFIGURATION
# -------------------------------------------------------------
BOT_TOKEN = "8916500708:AAGxhpTfz8x9ifJcdiL7loHdnwM0Mch-UtY"
CHANNEL_USERNAME = "@Daily_loot_deals25"
DISCOUNT_THRESHOLD = 40  # Set to 40% to guarantee instant hits
CHECK_INTERVAL_SECONDS = 60

SEARCH_URLS = [
    "https://www.flipkart.com/search?q=smartwatches&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=headphones&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=shoes&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=deals&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore"
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

seen_products = set()

def extract_numeric(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0

async def post_to_telegram(session: AsyncSession, title: str, cur_price: int, mrp: int, discount: int, link: str):
    mrp_text = f"❌ *MRP:* ₹{mrp:,}\n" if mrp > 0 else ""
    message = (
        f"🔥 *LOOT DEAL ({discount}% OFF)* 🔥\n\n"
        f"📦 *Product:* {title}\n"
        f"💰 *Deal Price:* ₹{cur_price:,}\n"
        f"{mrp_text}"
        f"📉 *Discount:* {discount}% OFF\n\n"
        f"🛒 [Grab Deal on Flipkart]({link})"
    )

    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_USERNAME,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:
        resp = await session.post(telegram_url, json=payload, timeout=15.0)
        res_data = resp.json()
        if res_data.get("ok"):
            print(f"[+] Posted to Telegram: {title[:30]}... ({discount}%)", flush=True)
        else:
            print(f"[-] Telegram Error: {res_data}", flush=True)
    except Exception as e:
        print(f"[-] Telegram dispatch error: {e}", flush=True)

async def scan_flipkart_page(session: AsyncSession, url: str):
    category = url.split("q=")[1].split("&")[0]
    try:
        resp = await session.get(url, headers=HEADERS, impersonate="chrome124", timeout=20.0)
        if resp.status_code != 200:
            print(f"[-] HTTP {resp.status_code} for {category}", flush=True)
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        deals_posted = 0

        # Method 1: Check embedded window.__INITIAL_STATE__ or json scripts
        json_found = False
        for script in soup.find_all("script"):
            script_text = script.string or ""
            if "__INITIAL_STATE__" in script_text or "pageDataV4" in script_text:
                try:
                    # Extract JSON payload inside script
                    json_str_match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});", script_text)
                    if json_str_match:
                        raw_data = json.loads(json_str_match.group(1))
                        # Navigate slots if present
                        slots = raw_data.get("pageDataV4", {}).get("page", {}).get("data", {}).get("10002", [])
                        for slot in slots:
                            widget = slot.get("widget", {}).get("data", {})
                            for prod in widget.get("products", []):
                                pinfo = prod.get("productInfo", {}).get("value", {})
                                p_url = pinfo.get("smartUrl", "")
                                if not p_url:
                                    continue
                                full_url = f"https://www.flipkart.com{p_url.split('?')[0]}"
                                if full_url in seen_products:
                                    continue
                                
                                title = pinfo.get("titles", {}).get("title", "Flipkart Loot Deal")
                                price = pinfo.get("pricing", {}).get("finalPrice", {}).get("value", 0)
                                mrp = pinfo.get("pricing", {}).get("mrp", {}).get("value", 0)
                                disc = pinfo.get("pricing", {}).get("totalDiscount", 0)
                                
                                if mrp > 0 and price > 0:
                                    disc = round(((mrp - price) / mrp) * 100)
                                
                                if disc >= DISCOUNT_THRESHOLD and price > 0:
                                    seen_products.add(full_url)
                                    deals_posted += 1
                                    await post_to_telegram(session, title, price, mrp, disc, full_url)
                        if deals_posted > 0:
                            json_found = True
                            break
                except Exception:
                    pass

        # Method 2: DOM Card Parsing with Regex Extraction
        cards = soup.select("div[data-id], div.slAVV4, div._75nlfW, div._1AtVbE")
        for card in cards:
            link_tag = card.select_one("a[href*='/p/']")
            if not link_tag or not link_tag.get("href"):
                continue

            raw_href = link_tag["href"]
            clean_url = f"https://www.flipkart.com{raw_href.split('?')[0]}"
            if clean_url in seen_products:
                continue

            card_text = card.get_text(" ", strip=True)

            # Extract prices using standard regex pattern on the entire card text
            prices = re.findall(r"₹([\d,]+)", card_text)
            if not prices:
                continue

            # In Flipkart cards, the first price is current, second is MRP
            cur_price = extract_numeric(prices[0])
            mrp = extract_numeric(prices[1]) if len(prices) > 1 else 0

            # Extract discount from text like "55% off"
            disc_match = re.search(r"(\d+)%\s*off", card_text, re.IGNORECASE)
            discount = int(disc_match.group(1)) if disc_match else 0

            if discount == 0 and mrp > cur_price and mrp > 0:
                discount = round(((mrp - cur_price) / mrp) * 100)

            if discount >= DISCOUNT_THRESHOLD and cur_price > 0:
                # Find best matching title
                title_tag = card.select_one("div.KzDlHZ, a.wjcEIp, a.WKTcLC, div._4rR01T, a.s1Q9rs")
                title = title_tag.get_text(strip=True) if title_tag else (link_tag.get("title") or "Flipkart Loot Deal")

                seen_products.add(clean_url)
                deals_posted += 1
                await post_to_telegram(session, title, cur_price, mrp, discount, clean_url)

        print(f"[*] {category}: Processed {len(cards)} items -> Dispatched {deals_posted} deals.", flush=True)

    except Exception as err:
        print(f"[-] Scan error on {category}: {err}", flush=True)

async def main():
    print("[*] Launching updated discount extractor...", flush=True)
    threading.Thread(target=run_health_server, daemon=True).start()
    print("[+] Port 10000 bound.", flush=True)

    async with AsyncSession() as session:
        while True:
            print("[*] Starting sweep...", flush=True)
            for url in SEARCH_URLS:
                await scan_flipkart_page(session, url)
                await asyncio.sleep(2)

            print(f"[*] Sweep done. Pausing for {CHECK_INTERVAL_SECONDS}s...", flush=True)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main())
