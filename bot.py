import os
import json
import telebot
import psycopg2 # اضافه شد برای اتصال به دیتابیس
from flask import Flask, request
from telebot import types

# --- تنظیمات اولیه ---
TOKEN = os.environ.get("BOT_TOKEN")
# آدرس اتصال از پنل Neon (مثال: postgresql://user:pass@host/dbname)
DATABASE_URL = os.environ.get("DATABASE_URL") 
ADMIN_ID = 6690559792 
CHANNEL_ID = "@banehstoore"
ADMIN_PV = "https://t.me/banehstoore_admin"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- توابع دیتابیس (Neon) ---

def init_db():
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

def get_user(user_id):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def register_user(user_id, full_name, phone):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s, %s, %s)", 
                (user_id, full_name, phone))
    conn.commit()
    cur.close()
    conn.close()

# ایجاد جدول در شروع برنامه
init_db()

# --- بخش مدیریت ثبت‌نام مشتری ---

@bot.message_handler(commands=['start'])
def send_welcome(m):
    user_id = m.from_user.id
    
    # اگر ادمین بود منوی ادمین را نشان بده
    if user_id == ADMIN_ID:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("➕ افزودن محصول جدید"))
        return bot.send_message(m.chat.id, "ادمین عزیز خوش آمدید:", reply_markup=markup)

    # بررسی ثبت‌نام مشتری در دیتابیس
    user = get_user(user_id)
    if user:
        bot.send_message(m.chat.id, f"سلام {user[1]} عزیز! خوش آمدید. برای خرید به کانال بپیوندید:\n{CHANNEL_ID}")
    else:
        # شروع فرآیند ثبت‌نام برای اولین بار
        msg = bot.send_message(m.chat.id, "سلام! به فروشگاه بانه استور خوش آمدید.\nبرای خدمات بهتر، لطفاً نام و نام خانوادگی خود را وارد کنید:")
        bot.register_next_step_handler(msg, process_name_step)

def process_name_step(m):
    full_name = m.text
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    button_phone = types.KeyboardButton(text="📱 ارسال شماره موبایل", request_contact=True)
    markup.add(button_phone)
    msg = bot.send_message(m.chat.id, f"ممنون {full_name}. حالا دکمه اشتراک‌گذاری شماره موبایل را بزنید:", reply_markup=markup)
    bot.register_next_step_handler(msg, process_phone_step, full_name)

def process_phone_step(m, full_name):
    if m.contact is not None:
        phone = m.contact.phone_number
        register_user(m.from_user.id, full_name, phone)
        bot.send_message(m.chat.id, "ثبت‌نام شما با موفقیت تکمیل شد! ✅\nحالا می‌توانید از کانال ما دیدن کنید.", reply_markup=types.ReplyKeyboardRemove())
    else:
        bot.send_message(m.chat.id, "لطفاً از دکمه برای ارسال شماره استفاده کنید. دوباره /start را بزنید.")

# --- بخش مدیریت محصولات (ادمین) همانند قبل ---
# [توابع extract_product_info و send_to_channel و handle_messages را اینجا قرار دهید]
