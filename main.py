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
        self.wfile.write(b"Bot is healthy and scanning.")

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
DISCOUNT_THRESHOLD = 50
CHECK_INTERVAL_SECONDS = 180

# Targeted search URLs pre-filtered for 50%+ discounts
SEARCH_URLS = [
    "https://www.flipkart.com/search?q=deals&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=headphones&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=smartwatches&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=t-shirts&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore"
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
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
        # Impersonate Chrome browser fingerprint to bypass Cloudflare / Akamai 403
        resp = await session.get(url, headers=HEADERS, impersonate="chrome", timeout=20.0)
        
        if resp.status_code != 200:
            print(f"[-] Blocked by Flipkart (Status {resp.status_code})", flush=True)
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div._1AtVbE, div._75nlfW, div[data-id], div.slAVV4")

        found_in_page = 0
        for card in cards:
            link_tag = card.select_one("a[href*='/p/']")
            if not link_tag or not link_tag.get("href"):
                continue

            raw_href = link_tag["href"]
            product_url = f"https://www.flipkart.com{raw_href.split('?')[0]}"

            if product_url in seen_products:
                continue

            title_tag = card.select_one("div._4rR01T, a.s1Q9rs, div.KzDlHZ, a.WKTcLC")
            title = title_tag.get_text(strip=True) if title_tag else "Flipkart Loot Deal"

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
                    found_in_page += 1
                    await post_to_telegram(session, title, cur_price, mrp, discount, product_url)

        print(f"[*] Found & posted {found_in_page} deals from page.", flush=True)

    except Exception as err:
        print(f"[-] Error parsing page: {err}", flush=True)

async def main():
    print("[*] Bot starting with Chrome TLS impersonation...", flush=True)

    threading.Thread(target=run_health_server, daemon=True).start()
    print("[+] Render port listener active.", flush=True)

    async with AsyncSession() as session:
        while True:
            print("[*] Running Flipkart sweep...", flush=True)
            for search_url in SEARCH_URLS:
                await scan_flipkart_page(session, search_url)
                await asyncio.sleep(3)

            print(f"[*] Sweep complete. Sleeping for {CHECK_INTERVAL_SECONDS}s...", flush=True)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main())
