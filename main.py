import os
import re
import asyncio
import threading
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
        self.wfile.write(b"Bot is alive and running!")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# -------------------------------------------------------------
# 2. CONFIGURATION
# -------------------------------------------------------------
BOT_TOKEN = "8916500708:AAGxhpTfz8x9ifJcdiL7loHdnwM0Mch-UtY"
CHANNEL_USERNAME = "@Daily_loot_deals25"
DISCOUNT_THRESHOLD = 50
CHECK_INTERVAL_SECONDS = 60

# Category URLs with pre-applied 50%+ discount filter facets
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
    message = (
        f"🔥 *LOOT DEAL ({discount}% OFF)* 🔥\n\n"
        f"📦 *Product:* {title}\n"
        f"💰 *Deal Price:* ₹{cur_price:,}\n"
        f"❌ *MRP:* ₹{mrp:,}\n"
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
            print(f"[+] Posted to Telegram: {title[:35]}... ({discount}%)", flush=True)
        else:
            print(f"[-] Telegram Error: {res_data}", flush=True)
    except Exception as e:
        print(f"[-] Telegram dispatch error: {e}", flush=True)

async def scan_flipkart_page(session: AsyncSession, url: str):
    try:
        resp = await session.get(url, headers=HEADERS, impersonate="chrome124", timeout=20.0)
        print(f"[*] Fetched page {url.split('q=')[1].split('&')[0]} -> Status: {resp.status_code}", flush=True)

        if resp.status_code != 200:
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Comprehensive selector matching all Flipkart search layouts (grid, list, mobile)
        cards = soup.select("div[data-id], div.slAVV4, div._75nlfW, div._1AtVbE")
        deals_posted = 0

        for card in cards:
            # 1. Grab Product URL
            link_tag = card.select_one("a[href*='/p/']")
            if not link_tag or not link_tag.get("href"):
                continue

            raw_href = link_tag["href"]
            clean_url = f"https://www.flipkart.com{raw_href.split('?')[0]}"

            if clean_url in seen_products:
                continue

            # 2. Grab Title
            title_tag = card.select_one("div.KzDlHZ, a.wjcEIp, a.WKTcLC, div._4rR01T, a.s1Q9rs")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)

            # 3. Grab Prices
            cur_price_tag = card.select_one("div.Nx9bqj, div._30jeq3")
            mrp_tag = card.select_one("div.yRaY8j, div._3I9_wc")

            if not cur_price_tag or not mrp_tag:
                continue

            cur_price = extract_numeric(cur_price_tag.get_text())
            mrp = extract_numeric(mrp_tag.get_text())

            if mrp > 0 and cur_price < mrp:
                discount = round(((mrp - cur_price) / mrp) * 100)

                if discount >= DISCOUNT_THRESHOLD:
                    seen_products.add(clean_url)
                    deals_posted += 1
                    await post_to_telegram(session, title, cur_price, mrp, discount, clean_url)

        print(f"[*] Processed {len(cards)} items, posted {deals_posted} deals.", flush=True)

    except Exception as err:
        print(f"[-] Scrape error: {err}", flush=True)

async def main():
    print("[*] Bot starting HTML parser with Chrome TLS impersonation...", flush=True)
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
