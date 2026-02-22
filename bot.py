import json
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

# --- ۳. تنظیمات ثابت ---
NAME, PHONE = range(2)
SEARCH_QUERY = 10
ADMIN_PANEL, BROADCAST = range(3, 5)
TRACK_ORDER = 15

HEADERS = {'User-Agent': 'Mozilla/5.0'}
SITE_URL = "https://banehstoore.ir"
CHANNEL_ID = "@banehstoore"
SUPPORT_URL = "https://t.me/+989180514202"
MIXIN_API_KEY = os.getenv('MIXIN_API_KEY')

# --- ۴. بخش پیگیری سفارش (اصلاح دقیق مبلغ و تاریخ) ---

async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔢 لطفاً شماره سفارش خود را وارد کنید:")
    return TRACK_ORDER

async def do_track_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_no = update.message.text.strip()
    wait = await update.message.reply_text("⏳ در حال استخراج تمام جزئیات سفارش از سایت...")
    
    # دیتابیس داخلی
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT items FROM orders WHERE order_id = %s", (order_no,))
        local_order = cur.fetchone(); cur.close(); conn.close()
        if local_order:
            await wait.edit_text(f"📄 **جزئیات فاکتور (ادمین):**\n\n{local_order[0]}", parse_mode='Markdown')
            return ConversationHandler.END
    except: pass

    # استعلام از API
    if MIXIN_API_KEY:
        try:
            api_url = f"{SITE_URL}/api/management/v1/orders/{order_no}/"
            res = requests.get(api_url, headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=12)
            
            if res.status_code == 200:
                data = res.json()
                
                # ۱. وضعیت با ترجمه ساده
                raw_status = data.get('status_display') or data.get('status') or 'ثبت شده'
                status_map = {"canceled": "❌ لغو شده", "pending": "⏳ در انتظار", "paid": "✅ پرداخت شده", "delivered": "🚚 تحویل شده"}
                status = status_map.get(raw_status.lower(), raw_status)

                # ۲. اصلاح مبلغ (تبدیل انواع فرمت‌ها به عدد)
                raw_price = data.get('total_price') or data.get('payable_amount') or data.get('total') or 0
                try:
                    price_val = int(float(raw_price))
                    total_price = "{:,} تومان".format(price_val) if price_val > 0 else "رایگان / نامشخص"
                except:
                    total_price = "نامشخص"
                
                # ۳. مشتری
                cust = data.get('customer') or data.get('user') or {}
                customer_name = f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip() or "نامشخص"
                
                # ۴. اقلام
                items_text = ""
                items = data.get('items') or data.get('order_items') or []
                for idx, item in enumerate(items, 1):
                    p_info = item.get('product') or item
                    name = p_info.get('title') or p_info.get('name') or 'محصول'
                    qty = item.get('quantity') or 1
                    items_text += f"{idx}. {name} (تعداد: {qty})\n"

                # ۵. اصلاح تاریخ
                raw_date = data.get('created_at_display') or data.get('created_at') or data.get('date_created') or 'نامشخص'
                # حذف قسمت ساعت برای تمیزی بیشتر (اگر فرمت استاندارد باشد)
                clean_date = raw_date.split('T')[0] if 'T' in raw_date else raw_date

                msg = (
                    f"📦 **اطلاعات کامل سفارش {order_no}**\n\n"
                    f"👤 **تحویل گیرنده:** {customer_name}\n"
                    f"🚩 **وضعیت فعلی:** {status}\n"
                    f"💰 **مبلغ کل سفارش:** {total_price}\n\n"
                    f"📝 **لیست اقلام سفارش:**\n{items_text}\n"
                    f"📅 **تاریخ ثبت:** {clean_date}\n\n"
                    f"💡 برای پیگیری دقیق‌تر با پشتیبانی در ارتباط باشید."
                )
                await wait.edit_text(msg, parse_mode='Markdown')
                return ConversationHandler.END
        except Exception as e: print(f"API Error: {e}")

    await wait.edit_text(f"❌ سفارش #{order_no} یافت نشد.")
    return ConversationHandler.END

# --- بقیه توابع (بدون تغییر) ---
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 نام محصول مورد نظر را وارد کنید:")
    return SEARCH_QUERY

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if query in ["جستجوی محصول 🔍", "پیگیری سفارش 📦", "ورود به پنل مدیریت ⚙️"]: return ConversationHandler.END
    wait = await update.message.reply_text(f"⏳ در حال جستجو برای «{query}»...")
    try:
        search_url = f"{SITE_URL}/search?q={query}"
        res = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        kb, seen = [], set()
        for link in soup.find_all('a', href=True):
            url = link['href']
            if url.startswith('/'): url = SITE_URL + url
            title = link.get_text().strip()
            if "/product/" in url and len(title) > 8:
                clean_title = re.sub(r'مشاهده|خرید|افزودن|تومان|قیمت', '', title).strip()
                if url not in seen and clean_title:
                    kb.append([InlineKeyboardButton(f"📦 {clean_title}", url=url)])
                    seen.add(url)
            if len(kb) >= 15: break
        if kb:
            await wait.delete()
            await update.message.reply_text(f"✅ نتایج یافت شده:", reply_markup=InlineKeyboardMarkup(kb))
        else: await wait.edit_text(f"❌ محصولی پیدا نشد.")
    except: await wait.edit_text("❌ خطا در اتصال به سایت.")
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    main_kb = [["جستجوی محصول 🔍", "پیگیری سفارش 📦"]]
    if str(user_id) == admin_id: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone(); cur.close(); conn.close()
    if user or str(user_id) == admin_id:
        await update.message.reply_text("خوش آمدید!", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
        return ConversationHandler.END
    await update.message.reply_text("سلام! نام و نام خانوادگی خود را وارد کنید:")
    return NAME

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

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    kb = [["آمار ربات 📊", "ارسال پیام همگانی 📢"], ["خروج از پنل 🔙"]]
    await update.message.reply_text("🛠 پنل مدیریت:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADMIN_PANEL

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM users")
    await update.message.reply_text(f"👥 تعداد کاربران: {cur.fetchone()[0]}")
    cur.close(); conn.close()

async def pre_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام را بفرستید:"); return BROADCAST

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT user_id FROM users")
    for u in cur.fetchall():
        try: await context.bot.copy_message(u[0], update.message.chat_id, update.message.message_id)
        except: pass
    cur.close(); conn.close()
    await update.message.reply_text("✅ ارسال شد."); return ADMIN_PANEL

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        title = (soup.find("meta", attrs={"property": "og:title"}) or soup.find("h1")).get("content", "محصول")
        img = soup.find("meta", attrs={"property": "og:image"})["content"]
        caption = f"🛍 **{title}**\n\n🔗 خرید مستقیم:\n{url}"
        await context.bot.send_photo(CHANNEL_ID, img, caption, parse_mode='Markdown')
        await update.message.reply_text("✅ ارسال شد.")
    except: pass

async def process_pasted_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    text = update.message.text
    try:
        order_id = re.search(r'شماره\s*:\s*(\d+)', text).group(1)
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO orders (order_id, items) VALUES (%s, %s) ON CONFLICT (order_id) DO UPDATE SET items=EXCLUDED.items", (order_id, text))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text(f"✅ فاکتور {order_id} ذخیره شد.")
    except: pass

if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^جستجوی محصول 🔍$"), search_start)],
            states={SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_search)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^پیگیری سفارش 📦$"), track_order_start)],
            states={TRACK_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_track_order)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^ورود به پنل مدیریت ⚙️$"), admin_menu)],
            states={
                ADMIN_PANEL: [MessageHandler(filters.Regex("^آمار ربات 📊$"), bot_stats), MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$"), pre_broadcast)],
                BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, do_broadcast)]
            },
            fallbacks=[MessageHandler(filters.Regex("^خروج از پنل 🔙$"), start)], allow_reentry=True
        ))
        app.add_handler(ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)], PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'جزییات سفارش شماره'), process_pasted_invoice))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        app.run_polling()