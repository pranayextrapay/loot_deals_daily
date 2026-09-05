import os
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8916500708:AAGxhpTfz8x9ifJcdiL7loHdnwM0Mch-UtY")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Daily_loot_deals25")
EXTRAPE_USER_ID = os.getenv("EXTRAPE_USER_ID", "3002631")

# High-discount deal search queries on Flipkart (50%+ off deals)
DEAL_SEARCH_URLS = [
    "https://www.flipkart.com/search?q=deals+of+the+day&marketplace=FLIPKART&p%5B%5D=facets.discount_range_v1%255B%255D%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=electronics+deals&marketplace=FLIPKART&p%5B%5D=facets.discount_range_v1%255B%255D%3D50%2525%2Bor%2Bmore",
    "https://www.flipkart.com/search?q=headphones+smartwatch+deals&marketplace=FLIPKART&p%5B%5D=facets.discount_range_v1%255B%255D%3D50%2525%2Bor%2Bmore"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
}

# In-memory record to prevent posting duplicate deals
posted_items = set()

def make_extrape_link(raw_flipkart_url: str) -> str:
    """Encodes Flipkart product link into your ExtraPe tracking link."""
    # Strip tracking and session query parameters
    clean_url = raw_flipkart_url.split("?")[0]
    encoded_url = urllib.parse.quote(clean_url, safe="")
    return f"https://links.extrape.com/rl/{EXTRAPE_USER_ID}?slug=flipkartearn&url={encoded_url}"

def send_telegram_deal(title: str, price: str, original_price: str, discount: str, affiliate_url: str, img_url: str = None) -> bool:
    """Sends deal caption and picture to the Telegram channel."""
    caption = (
        f"🔥 *FLIPKART LOOT DEAL* 🔥\n\n"
        f"📦 *{title}*\n\n"
        f"💰 *Deal Price:* ₹{price}  (~₹{original_price}~)\n"
        f"⚡ *Discount:* {discount} OFF\n\n"
        f"🛒 *Buy Now:* {affiliate_url}"
    )

    try:
        if img_url:
            endpoint = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            payload = {
                "chat_id": CHANNEL_ID,
                "photo": img_url,
                "caption": caption,
                "parse_mode": "Markdown"
            }
        else:
            endpoint = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": CHANNEL_ID,
                "text": caption,
                "parse_mode": "Markdown"
            }

        response = requests.post(endpoint, data=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"[!] Telegram API error: {e}")
        return False

def scrape_and_broadcast():
    print("[*] Starting scrape loop across Flipkart categories...")
    for target_url in DEAL_SEARCH_URLS:
        try:
            res = requests.get(target_url, headers=HEADERS, timeout=15)
            if res.status_code != 200:
                print(f"[!] Failed to fetch {target_url}, status code: {res.status_code}")
                continue

            soup = BeautifulSoup(res.content, "html.parser")
            
            # Locate product containers
            cards = soup.find_all("div", attrs={"data-id": True})
            for card in cards:
                product_id = card.get("data-id")
                if not product_id or product_id in posted_items:
                    continue

                # 1. Product Title
                title_elem = (
                    card.find("div", class_="KzDlHZ") or 
                    card.find("a", class_="wjcEIp") or 
                    card.find("a", title=True)
                )
                if not title_elem:
                    continue
                title = title_elem.get("title") or title_elem.text.strip()

                # 2. Pricing & Discounts
                price_elem = card.find("div", class_="Nx9bqj")
                old_price_elem = card.find("div", class_="yRaY8j")
                discount_elem = card.find("div", class_="UkUFwK")

                if not price_elem or not discount_elem:
                    continue

                price = price_elem.text.replace("₹", "").strip()
                old_price = old_price_elem.text.replace("₹", "").strip() if old_price_elem else "MRP"
                discount = discount_elem.text.replace("off", "").strip()

                # 3. Product URL
                anchor = card.find("a", href=True)
                if not anchor:
                    continue
                raw_product_url = "https://www.flipkart.com" + anchor["href"]

                # 4. Product Image
                img_tag = card.find("img", src=True)
                img_url = img_tag["src"] if img_tag else None

                # Generate affiliate link
                extrape_link = make_extrape_link(raw_product_url)

                # Send deal to channel
                if send_telegram_deal(title, price, old_price, discount, extrape_link, img_url):
                    print(f"[+] Posted deal: {title[:40]} | ₹{price} ({discount} OFF)")
                    posted_items.add(product_id)
                    time.sleep(5)  # Pause to avoid Telegram rate limits

        except Exception as err:
            print(f"[!] Error during scraping run: {err}")

    # Keep memory usage minimal
    if len(posted_items) > 2000:
        posted_items.clear()

if __name__ == "__main__":
    print("[✓] Deal bot initialized. Running continuous 24/7 worker...")
    while True:
        scrape_and_broadcast()
        # Scan every 10 minutes for new deals
        print("[*] Sleeping for 10 minutes until next scrape check...")
        time.sleep(600)
