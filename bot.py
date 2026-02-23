import json
import os
import requests
import psycopg2
import re
from urllib.parse import quote
from threading import Thread
from flask import Flask
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, 
    ConversationHandler, ContextTypes, CallbackQueryHandler
)
from telegram.error import BadRequest

# --- متغیرهای متنی دکمه‌ها (برای جلوگیری از خطای تایپی) ---
BTN_SEARCH = "جستجوی محصول 🔍"
BTN_TRACK = "پیگیری سفارش 📦"
BTN_CATS = "🗂 دسته‌بندی محصولات"
BTN_PRICE = "💰 استعلام قیمت لحظه‌ای"
BTN_SUPPORT = "📞 پشتیبانی و مشاوره"
BTN_ADMIN = "ورود به پنل مدیریت ⚙️"

# --- ۱. وب‌سرور زنده نگهدارنده ---
web_app = Flask('')
@web_app.route('/')
def home(): return "Bot is Online!"

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- ۲. تنظیمات دیتابیس ---
def get_db_connection():
    raw_url = os.getenv('DATABASE_URL')
    if raw_url and raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql://", 1)
    if raw_url and "sslmode" not in raw_url:
        raw_url += ("&" if "?" in raw_url else "?") + "sslmode=require"
    return psycopg2.connect(raw_url)

def init_db():
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY, full_name TEXT, phone_number TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, customer_name TEXT, items TEXT, total_price TEXT, status TEXT)''')
        conn.commit(); cur.close(); conn.close()
    except Exception as e: print(f"❌ DB Error: {e}")

# --- ۳. تنظیمات ثابت ---
NAME, PHONE = range(2)
SEARCH_QUERY = 10
ADMIN_PANEL, BROADCAST = range(3, 5)
TRACK_ORDER = 15
ASK_PRICE = 20

HEADERS = {'User-Agent': 'Mozilla/5.0'}
SITE_URL = "https://banehstoore.ir"
CHANNEL_ID = "@banehstoore" 
SUPPORT_PHONE = "09180514202"
SUPPORT_MAP = "https://maps.app.goo.gl/eWv6njTbL8ivfbYa6"
MIXIN_API_KEY = os.getenv('MIXIN_API_KEY')

# --- توابع کمکی عضویت اجباری ---
async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception: return True 

async def send_join_request(update: Update):
    keyboard = [
        [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_ID.replace('@','')}")],
        [InlineKeyboardButton("✅ عضو شدم (تایید)", callback_data="check_join")]
    ]
    msg = "⚠️ برای استفاده از امکانات ربات، ابتدا باید در کانال ما عضو شوید 👇"
    if update.message:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

# --- بخش پشتیبانی و مشاوره ---
async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # لاگ برای عیب‌یابی در کنسول Render
    print(f"Support button clicked by: {update.effective_user.id}")
    
    kb = [
        [InlineKeyboardButton("📍 مشاهده آدرس روی نقشه", url=SUPPORT_MAP)],
        [InlineKeyboardButton("📞 تماس مستقیم", url=f"tel:{SUPPORT_PHONE}"), 
         InlineKeyboardButton("💬 واتساپ", url=f"https://wa.me/{SUPPORT_PHONE.replace('0','+98',1)}")],
        [InlineKeyboardButton("📢 کانال تلگرام ما", url=f"https://t.me/{CHANNEL_ID.replace('@','')}")]
    ]
    await update.message.reply_text(
        "🎧 **بخش پشتیبانی و مشاوره بانه استور**\n\nجهت ارتباط با ما از دکمه‌های زیر استفاده کنید:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )

# --- سایر توابع (جستجو، پیگیری و ...) همانند قبل ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    
    # ساخت کیبورد با متغیرهای ثابت
    main_kb = [
        [BTN_SEARCH, BTN_TRACK],
        [BTN_CATS, BTN_PRICE],
        [BTN_SUPPORT]
    ]
    if str(user_id) == admin_id: main_kb.insert(0, [BTN_ADMIN])
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
    user_row = cur.fetchone(); cur.close(); conn.close()
    
    if user_row or str(user_id) == admin_id:
        if not await is_subscribed(context, user_id):
            await send_join_request(update); return ConversationHandler.END
        name = user_row[0] if user_row else "مدیریت"
        await update.message.reply_text(f"سلام {name} عزیز، خوش آمدید:", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
        return ConversationHandler.END
    await update.message.reply_text("سلام! نام و نام خانوادگی خود را وارد کنید:")
    return NAME

async def handle_callback_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if await is_subscribed(context, query.from_user.id):
        await query.message.delete()
        await start(update, context)
    else: await context.bot.send_message(chat_id=query.from_user.id, text="❌ هنوز عضو نشده‌اید.")

# --- بخش ثبت‌نام ---
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    btn = [[KeyboardButton("ارسال شماره موبایل 📱", request_contact=True)]]
    await update.message.reply_text("لطفاً شماره خود را تایید کنید:", reply_markup=ReplyKeyboardMarkup(btn, one_time_keyboard=True, resize_keyboard=True))
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact: return PHONE
    user_id, phone, name = update.effective_user.id, update.message.contact.phone_number, context.user_data.get('full_name')
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (user_id, name, phone))
    conn.commit(); cur.close(); conn.close()
    if not await is_subscribed(context, user_id): await send_join_request(update)
    else: await start(update, context)
    return ConversationHandler.END

# --- اجرای اصلی ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # ۱. هندلرهای عمومی و دکمه‌های شیشه‌ای (بالاترین اولویت)
        app.add_handler(CallbackQueryHandler(handle_callback_check, pattern="check_join"))
        
        # ۲. هندلرهای دکمه‌های ریپلای (بدون نیاز به Conversation)
        app.add_handler(MessageHandler(filters.Regex(f"^{BTN_SUPPORT}$"), show_support))
        
        # ۳. هندلرهای گفتگو (مانند جستجو، پیگیری و ثبت‌نام)
        # (توجه: اینها باید بعد از دکمه پشتیبانی باشند)
        
        # ... هندلرهای دیگر اینجا اضافه شوند ...

        # هندلر شروع (ثبت‌نام)
        app.add_handler(ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
                PHONE: [MessageHandler(filters.CONTACT, get_phone)]
            },
            fallbacks=[CommandHandler('start', start)],
            allow_reentry=True
        ))

        print("Bot is starting...")
        app.run_polling()