import os
import re
import time
import asyncio
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from bs4 import BeautifulSoup
import httpx

# -------------------------------------------------------------
# 1. LIGHTWEIGHT HEALTHCHECK SERVER (Prevents Render Port Timeout)
# -------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is healthy and scanning.")

    def log_message(self, format, *args):
        # Silence default HTTP server logging to keep terminal clean
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# -------------------------------------------------------------
# 2. CONFIGURATION & CREDENTIALS
# -------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8916500708:AAGxhpTfz8x9ifJcdiL7loHdnwM0Mch-UtY")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@Daily_loot_deals25")
DISCOUNT_THRESHOLD = 50  # Minimum discount percentage to trigger post
CHECK_INTERVAL_SECONDS = 180  # Check every 3 minutes

# Search targets across key Flipkart categories
SEARCH_URLS = [
    "https://www.flipkart.com/search?q=deals&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=headphones&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=smartwatches&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=t-shirts&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# Cache to avoid posting duplicate products in the same run
seen_products = set()

# -------------------------------------------------------------
# 3. HELPER FUNCTIONS
# -------------------------------------------------------------
def extract_numeric(text: str) -> int:
    """Extract digits from price strings like '₹1,299' -> 1299."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0

async def post_to_telegram(client: httpx.AsyncClient, title: str, cur_price: int, mrp: int, discount: int, link: str):
    """Sends formatted deal message directly to your Telegram channel."""
    message = (
        f"🔥 *LOOT DEAL ({discount}% OFF)* 🔥\n\n"
        f"📦 *Product:* {title}\n"
        f"💰 *Deal Price:* ₹{cur_price:,}\n"
        f"❌ *MRP:* ₹{mrp:,}\n"
        f"📉 *Save:* ₹{mrp - cur_price:,} ({discount}% off)\n\n"
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
        response = await client.post(telegram_url, json=payload, timeout=15.0)
        res_data = response.json()
        if res_data.get("ok"):
            print(f"[+] Posted to Telegram: {title[:35]}... ({discount}%)", flush=True)
        else:
            print(f"[-] Telegram API Error: {res_data}", flush=True)
    except Exception as e:
        print(f"[-] Failed to push deal to Telegram: {e}", flush=True)

async def scan_flipkart_page(client: httpx.AsyncClient, url: str):
    """Scrapes Flipkart search page, parses prices, and posts deals >= 50%."""
    try:
        resp = await client.get(url, headers=HEADERS, timeout=20.0, follow_redirects=True)
        if resp.status_code != 200:
            print(f"[-] Non-200 response from Flipkart: {resp.status_code}", flush=True)
            return

        soup = BeautifulSoup(resp.text, "html.parser")

        # Select standard Flipkart product cards
        cards = soup.select("div._1AtVbE, div._75nlfW, div[data-id]")

        for card in cards:
            # Extract product link
            link_tag = card.select_one("a[href*='/p/']")
            if not link_tag or not link_tag.get("href"):
                continue

            raw_href = link_tag["href"]
            product_url = f"https://www.flipkart.com{raw_href.split('?')[0]}"

            # Deduplication
            if product_url in seen_products:
                continue

            # Extract title
            title_tag = card.select_one("div._4rR01T, a.s1Q9rs, div.KzDlHZ, a.WKTcLC")
            title = title_tag.get_text(strip=True) if title_tag else "Flipkart Deal"

            # Extract pricing
            cur_price_tag = card.select_one("div._30jeq3, div.Nx9bqj")
            mrp_tag = card.select_one("div._3I9_wc, div.yRaY8j")

            if not cur_price_tag or not mrp_tag:
                continue

            cur_price = extract_numeric(cur_price_tag.get_text())
            mrp = extract_numeric(mrp_tag.get_text())

            if mrp > 0 and cur_price < mrp:
                discount = round(((mrp - cur_price) / mrp) * 100)

                if discount >= DISCOUNT_THRESHOLD:
                    seen_products.add(product_url)
                    await post_to_telegram(client, title, cur_price, mrp, discount, product_url)

    except Exception as err:
        print(f"[-] Error during page scan: {err}", flush=True)

# -------------------------------------------------------------
# 4. MAIN LOOP
# -------------------------------------------------------------
async def main():
    print("[*] Bot starting up...", flush=True)

    # Launch Render port listener on background daemon thread
    server_thread = threading.Thread(target=run_health_server, daemon=True)
    server_thread.start()
    print("[+] Render health check bound on port 10000.", flush=True)

    async with httpx.AsyncClient() as client:
        while True:
            print("[*] Running deal scan sweep...", flush=True)
            for search_url in SEARCH_URLS:
                await scan_flipkart_page(client, search_url)
                await asyncio.sleep(2)  # Short delay between category requests

            print(f"[*] Sweep complete. Sleeping for {CHECK_INTERVAL_SECONDS}s...", flush=True)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main())
