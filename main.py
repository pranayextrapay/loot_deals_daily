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
        self.wfile.write(b"Bot is healthy and monitoring price drops.")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# -------------------------------------------------------------
# 2. BOT CONFIGURATION
# -------------------------------------------------------------
BOT_TOKEN = "8916500708:AAF4bTn5L9k7kabQD-xokUPCF16-OzWfGfU"
CHANNEL_USERNAME = "@Daily_loot_deals25"

# Trigger settings
DISCOUNT_THRESHOLD = 70          # Minimum baseline discount %
CHECK_INTERVAL_SECONDS = 180     # 3-minute sweep
MESSAGE_DELAY_SECONDS = 3.5      # Telegram anti-flood wait

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

# Stores product_url: last_known_price to track genuine drops
price_history = {}

def extract_numeric(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0

async def post_deal_to_telegram(session: AsyncSession, title: str, cur_price: int, mrp: int, discount: int, link: str, img_url: str):
    """Posts in the clean channel image + caption format."""
    caption = (
        f"{title}\n\n"
        f"{link}\n\n"
        f"@{cur_price}₹ ({discount}% Off)"
    )

    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHANNEL_USERNAME,
        "photo": img_url,
        "caption": caption
    }

    try:
        resp = await session.post(telegram_url, json=payload, timeout=15.0)
        res_data = resp.json()

        # Fallback to text message if photo URL is blocked or expired
        if not res_data.get("ok"):
            text_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            text_payload = {
                "chat_id": CHANNEL_USERNAME,
                "text": f"{title}\n\n{link}\n\n@{cur_price}₹ ({discount}% Off)",
                "disable_web_page_preview": False
            }
            resp = await session.post(text_url, json=text_payload, timeout=15.0)
            res_data = resp.json()

        if res_data.get("ok"):
            print(f"[+] Broadcasted deal: {title[:25]}... (₹{cur_price})", flush=True)
            await asyncio.sleep(MESSAGE_DELAY_SECONDS)
        elif res_data.get("error_code") == 429:
            retry_after = res_data.get("parameters", {}).get("retry_after", 20)
            print(f"[!] Rate limit hit. Pausing {retry_after}s...", flush=True)
            await asyncio.sleep(retry_after + 2)
            await session.post(telegram_url, json=payload, timeout=15.0)
        else:
            print(f"[-] Telegram dispatch rejected: {res_data}", flush=True)
    except Exception as e:
        print(f"[-] Dispatch error: {e}", flush=True)

async def scan_flipkart_page(session: AsyncSession, url: str):
    category = url.split("q=")[1].split("&")[0]
    try:
        resp = await session.get(url, headers=HEADERS, impersonate="chrome124", timeout=20.0)
        if resp.status_code != 200:
            print(f"[-] HTTP {resp.status_code} on {category}", flush=True)
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div[data-id], div.slAVV4, div._75nlfW, div._1AtVbE")
        deals_dispatched = 0

        for card in cards:
            link_tag = card.select_one("a[href*='/p/']")
            if not link_tag or not link_tag.get("href"):
                continue

            raw_href = link_tag["href"]
            clean_url = f"https://www.flipkart.com{raw_href.split('?')[0]}"

            card_text = card.get_text(" ", strip=True)

            # Stock check
            if any(term in card_text.lower() for term in ["out of stock", "sold out", "currently unavailable"]):
                continue

            # Price extraction
            cur_price_el = card.select_one("div.Nx9bqj, div._30jeq3")
            cur_price = extract_numeric(cur_price_el.get_text()) if cur_price_el else 0

            if cur_price == 0:
                price_match = re.search(r"₹([\d,]+)", card_text)
                if price_match:
                    cur_price = extract_numeric(price_match.group(1))

            if cur_price == 0:
                continue

            # Discount extraction
            discount = 0
            disc_match = re.search(r"(\d+)%\s*off", card_text, re.IGNORECASE)
            if disc_match:
                discount = int(disc_match.group(1))

            mrp_el = card.select_one("div.yRaY8j, div._3I9_wc")
            mrp = extract_numeric(mrp_el.get_text()) if mrp_el else 0

            if (mrp <= cur_price or mrp == 0) and discount > 0 and discount < 100:
                mrp = round(cur_price / (1 - (discount / 100)))

            if discount == 0 and mrp > cur_price:
                discount = round(((mrp - cur_price) / mrp) * 100)

            # Image extraction
            img_tag = card.select_one("img._53G40d, img.DByuf4, img._396cs4, img")
            img_url = img_tag.get("src") or img_tag.get("data-src") if img_tag else ""

            # Title extraction
            title_tag = card.select_one("div.KzDlHZ, a.wjcEIp, a.WKTcLC, div._4rR01T, a.s1Q9rs")
            title = title_tag.get_text(strip=True) if title_tag else (link_tag.get("title") or "Flipkart Loot Deal")

            # GENUINE PRICE DROP DETECTION
            # Case 1: First time bot sees this item, check if it already meets the baseline loot criteria
            # Case 2: If seen before, ONLY trigger if price has actively dropped below previous observation
            is_genuine_drop = False

            if clean_url not in price_history:
                if discount >= DISCOUNT_THRESHOLD:
                    is_genuine_drop = True
            else:
                prev_price = price_history[clean_url]
                if cur_price < prev_price:
                    is_genuine_drop = True
                    print(f"[*] Price drop detected! Was ₹{prev_price} -> Now ₹{cur_price}", flush=True)

            # Update cache with latest observed price
            price_history[clean_url] = cur_price

            if is_genuine_drop and img_url:
                deals_dispatched += 1
                await post_deal_to_telegram(session, title, cur_price, mrp, discount, clean_url, img_url)

        print(f"[*] {category}: Processed {len(cards)} items -> Dispatched {deals_dispatched} genuine drops.", flush=True)

    except Exception as err:
        print(f"[-] Scrape error on {category}: {err}", flush=True)

async def main():
    print("[*] Bot running: Image cards + genuine price-drop tracking enabled...", flush=True)
    threading.Thread(target=run_health_server, daemon=True).start()
    print("[+] Port 10000 bound.", flush=True)

    async with AsyncSession() as session:
        while True:
            print("[*] Running sweep...", flush=True)
            for url in SEARCH_URLS:
                await scan_flipkart_page(session, url)
                await asyncio.sleep(3)

            print(f"[*] Sweep done. Pausing for {CHECK_INTERVAL_SECONDS}s...", flush=True)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main())
