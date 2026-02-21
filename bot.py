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
# فعال‌سازی Next Step برای کارکرد صحیح در حالت Webhook
bot.enable_save_next_step_handlers(delay=2)
bot.load_next_step_handlers()

app = Flask(__name__)

# --- مدیریت دیتابیس (Neon) ---
def get_db_connection():
    # Neon لینک‌ها را با postgres:// می‌دهد، اما psycopg2 گاهی نیاز به postgresql:// دارد
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
    except Exception as e:
        print(f"DB Init Error: {e}")

if DATABASE_URL:
    init_db()

# --- هندلرهای تلگرام ---

@bot.message_handler(commands=['start'])
def welcome(m):
    user_id = m.from_user.id
    
    # اگر ادمین بود
    if user_id == ADMIN_ID:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("➕ افزودن محصول جدید")
        return bot.send_message(m.chat.id, "ادمین عزیز خوش آمدید:", reply_markup=markup)

    # برای کاربران معمولی
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            bot.send_message(m.chat.id, f"سلام {user[0]} عزیز! خوش آمدید به بانه استور. ✨")
        else:
            msg = bot.send_message(m.chat.id, "سلام! برای ثبت‌نام در فروشگاه، لطفاً نام و نام خانوادگی خود را وارد کنید:")
            bot.register_next_step_handler(msg, save_name)
    except Exception as e:
        bot.send_message(m.chat.id, "در حال حاضر سیستم ثبت‌نام با اختلال مواجه است، اما می‌توانید از کانال دیدن کنید.")
        print(f"User check error: {e}")

def save_name(m):
    full_name = m.text
    if not full_name or len(full_name) < 3:
        msg = bot.reply_to(m, "لطفاً نام معتبر وارد کنید:")
        return bot.register_next_step_handler(msg, save_name)
        
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(types.KeyboardButton("📱 ارسال شماره موبایل", request_contact=True))
    msg = bot.send_message(m.chat.id, f"ممنون {full_name} عزیز، حالا با زدن دکمه زیر شماره خود را تایید کنید:", reply_markup=markup)
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
            bot.send_message(m.chat.id, "ثبت‌نام شما با موفقیت تکمیل شد! ✅", reply_markup=types.ReplyKeyboardRemove())
        except Exception as e:
            bot.send_message(m.chat.id, "خطا در ذخیره‌سازی اطلاعات.")
    else:
        bot.send_message(m.chat.id, "لطفاً برای ارسال شماره فقط از دکمه استفاده کنید. دوباره /start بزنید.")

# --- بقیه توابع (استخراج محصول و ارسال به کانال) همانند قبل ---
# [اینجا توابع extract_product_info و handle_messages ادمین را قرار دهید]

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'Forbidden', 403

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
