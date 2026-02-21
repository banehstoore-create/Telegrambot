import os
import json
import telebot
import requests
from bs4 import BeautifulSoup
from flask import Flask, request
from telebot import types

# --- تنظیمات اولیه ---
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 6690559792 
CHANNEL_ID = "@banehstoore"
ADMIN_PV = "https://t.me/banehstoore_admin" 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

def extract_product_info(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        product_data = {}
        json_ld_tags = soup.find_all('script', type='application/ld+json')
        found_ld = False
        
        for tag in json_ld_tags:
            try:
                data = json.loads(tag.text)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get('@type') == 'Product':
                        product_data['title'] = item.get('name')
                        product_data['image'] = item.get('image')
                        if isinstance(product_data['image'], list): product_data['image'] = product_data['image'][0]
                        
                        offers = item.get('offers', {})
                        price = offers.get('price')
                        
                        # --- اصلاح قیمت (تبدیل ریال به تومان) ---
                        if price and str(price).isdigit():
                            toman_price = int(price) // 10  # حذف یک صفر برای تبدیل به تومان
                            product_data['price'] = f"{toman_price:,}" + " تومان"
                        else:
                            product_data['price'] = "تماس بگیرید"
                        
                        availability = offers.get('availability', '')
                        product_data['status'] = "✅ موجود در انبار" if ('InStock' in availability or 'موجود' in availability) else "❌ ناموجود"
                        found_ld = True
                        break
                if found_ld: break
            except: continue

        if not found_ld:
            product_data['title'] = soup.find('h1').text.strip() if soup.find('h1') else "محصول جدید"
            product_data['price'] = "استعلام تلفنی"
            product_data['status'] = "موجود"
            img_tag = soup.find('meta', property='og:image')
            product_data['image'] = img_tag['content'] if img_tag else None

        product_data['url'] = url
        return product_data
    except Exception:
        return None

def send_to_channel(data):
    caption = (
        f"🛍 **{data['title']}**\n\n"
        f"💰 قیمت: {data['price']}\n"
        f"📦 وضعیت: {data['status']}\n\n"
        f"🏁 بانه استور - انتخاب برتر شما\n"
        f"🆔 {CHANNEL_ID}"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔗 مشاهده در سایت", url=data['url']))
    markup.add(types.InlineKeyboardButton("🛒 ثبت سفارش (مشاوره)", url=ADMIN_PV))
    
    if data['image']:
        bot.send_photo(CHANNEL_ID, data['image'], caption=caption, parse_mode='Markdown', reply_markup=markup)
    else:
        bot.send_message(CHANNEL_ID, caption, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['start'])
def send_welcome(m):
    if m.from_user.id == ADMIN_ID:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("➕ افزودن محصول جدید"))
        bot.send_message(m.chat.id, "ادمین عزیز خوش آمدید. گزینه مورد نظر را انتخاب کنید:", reply_markup=markup)
    else:
        bot.send_message(m.chat.id, f"سلام! برای خرید به کانال ما بپیوندید:\n{CHANNEL_ID}")

@bot.message_handler(func=lambda m: m.text == "➕ افزودن محصول جدید")
def ask_for_link(m):
    if m.from_user.id == ADMIN_ID:
        bot.send_message(m.chat.id, "لطفاً لینک محصول را از سایت کپی کرده و اینجا بفرستید:")

@bot.message_handler(func=lambda m: True)
def handle_all_messages(m):
    if m.from_user.id == ADMIN_ID:
        if "http" in m.text:
            sent_msg = bot.reply_to(m, "⏳ در حال استخراج اطلاعات و تبدیل قیمت...")
            product_data = extract_product_info(m.text)
            if product_data:
                try:
                    send_to_channel(product_data)
                    bot.edit_message_text("✅ محصول با موفقیت و قیمت اصلاح شده ارسال شد.", m.chat.id, sent_msg.message_id)
                except Exception as e:
                    bot.edit_message_text(f"❌ خطا در ارسال به کانال: {e}", m.chat.id, sent_msg.message_id)
            else:
                bot.edit_message_text("❌ خطا در استخراج! لطفاً لینک را بررسی کنید.", m.chat.id, sent_msg.message_id)
    else:
        bot.reply_to(m, "🙏 دسترسی محدود به مدیریت.")

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
