import telebot
from telebot import types
import requests
from bs4 import BeautifulSoup
import re
import os
from flask import Flask, request

# ================== تنظیمات ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = "@banehstoore"
WHATSAPP = "09180514202"
ADMIN_ID = 6690559792

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ================== منوی شروع ==================
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🛒 محصولات", "📞 پشتیبانی")

    bot.send_message(
        message.chat.id,
        "👋 به ربات فروشگاه بانه استور خوش آمدید\n"
        "لطفاً از منوی زیر استفاده کنید:",
        reply_markup=markup
    )

# ================== پشتیبانی ==================
@bot.message_handler(func=lambda m: m.text == "📞 پشتیبانی")
def support(message):
    markup = types.InlineKeyboardMarkup(row_width=2)

    markup.add(
        types.InlineKeyboardButton("📲 واتساپ", url="https://wa.me/98" + WHATSAPP[1:]),
        types.InlineKeyboardButton("💬 تلگرام", url="https://t.me/share/url?text=سلام،%20برای%20پشتیبانی%20پیام%20می‌دهم")
    )

    bot.send_message(
        message.chat.id,
        "📞 ارتباط با پشتیبانی بانه استور:",
        reply_markup=markup
    )

# ================== دسته‌بندی محصولات ==================
@bot.message_handler(func=lambda m: m.text == "🛒 محصولات")
def products(message):
    markup = types.InlineKeyboardMarkup(row_width=2)

    markup.add(
        types.InlineKeyboardButton("☕ اسپرسوساز", url="https://banehstoore.ir/product-category/espresso-maker"),
        types.InlineKeyboardButton("🍟 سرخ‌کن", url="https://banehstoore.ir/product-category/air-fryer"),
        types.InlineKeyboardButton("🥘 لوازم پخت‌وپز", url="https://banehstoore.ir/product-category/cookware"),
        types.InlineKeyboardButton("🧹 جاروبرقی", url="https://banehstoore.ir/product-category/vacuum-cleaner"),
        types.InlineKeyboardButton("🍲 غذاساز و خردکن", url="https://banehstoore.ir/product-category/food-processor"),
        types.InlineKeyboardButton("🔥 سماور برقی", url="https://banehstoore.ir/product-category/electric-samovar"),
        types.InlineKeyboardButton("🛍 مشاهده همه محصولات", url="https://banehstoore.ir")
    )

    bot.send_message(
        message.chat.id,
        "🛒 دسته‌بندی محصولات بانه استور:",
        reply_markup=markup
    )

# ================== دریافت اطلاعات محصول ==================
def fetch_product(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    title = soup.find("h1").get_text(strip=True)

    image = None
    og = soup.find("meta", property="og:image")
    if og:
        image = og.get("content")

    price = "تماس بگیرید"
    for span in soup.find_all("span"):
        txt = span.get_text(strip=True).replace(",", "")
        if txt.isdigit() and len(txt) >= 5:
            price = span.get_text(strip=True) + " تومان"
            break

    stock = "✅ موجود"
    if "ناموجود" in soup.text:
        stock = "❌ ناموجود"

    return title, image, price, stock

# ================== ارسال محصول به کانال ==================
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and re.search(r'https?://banehstoore.ir', m.text or ""))
def handle_product_link(message):
    bot.send_message(message.chat.id, "⏳ در حال پردازش لینک محصول...")

    try:
        title, image, price, stock = fetch_product(message.text)

        caption = f"""
🛍 *{title}*

💰 قیمت: {price}
📦 وضعیت: {stock}

🚚 ارسال سریع  
💯 ضمانت اصالت  
🤝 خرید مطمئن از بانه استور
"""

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🛒 خرید محصول", url=message.text),
            types.InlineKeyboardButton("📲 واتساپ", url=f"https://wa.me/98{WHATSAPP[1:]}")
        )

        bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=image,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=markup
        )

        bot.send_message(message.chat.id, "✅ محصول با موفقیت در کانال منتشر شد")

    except Exception as e:
        print("ERROR:", e)
        bot.send_message(message.chat.id, "❌ خطا در پردازش محصول")

# ================== پیام پیش‌فرض ==================
@bot.message_handler(func=lambda m: True)
def other(message):
    bot.send_message(message.chat.id, "👇 لطفاً از دکمه‌های منو استفاده کنید")

# ================== webhook ==================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

@app.route('/')
def home():
    return "Bot is running", 200

# ================== اجرا ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))