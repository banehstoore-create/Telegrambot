import os
import json
import telebot
import requests
from bs4 import BeautifulSoup
from flask import Flask, request

# --- تنظیمات اولیه ---
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 6690559792  # آیدی عددی شما
CHANNEL_ID = "@banehstoore"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- توابع استخراج اطلاعات (Mixin Optimized) ---

def extract_product_info(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        product_data = {}
        
        # استخراج اطلاعات از JSON-LD (استاندارد میکسین)
        json_ld_tags = soup.find_all('script', type='application/ld+json')
        found_ld = False
        
        for tag in json_ld_tags:
            try:
                data = json.loads(tag.text)
                # بررسی اینکه آیا این تگ مربوط به محصول است
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get('@type') == 'Product':
                        product_data['title'] = item.get('name')
                        product_data['image'] = item.get('image')
                        if isinstance(product_data['image'], list):
                            product_data['image'] = product_data['image'][0]
                        
                        offers = item.get('offers', {})
                        price = offers.get('price')
                        product_data['price'] = f"{int(price):,}" if price and str(price).isdigit() else "تماس بگیرید"
                        
                        availability = offers.get('availability', '')
                        if 'InStock' in availability or 'موجود' in availability:
                            product_data['status'] = "✅ موجود در انبار بانه استور"
                        else:
                            product_data['status'] = "❌ ناموجود"
                        
                        found_ld = True
                        break
                if found_ld: break
            except:
                continue

        # روش پشتیبان (اگر JSON-LD یافت نشد)
        if not found_ld:
            product_data['title'] = soup.find('h1').text.strip() if soup.find('h1') else "محصول جدید"
            og_price = soup.find('meta', property='product:price:amount')
            product_data['price'] = og_price['content'] if og_price else "نامشخص"
            product_data['status'] = "جهت استعلام موجودی پیام دهید"
            img_tag = soup.find('meta', property='og:image')
            product_data['image'] = img_tag['content'] if img_tag else None

        product_data['url'] = url
        return product_data
    except Exception as e:
        print(f"Extraction Error: {e}")
        return None

def send_to_channel(data):
    # کپشن‌نویسی اتوماتیک
    caption = (
        f"🛍 **{data['title']}**\n\n"
        f"💰 قیمت: {data['price']} تومان\n"
        f"📦 وضعیت: {data['status']}\n\n"
        f"🔗 مشاهده جزئیات و خرید آنلاین:\n"
        f"{data['url']}\n\n"
        f"🏁 بانه استور - خرید هوشمندانه از بانه\n"
        f"🆔 {CHANNEL_ID}"
    )
    
    if data['image']:
        bot.send_photo(CHANNEL_ID, data['image'], caption=caption, parse_mode='Markdown')
    else:
        bot.send_message(CHANNEL_ID, caption, parse_mode='Markdown')

# --- بخش مدیریت پیام‌ها ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(m):
    if m.from_user.id == ADMIN_ID:
        msg = "خوش آمدید ادمین عزیز. لینک محصول را بفرستید تا در کانال منتشر شود."
    else:
        msg = f"سلام! به ربات بانه استور خوش آمدید. 😊\n\nبرای مشاهده محصولات به کانال ما بپیوندید:\n{CHANNEL_ID}"
    bot.reply_to(m, msg)

@bot.message_handler(func=lambda m: True)
def handle_messages(m):
    # تفکیک دسترسی
    if m.from_user.id == ADMIN_ID:
        # شناسایی لینک از هر دو دامنه شما
        if "banehstoore.ir" in m.text or "banehservice.com" in m.text:
            sent_msg = bot.reply_to(m, "در حال استخراج اطلاعات از میکسین... ⏳")
            
            product_data = extract_product_info(m.text)
            if product_data:
                try:
                    send_to_channel(product_data)
                    bot.edit_message_text("✅ با موفقیت به کانال ارسال شد.", m.chat.id, sent_msg.message_id)
                except Exception as e:
                    bot.edit_message_text(f"❌ خطا در ارسال: {e}", m.chat.id, sent_msg.message_id)
            else:
                bot.edit_message_text("❌ متاسفانه اطلاعات محصول یافت نشد.", m.chat.id, sent_msg.message_id)
        else:
            bot.reply_to(m, "لطفاً یک لینک معتبر محصول بفرستید.")
    else:
        # پاسخ به کاربران عادی
        bot.reply_to(m, "🙏 عذرخواهی می‌کنیم، این بخش مخصوص مدیریت فروشگاه است.")

# --- تنظیمات Webhook و سرور ---

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'Forbidden', 403

@app.route('/')
def index():
    return "BanehStoore Bot is Active!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
