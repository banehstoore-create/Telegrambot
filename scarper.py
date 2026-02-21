import requests
from bs4 import BeautifulSoup

def scrape_product(url):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    res = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(res.text, "html.parser")

    title = soup.find("h1").get_text(strip=True)

    price_tag = soup.select_one(".price")
    price = price_tag.get_text(strip=True) if price_tag else "تماس بگیرید"

    img = soup.find("meta", property="og:image")
    image_url = img["content"] if img else None

    stock = "✅ موجود"
    if "ناموجود" in soup.text:
        stock = "❌ ناموجود"

    caption = f"""
🛒 {title}

💰 قیمت: {price}
📦 وضعیت: {stock}

🔗 خرید از بانه استور
"""

    return {
        "title": title,
        "price": price,
        "stock": stock,
        "image": image_url,
        "caption": caption
    }
