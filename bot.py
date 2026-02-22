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
        print("✅ Database Ready!")
    except Exception as e: print(f"❌ DB Error: {e}")

# --- ۳. تنظیمات و متغیرها ---
NAME, PHONE = range(2)
SEARCH_QUERY = 10
ADMIN_PANEL, BROADCAST = range(3, 5)
TRACK_ORDER = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}
SITE_URL = "https://banehstoore.ir"
CHANNEL_ID = "@banehstoore"
SUPPORT_URL = "https://t.me/+989180514202"
MIXIN_API_KEY = os.getenv('MIXIN_API_KEY') # توکن اختیاری برای پیگیری خودکار

# --- ۴. توابع پیگیری و ثبت هوشمند فاکتور (ترکیب دستی و خودکار) ---

async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔢 لطفاً شماره سفارش خود را وارد کنید:")
    return TRACK_ORDER

async def do_track_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_no = update.message.text.strip()
    wait = await update.message.reply_text("⏳ در حال بررسی وضعیت سفارش...")
    
    # ابتدا بررسی در دیتابیس داخلی (فاکتورهای کپی شده توسط ادمین)
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT items FROM orders WHERE order_id = %s", (order_no,))
        order = cur.fetchone(); cur.close(); conn.close()
        if order:
            await wait.edit_text(f"📄 **اطلاعات سفارش شما:**\n\n{order[0]}", parse_mode='Markdown')
            return ConversationHandler.END
    except: pass

    # اگر در دیتابیس نبود، استعلام از سایت (API میکسین)
    if MIXIN_API_KEY:
        try:
            api_url = f"{SITE_URL}/api/management/v1/orders/{order_no}/"
            res = requests.get(api_url, headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                status = data.get('status_display', 'ثبت شده')
                await wait.edit_text(f"📦 **وضعیت سفارش در سایت:**\n\nشماره سفارش: {order_no}\nوضعیت فعلی: {status}")
                return ConversationHandler.END
        except: pass

    await wait.edit_text("❌ سفارش یافت نشد. اگر فاکتور دارید، شماره را درست وارد کنید.")
    return ConversationHandler.END

async def process_pasted_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    text = update.message.text
    try:
        order_id_match = re.search(r'شماره\s*:\s*(\d+)', text)
        if not order_id_match: return
        order_id = order_id_match.group(1)
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO orders (order_id, items) VALUES (%s, %s) 
            ON CONFLICT (order_id) DO UPDATE SET items=EXCLUDED.items
        """, (order_id, text))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text(f"✅ فاکتور شماره {order_id} با موفقیت ذخیره شد.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در ذخیره فاکتور: {e}")

# --- ۵. بخش جستجوی محصول (تست شده و اصلاح شده) ---

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 نام محصول مورد نظر را وارد کنید:")
    return SEARCH_QUERY

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if query in ["جستجوی محصول 🔍", "پیگیری سفارش 📦", "ورود به پنل مدیریت ⚙️"]:
        return ConversationHandler.END

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
        else:
            await wait.edit_text(f"❌ محصولی برای «{query}» پیدا نشد.")
    except:
        await wait.edit_text("❌ خطا در اتصال به سایت.")
    return ConversationHandler.END

# --- ۶. توابع ادمین و انتشار محصول ---

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text
    msg = await update.message.reply_text("⏳ در حال انتشار...")
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        title = (soup.find("meta", attrs={"property": "og:title"}) or soup.find("h1")).get("content", "محصول")
        img = soup.find("meta", attrs={"property": "og:image"})["content"]
        p_elem = soup.find(attrs={"data-price": True}) or soup.select_one(".product-price")
        p_val = "".join(filter(str.isdigit, p_elem.text if p_elem else ""))
        price = "{:,} تومان".format(int(p_val)//10) if p_val else "تماس بگیرید"
        caption = f"🛍 **{title}**\n\n💰 قیمت: {price}\n\n🔗 خرید مستقیم 👇"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ثبت سفارش", url=url)], [InlineKeyboardButton("👨‍💻 پشتیبانی", url=SUPPORT_URL)]])
        await context.bot.send_photo(CHANNEL_ID, img, caption, parse_mode='Markdown', reply_markup=kb)
        await msg.edit_text("✅ در کانال منتشر شد.")
    except: await msg.edit_text("❌ خطا در استخراج اطلاعات.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    main_kb = [["جستجوی محصول 🔍", "پیگیری سفارش 📦"]]
    if str(user_id) == admin_id: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
        user_exists = cur.fetchone(); cur.close(); conn.close()
        if user_exists or str(user_id) == admin_id:
            await update.message.reply_text("خوش آمدید! از منو استفاده کنید:", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
            return ConversationHandler.END
    except: pass
    await update.message.reply_text("سلام! لطفاً نام و نام خانوادگی خود را وارد کنید:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    btn = [[KeyboardButton("ارسال شماره موبایل 📱", request_contact=True)]]
    await update.message.reply_text("لطفاً شماره خود را تایید کنید:", reply_markup=ReplyKeyboardMarkup(btn, one_time_keyboard=True, resize_keyboard=True))
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact: return PHONE
    user_id, phone, name = update.effective_user.id, update.message.contact.phone_number, context.user_data.get('full_name')
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (user_id, name, phone))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text("✅ ثبت‌نام موفق!", reply_markup=ReplyKeyboardMarkup([["جستجوی محصول 🔍", "پیگیری سفارش 📦"]], resize_keyboard=True))
    except: pass
    return ConversationHandler.END

# --- ۷. پنل مدیریت (بازگردانی شده) ---

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

# --- ۸. اجرای نهایی ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # هندلر جستجو
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^جستجوی محصول 🔍$"), search_start)],
            states={SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_search)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))

        # هندلر پیگیری سفارش
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^پیگیری سفارش 📦$"), track_order_start)],
            states={TRACK_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_track_order)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))

        # هندلر ادمین
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^ورود به پنل مدیریت ⚙️$"), admin_menu)],
            states={
                ADMIN_PANEL: [MessageHandler(filters.Regex("^آمار ربات 📊$"), bot_stats), MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$"), pre_broadcast)],
                BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, do_broadcast)]
            },
            fallbacks=[MessageHandler(filters.Regex("^خروج از پنل 🔙$"), start)], allow_reentry=True
        ))

        # هندلر ثبت‌نام
        app.add_handler(ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)], PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))

        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'جزییات سفارش شماره'), process_pasted_invoice))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        
        print("🚀 Bot is Online with All Features!")
        app.run_polling()