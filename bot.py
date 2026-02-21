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
app = Flask(__name__)

# --- مدیریت دیتابیس (Neon) ---
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
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
    except Exception as e:
        print(f"Database Init Error: {e}")

def get_user(user_id):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        return user
    except: return None

def register_user(user_id, full_name, phone):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s, %s, %s)", 
                    (user_id, full_name, phone))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Register Error: {e}")

# اجرای اولیه دیتابیس
if DATABASE_URL:
    init_db()

# --- توابع استخراج اطلاعات محصول ---
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
                        product_data['image'] = item.get('image')[0] if isinstance(item.get('image'), list) else item.get('image')
                        offers = item.get('offers', {})
                        price = offers.get('price')
                        # تبدیل ریال به تومان
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
    caption = f"🛍 **{data['title']}**\n\n💰 قیمت: {data['price']}\n📦 وضعیت: {data['status']}\n\n🆔 {CHANNEL_ID}"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔗 مشاهده در سایت", url=data['url']))
    markup.add(types.InlineKeyboardButton("🛒 ثبت سفارش", url=ADMIN_PV))
    
    if data.get('image'):
        bot.send_photo(CHANNEL_ID, data['image'], caption=caption, parse_mode='Markdown', reply_markup=markup)
    else:
        bot.send_message(CHANNEL_ID, caption, parse_mode='Markdown', reply_markup=markup)

# --- هندلرهای تلگرام ---
@bot.message_handler(commands=['start'])
def welcome(m):
    user_id = m.from_user.id
    if user_id == ADMIN_ID:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("➕ افزودن محصول جدید")
        return bot.send_message(m.chat.id, "پنل مدیریت بانه استور:", reply_markup=markup)

    user = get_user(user_id)
    if user:
        bot.send_message(m.chat.id, f"سلام {user[1]} عزیز، خوش آمدید!")
    else:
        msg = bot.send_message(m.chat.id, "سلام! برای ثبت‌نام در بانه استور، نام و نام خانوادگی خود را وارد کنید:")
        bot.register_next_step_handler(msg, save_name)

def save_name(m):
    full_name = m.text
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(types.KeyboardButton("📱 ارسال شماره موبایل", request_contact=True))
    msg = bot.send_message(m.chat.id, f"ممنون {full_name} عزیز، حالا شماره خود را ارسال کنید:", reply_markup=markup)
    bot.register_next_step_handler(msg, save_phone, full_name)

def save_phone(m, full_name):
    if m.contact:
        register_user(m.from_user.id, full_name, m.contact.phone_number)
        bot.send_message(m.chat.id, "ثبت‌نام تکمیل شد. ✅", reply_markup=types.ReplyKeyboardRemove())
    else:
        bot.send_message(m.chat.id, "لطفاً دوباره /start بزنید و از دکمه استفاده کنید.")

@bot.message_handler(func=lambda m: m.text == "➕ افزودن محصول جدید")
def admin_add(m):
    if m.from_user.id == ADMIN_ID:
        bot.send_message(m.chat.id, "لینک محصول را بفرستید:")

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and "http" in m.text)
def process_link(m):
    sent = bot.reply_to(m, "⏳ در حال پردازش...")
    data = extract_product_info(m.text)
    if data:
        send_to_channel(data)
        bot.edit_message_text("✅ ارسال شد.", m.chat.id, sent.message_id)
    else:
        bot.edit_message_text("❌ خطا در استخراج.", m.chat.id, sent.message_id)

# --- تنظیمات سرور ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([telebot.types.Update.de_json(request.get_data().decode('utf-8'))])
        return ''
    return 'Forbidden', 403

@app.route('/')
def index(): return "Bot is Active!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
