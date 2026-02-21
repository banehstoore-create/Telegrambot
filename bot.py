import os
import telebot
import requests
from bs4 import BeautifulSoup
from flask import Flask, request

# تنظیمات اولیه از Environment Variables
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 6690559792 
CHANNEL_ID = "@banehstoore"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- توابع کمکی (استخراج اطلاعات) ---

def extract_product_info(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        title = soup.find('h1').text.strip() if soup.find('h1') else "بدون نام"
        price = "نامشخص"
        price_tag = soup.select_one('.price ins .woocommerce-Price-amount')
        if price_tag:
            price = price_tag.text.strip()
            
        image_tag = soup.select_one('.woocommerce-product-gallery__image img')
        image_url = image_tag['src'] if image_tag else None
        
        return {"title": title, "price": price, "image": image_url, "url": url}
    except Exception as e:
        print(f"Error extracting: {e}")
        return None

def send_to_channel(data):
    caption = f"🌟 {data['title']}\n\n💰 قیمت: {data['price']}\n\n🔗 لینک خرید:\n{data['url']}\n\n🆔 {CHANNEL_ID}"
    if data['image']:
        bot.send_photo(CHANNEL_ID, data['image'], caption=caption)
    else:
        bot.send_message(CHANNEL_ID, caption)

# --- بخش مدیریت پیام‌ها ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(m):
    welcome_text = (
        "سلام! به ربات بانه استور خوش آمدید. 😊\n\n"
        "این ربات جهت مدیریت محصولات کانال طراحی شده است.\n"
        "اگر مشتری هستید، می‌توانید از محصولات کانال ما دیدن کنید: \n" + CHANNEL_ID
    )
    bot.reply_to(m, welcome_text)

@bot.message_handler(func=lambda m: True)
def handle_messages(m):
    # چک کردن ادمین
    if m.from_user.id == ADMIN_ID:
        if "banehservice.com" in m.text:
            sent_msg = bot.reply_to(m, "ادمین گرامی، در حال استخراج و ارسال به کانال... ⏳")
            
            product_data = extract_product_info(m.text)
            if product_data:
                try:
                    send_to_channel(product_data)
                    bot.edit_message_text("✅ محصول با موفقیت در کانال منتشر شد.", m.chat.id, sent_msg.message_id)
                except Exception as e:
                    bot.edit_message_text(f"❌ خطا در ارسال به کانال: {e}", m.chat.id, sent_msg.message_id)
            else:
                bot.edit_message_text("❌ خطا در استخراج اطلاعات از سایت.", m.chat.id, sent_msg.message_id)
        else:
            bot.reply_to(m, "ادمین عزیز، برای انتشار محصول لطفاً لینک سایت بانه سرویس را بفرستید.")
    else:
        # پاسخ به کاربران عادی
        bot.reply_to(m, "عذرخواهی می‌کنم، ارسال محصول به کانال فقط توسط مدیریت انجام می‌شود. 🙏")

# --- تنظیمات Webhook و Flask ---

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'Error', 403

@app.route('/')
def index():
    return "Bot is Running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
