import os
import json
import telebot
import requests
import psycopg2
from bs4 import BeautifulSoup
from flask import Flask, request
from telebot import types

# --- تنظیمات اولیه ---
TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_ID = 6690559792 
CHANNEL_ID = "@banehstoore"
ADMIN_PV = "https://t.me/banehstoore_admin"

bot = telebot.TeleBot(TOKEN)
# برای کارکرد صحیح ثبت‌نام در حالت Webhook
bot.enable_save_next_step_handlers(delay=2)
bot.load_next_step_handlers()

app = Flask(__name__)

# --- مدیریت دیتابیس (Neon) ---
def get_db_connection():
    # اصلاح پروتکل برای سازگاری با پایتون
    url = DATABASE_URL
    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url)

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                full_name TEXT,
                phone_number TEXT
            )
        ''')
        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Database Init Error: {e}")

# اجرای اولیه برای ساخت جدول
if DATABASE_URL:
    init_db()

# --- توابع استخراج اطلاعات محصول (Mixin) ---
def extract_product_info(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        product_data = {}
        json_ld_tags = soup.find_all('script', type='application/ld+json')
        
        for tag in json_ld_tags:
            try:
                data = json.loads(tag.text)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get('@type') == 'Product':
                        product_data['title'] = item.get('name')
                        img = item.get('image')
                        product_data['image'] = img[0] if isinstance(img, list) else img
                        
                        offers = item.get('offers', {})
                        price = offers.get('price')
                        if price and str(price).isdigit():
                            product_data['price'] = f"{int(price)//10:,} تومان"
                        else:
                            product_data['price'] = "تماس بگیرید"
                        
                        av = offers.get('availability', '')
                        product_data['status'] = "✅ موجود" if 'InStock' in av or 'موجود' in av else "❌ ناموجود"
                        product_data['url'] = url
                        return product_data
            except: continue
        return None
    except: return None

def send_to_channel(data):
    caption = f"🛍 **{data['title']}**\n\n💰 قیمت: {data['price']}\n📦 وضعیت: {data['status']}\n\n🏁 بانه استور\n🆔 {CHANNEL_ID}"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔗 مشاهده در سایت", url=data['url']))
    markup.add(types.InlineKeyboardButton("🛒 ثبت سفارش", url=ADMIN_PV))
    
    if data.get('image'):
        bot.send_photo(CHANNEL_ID, data['image'], caption=caption, parse_mode='Markdown', reply_markup=markup)
    else:
        bot.send_message(CHANNEL_ID, caption, parse_mode='Markdown', reply_markup=markup)

# --- هندلرهای تلگرام (ثبت‌نام مشتری و پنل ادمین) ---

@bot.message_handler(commands=['start'])
def welcome(m):
    user_id = m.from_user.id
    
    if user_id == ADMIN_ID:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("➕ افزودن محصول جدید")
        return bot.send_message(m.chat.id, "خوش آمدید ادمین عزیز. محصول جدیدی دارید؟", reply_markup=markup)

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            bot.send_message(m.chat.id, f"سلام {user[0]} عزیز! به بانه استور خوش آمدید. ✨\nمحصولات جدید را در کانال دنبال کنید: {CHANNEL_ID}")
        else:
            msg = bot.send_message(m.chat.id, "سلام! به بانه استور خوش آمدید. 😊\nبرای ثبت‌نام و مشاهده قیمت‌ها، لطفاً نام و نام خانوادگی خود را وارد کنید:")
            bot.register_next_step_handler(msg, save_name)
    except Exception as e:
        bot.send_message(m.chat.id, "خوش آمدید! برای مشاهده محصولات وارد کانال شوید.")
        print(f"User Check Error: {e}")

def save_name(m):
    if not m.text or m.text.startswith('/'):
        msg = bot.send_message(m.chat.id, "لطفاً یک نام معتبر وارد کنید:")
        return bot.register_next_step_handler(msg, save_name)
    
    full_name = m.text
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(types.KeyboardButton("📱 ارسال شماره موبایل", request_contact=True))
    msg = bot.send_message(m.chat.id, f"ممنون {full_name}. برای تکمیل ثبت‌نام، شماره موبایل خود را ارسال کنید:", reply_markup=markup)
    bot.register_next_step_handler(msg, save_phone, full_name)

def save_phone(m, full_name):
    if m.contact:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s, %s, %s)", 
                        (m.from_user.id, full_name, m.contact.phone_number))
            conn.commit()
            cur.close()
            conn.close()
            bot.send_message(m.chat.id, "ثبت‌نام شما با موفقیت انجام شد! ✅", reply_markup=types.ReplyKeyboardRemove())
        except:
            bot.send_message(m.chat.id, "خطا در ذخیره اطلاعات. لطفاً دوباره /start بزنید.")
    else:
        bot.send_message(m.chat.id, "لطفاً فقط از دکمه 'ارسال شماره موبایل' استفاده کنید.")

@bot.message_handler(func=lambda m: m.text == "➕ افزودن محصول جدید")
def admin_prompt(m):
    if m.from_user.id == ADMIN_ID:
        bot.send_message(m.chat.id, "لطفاً لینک محصول را بفرستید:")

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and "http" in m.text)
def admin_process(m):
    sent = bot.reply_to(m, "⏳ در حال استخراج و ارسال به کانال...")
    data = extract_product_info(m.text)
    if data:
        send_to_channel(data)
        bot.edit_message_text("✅ محصول با موفقیت منتشر شد.", m.chat.id, sent.message_id)
    else:
        bot.edit_message_text("❌ خطا! اطلاعات محصول یافت نشد.", m.chat.id, sent.message_id)

# --- تنظیمات Flask و Webhook ---

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