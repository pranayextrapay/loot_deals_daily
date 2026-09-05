import os
import re
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from curl_cffi.requests import AsyncSession

# -------------------------------------------------------------
# 1. RENDER PORT LISTENER
# -------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# -------------------------------------------------------------
# 2. BOT SETTINGS
# -------------------------------------------------------------
BOT_TOKEN = "8916500708:AAGxhpTfz8x9ifJcdiL7loHdnwM0Mch-UtY"
CHANNEL_USERNAME = "@Daily_loot_deals25"
DISCOUNT_THRESHOLD = 50  # 50% or higher
CHECK_INTERVAL_SECONDS = 60  # Check every 60 seconds

SEARCH_QUERIES = [
    "deals",
    "electronics",
    "smartwatches",
    "headphones",
    "shoes"
]

seen_products = set()

async def post_to_telegram(session: AsyncSession, title: str, cur_price: int, mrp: int, discount: int, link: str):
    message = (
        f"🔥 *LOOT DEAL ({discount}% OFF)* 🔥\n\n"
        f"📦 *Product:* {title}\n"
        f"💰 *Deal Price:* ₹{cur_price:,}\n"
        f"❌ *MRP:* ₹{mrp:,}\n"
        f"📉 *You Save:* ₹{mrp - cur_price:,} ({discount}% OFF)\n\n"
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

async def scan_flipkart_query(session: AsyncSession, query: str):
    url = f"https://www.flipkart.com/api/4/page/fetch"
    payload = {
        "pageUri": f"/search?q={query}&p%5B%5D=facets.discount_range_v1%3D50%2525%2Bor%2Bmore",
        "locationContext": {"pincode": "500001"}
    }
    headers = {
        "X-User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "Accept": "*/*"
    }

    try:
        resp = await session.post(url, json=payload, headers=headers, impersonate="chrome", timeout=15.0)
        if resp.status_code != 200:
            # Fallback to direct web scraping if API endpoint shifts
            return

        data = resp.json()
        slots = data.get("RESPONSE", {}).get("slots", [])
        
        deals_found = 0
        for slot in slots:
            widget = slot.get("widget", {})
            elements = widget.get("data", {}).get("products", [])
            
            for p in elements:
                p_val = p.get("productInfo", {}).get("value", {})
                pricing = p_val.get("pricing", {})
                
                cur_price = pricing.get("finalPrice", {}).get("value", 0)
                mrp = pricing.get("mrp", {}).get("value", 0)
                discount = pricing.get("totalDiscount", 0)
                
                title = p_val.get("titles", {}).get("title", "Loot Deal")
                base_url = p_val.get("smartUrl", "")
                
                if not base_url:
                    continue
                    
                full_url = f"https://www.flipkart.com{base_url.split('?')[0]}"
                
                if full_url in seen_products:
                    continue

                if discount >= DISCOUNT_THRESHOLD or (mrp > 0 and ((mrp - cur_price) / mrp * 100) >= DISCOUNT_THRESHOLD):
                    calc_discount = discount or round(((mrp - cur_price) / mrp) * 100)
                    seen_products.add(full_url)
                    deals_found += 1
                    await post_to_telegram(session, title, cur_price, mrp, calc_discount, full_url)

        print(f"[*] Found & posted {deals_found} deals for '{query}'.", flush=True)

    except Exception as err:
        print(f"[-] Scan error on '{query}': {err}", flush=True)

async def main():
    print("[*] Bot active with JSON API parser...", flush=True)
    threading.Thread(target=run_health_server, daemon=True).start()
    print("[+] Health port 10000 bound.", flush=True)

    async with AsyncSession() as session:
        while True:
            print("[*] Starting sweep...", flush=True)
            for q in SEARCH_QUERIES:
                await scan_flipkart_query(session, q)
                await asyncio.sleep(2)

            print(f"[*] Sweep done. Pausing for {CHECK_INTERVAL_SECONDS}s...", flush=True)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main())
