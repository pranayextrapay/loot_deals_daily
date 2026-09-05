# 🛒 Flipkart Loot Deals 24/7 Telegram Bot

An automated Python worker that monitors Flipkart for steep discounts (≥50% OFF), generates ExtraPe affiliate tracking redirects, and broadcasts formatted deal cards to a Telegram channel.

---

## ⚡ Features

* **Autonomous Scraping:** Periodically monitors Flipkart search queries for live 50%+ discounts and Daily Loot offers.
* **Affiliate Tagging:** Converts clean Flipkart product URLs into tracked ExtraPe links (`links.extrape.com`) on the fly.
* **Deduplication:** Maintains an in-memory cache of previously posted product IDs to avoid duplicate alerts.
* **Rich Telegram Alerts:** Formats posts with product titles, deal prices, MRP discounts, and direct product images.
* **Cloud Ready:** Structured to deploy directly as a continuous Background Worker on platforms like Render.

---

## 🛠️ Tech Stack

* **Language:** Python 3.10+
* **Libraries:** `requests`, `beautifulsoup4`
* **Platform APIs:** Telegram Bot API
* **Affiliate Gateway:** ExtraPe

---

## 📂 Project Structure

```text
├── main.py              # Scraper, affiliate converter, and Telegram poster
├── requirements.txt     # Python dependencies
├── Procfile             # Process configuration for Render deployment
└── README.md            # Project documentation
