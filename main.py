import os
import re
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
        self.wfile.write(b"Bot is alive and monitoring 80%+ deals.")

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

# Strict 80%+ filter
DISCOUNT_THRESHOLD = 80  
CHECK_INTERVAL_SECONDS = 120
MESSAGE_DELAY_SECONDS = 3.5  # Prevents Telegram rate-limiting

# Expanded categories with 80%+ pre-filters
SEARCH_URLS = [
    "https://www.flipkart.com/search?q=smartwatches&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=headphones&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=shoes&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=t-shirts&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=kitchen+appliances&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=home+decor&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=trimmers&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=backpacks&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=sunglasses&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=powerbank&p%5B%5D=facets.discount_range_v1%3D80%2525%2Bor%2Bmore"
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
        f"⚡ *MEGA 80%+ LOOT DEAL* ⚡\n\n"
        f"📦 *Product:* {title}\n"
        f"💰 *Deal Price:* ₹{cur_price:,}\n"
        f"{mrp_text}"
        f"💥 *Discount:* {discount}% OFF\n\n"
        f"🛒 [Order on Flipkart]({link})"
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
            print(f"[+] Posted: {title[:28]}... ({discount}%)", flush=True)
            await asyncio.sleep(MESSAGE_DELAY_SECONDS)
        elif res_data.get("error_code") == 429:
            retry_after = res_data.get("parameters", {}).get("retry_after", 20)
            print(f"[!] Rate limit hit. Pausing {retry_after}s...", flush=True)
            await asyncio.sleep(retry_after + 2)
            await session.post(telegram_url, json=payload, timeout=15.0)
        else:
            print(f"[-] Telegram Error: {res_data}", flush=True)
    except Exception as e:
        print(f"[-] Dispatch error: {e}", flush=True)

async def scan_flipkart_page(session: AsyncSession, url: str):
    category = url.split("q=")[1].split("&")[0]
    try:
        resp = await session.get(url, headers=HEADERS, impersonate="chrome124", timeout=20.0)
        if resp.status_code != 200:
            print(f"[-] HTTP {resp.status_code} for {category}", flush=True)
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div[data-id], div.slAVV4, div._75nlfW, div._1AtVbE")
        deals_posted = 0

        for card in cards:
            link_tag = card.select_one("a[href*='/p/']")
            if not link_tag or not link_tag.get("href"):
                continue

            raw_href = link_tag["href"]
            clean_url = f"https://www.flipkart.com{raw_href.split('?')[0]}"
            if clean_url in seen_products:
                continue

            card_text = card.get_text(" ", strip=True)
            prices = re.findall(r"₹([\d,]+)", card_text)
            if not prices:
                continue

            cur_price = extract_numeric(prices[0])
            mrp = extract_numeric(prices[1]) if len(prices) > 1 else 0

            disc_match = re.search(r"(\d+)%\s*off", card_text, re.IGNORECASE)
            discount = int(disc_match.group(1)) if disc_match else 0

            if discount == 0 and mrp > cur_price and mrp > 0:
                discount = round(((mrp - cur_price) / mrp) * 100)

            # Strict 80%+ evaluation
            if discount >= DISCOUNT_THRESHOLD and cur_price > 0:
                title_tag = card.select_one("div.KzDlHZ, a.wjcEIp, a.WKTcLC, div._4rR01T, a.s1Q9rs")
                title = title_tag.get_text(strip=True) if title_tag else (link_tag.get("title") or "Flipkart Loot Deal")

                seen_products.add(clean_url)
                deals_posted += 1
                await post_to_telegram(session, title, cur_price, mrp, discount, clean_url)

        print(f"[*] {category}: Found {len(cards)} items -> Dispatched {deals_posted} deals.", flush=True)

    except Exception as err:
        print(f"[-] Scan error on {category}: {err}", flush=True)

async def main():
    print("[*] Bot running with 80%+ strict filter across 10 categories...", flush=True)
    threading.Thread(target=run_health_server, daemon=True).start()
    print("[+] Port 10000 bound.", flush=True)

    async with AsyncSession() as session:
        while True:
            print("[*] Running category sweep...", flush=True)
            for url in SEARCH_URLS:
                await scan_flipkart_page(session, url)
                await asyncio.sleep(4)  # Politeness interval between categories

            print(f"[*] Sweep complete. Pausing for {CHECK_INTERVAL_SECONDS}s...", flush=True)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main())
