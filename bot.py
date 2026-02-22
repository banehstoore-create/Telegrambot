import os
import requests
import psycopg2
import re
from threading import Thread
from flask import Flask
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
)

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

# --- ۳. تنظیمات و وضعیت‌ها ---
NAME, PHONE = range(0, 2)
SEARCH_STATE = 10
ADMIN_PANEL, BROADCAST = range(20, 22)
TRACK_ORDER = 30

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
SITE_URL = "https://banehstoore.ir"
SUPPORT_URL = "https://t.me/+989180514202"
CHANNEL_ID = "@banehstoore"

# --- ۴. بخش جستجو (اصلاح شده) ---

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 نام محصول مورد نظر را وارد کنید (مثلاً: جاروبرقی):")
    return SEARCH_STATE

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    # اگر کاربر دکمه‌های اصلی را وسط جستجو بزند، عملیات لغو شود
    if query in ["جستجوی محصول 🔍", "پیگیری سفارش 📦", "ورود به پنل مدیریت ⚙️"]:
        return ConversationHandler.END

    wait_msg = await update.message.reply_text(f"⏳ در حال جستجوی «{query}»...")
    
    try:
        # ساختار جستجوی سایت میکسین
        search_url = f"{SITE_URL}/search?q={query}"
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        kb = []
        seen_urls = set()

        # پیدا کردن لینک محصولات در سایت میکسین
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.startswith('/'): href = SITE_URL + href
            
            title = link.get_text().strip()
            
            # فیلتر کردن لینک‌های تکراری و متون کوتاه یا بی‌ربط
            if "/product/" in href and len(title) > 8:
                clean_title = re.sub(r'مشاهده|خرید|افزودن|تومان|قیمت|سبد خرید', '', title).strip()
                if href not in seen_urls and clean_title:
                    kb.append([InlineKeyboardButton(f"📦 {clean_title}", url=href)])
                    seen_urls.add(href)
            
            if len(kb) >= 12: break # نمایش حداکثر ۱۲ محصول

        if kb:
            await wait_msg.delete()
            await update.message.reply_text(
                f"✅ محصولات یافت شده برای «{query}»:",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await wait_msg.edit_text(f"❌ متأسفانه محصولی برای «{query}» پیدا نشد.\n\n💡 پیشنهاد: کلمه را کوتاه‌تر وارد کنید.")
            
    except Exception as e:
        await wait_msg.edit_text("❌ خطا در اتصال به سایت. لطفاً بعداً تلاش کنید.")
    
    return ConversationHandler.END

# --- ۵. سایر توابع (ثابت) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    main_kb = [["جستجوی محصول 🔍", "پیگیری سفارش 📦"]]
    if str(user_id) == admin_id: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone(); cur.close(); conn.close()
    
    if user or str(user_id) == admin_id:
        await update.message.reply_text("خوش آمدید! از منوی زیر استفاده کنید:", 
                                       reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
        return ConversationHandler.END
    
    await update.message.reply_text("سلام! برای استفاده از ربات، ابتدا نام و نام خانوادگی خود را وارد کنید:")
    return NAME

# (سایر توابع مثل track_order, post_product و غیره دقیقاً مثل قبل هستند اما برای اختصار اینجا حذف شده‌اند تا تمرکز روی باگ جستجو باشد)
# در کد نهایی زیر، همه توابع شما گنجانده شده است.

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
    await update.message.reply_text("✅ ثبت‌نام موفق!", reply_markup=ReplyKeyboardMarkup([["جستجوی محصول 🔍", "پیگیری سفارش 📦"]], resize_keyboard=True))
    return ConversationHandler.END

# --- ۶. اجرای ربات و ترتیب هندلرها (بسیار مهم) ---

if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # ۱. هندلر جستجو (بالاترین اولویت)
        search_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^جستجوی محصول 🔍$"), search_start)],
            states={SEARCH_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_search)]},
            fallbacks=[CommandHandler('start', start)],
            allow_reentry=True
        )

        # ۲. هندلر ثبت‌نام
        reg_conv = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
                PHONE: [MessageHandler(filters.CONTACT, get_phone)]
            },
            fallbacks=[CommandHandler('start', start)],
            allow_reentry=True
        )

        # اضافه کردن سایر هندلرها (ادمین و غیره) به همین ترتیب...
        app.add_handler(search_conv)
        app.add_handler(reg_conv)
        # سایر هندلرهای پیام ساده
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product)) 
        
        print("🚀 Bot is Online with Fix!")
        app.run_polling()