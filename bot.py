import json
import os
import requests
import psycopg2
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
ADMIN_PANEL, BROADCAST = range(3, 5)
ORDER_ID, CUST_NAME, ORDER_ITEMS, ORDER_PRICE = range(10, 14)
TRACK_ORDER = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'fa-IR,fa;q=0.9',
}
CHANNEL_ID = "@banehstoore"
SUPPORT_URL = "https://t.me/+989180514202"

# --- ۴. توابع منطقی ربات ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    
    # کیبورد اصلی با پیگیری سفارش
    main_kb = [["جستجوی محصول 🔍", "پیگیری سفارش 📦"]]
    if str(user_id) == admin_id:
        main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone(); cur.close(); conn.close()
        if user or str(user_id) == admin_id:
            await update.message.reply_text("خوش آمدید! از منوی زیر استفاده کنید:", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
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
    user_id = update.effective_user.id
    phone = update.message.contact.phone_number
    full_name = context.user_data.get('full_name')
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s,%s,%s) ON CONFLICT (user_id) DO NOTHING", (user_id, full_name, phone))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text("✅ ثبت‌نام موفق!", reply_markup=ReplyKeyboardMarkup([["جستجوی محصول 🔍", "پیگیری سفارش 📦"]], resize_keyboard=True))
    except: pass
    return ConversationHandler.END

# --- ۵. پیگیری سفارش (مشتری) ---
async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔢 لطفاً شماره سفارش خود را وارد کنید:")
    return TRACK_ORDER

async def do_track_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_no = update.message.text.strip()
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE order_id = %s", (order_no,))
        order = cur.fetchone(); cur.close(); conn.close()
        if order:
            text = (f"📄 **جزئیات فاکتور شماره: {order[0]}**\n\n👤 مشتری: {order[1]}\n📦 شرح: {order[2]}\n💰 مبلغ کل: {order[3]}\n🚚 وضعیت: {order[4]}")
            await update.message.reply_text(text, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ فاکتوری با این شماره یافت نشد.")
    except: await update.message.reply_text("❌ خطای سیستم.")
    return ConversationHandler.END

# --- ۶. پنل مدیریت و ثبت فاکتور ---
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    kb = [["آمار ربات 📊", "ارسال پیام همگانی 📢"], ["ثبت فاکتور دستی ➕", "خروج از پنل 🔙"]]
    await update.message.reply_text("⚙️ پنل مدیریت:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADMIN_PANEL

async def add_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🆕 شماره سفارش را وارد کنید (مثلاً ۴۹۱۱۱):")
    return ORDER_ID

async def set_order_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_order_id'] = update.message.text
    await update.message.reply_text("👤 نام مشتری:")
    return CUST_NAME

async def set_cust_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_cust_name'] = update.message.text
    await update.message.reply_text("📦 شرح کالا:")
    return ORDER_ITEMS

async def set_order_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_items'] = update.message.text
    await update.message.reply_text("💰 مبلغ کل (تومان):")
    return ORDER_PRICE

async def set_order_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = update.message.text
    oid, name, items = context.user_data['new_order_id'], context.user_data['new_cust_name'], context.user_data['new_items']
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO orders (order_id, customer_name, items, total_price, status) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (order_id) DO UPDATE SET status=EXCLUDED.status", 
                    (oid, name, items, price, "تایید شده"))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text(f"✅ فاکتور {oid} ثبت شد.")
    except: await update.message.reply_text("❌ خطا در ذخیره.")
    return ADMIN_PANEL

# (توابع bot_stats و do_broadcast و search_products و post_product بدون تغییر باقی می‌مانند...)
# برای کوتاه شدن پاسخ، توابع کمکی تکراری مثل آمار و سرچ را در کد نهایی ادغام کردیم.

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]; cur.close(); conn.close()
    await update.message.reply_text(f"👥 تعداد کاربران: {count}")

async def pre_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام را بفرستید:"); return BROADCAST

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT user_id FROM users")
    users = cur.fetchall(); cur.close(); conn.close()
    for u in users:
        try: await context.bot.copy_message(u[0], update.message.chat_id, update.message.message_id)
        except: pass
    await update.message.reply_text("✅ ارسال شد."); return ADMIN_PANEL

async def search_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    if query == "جستجوی محصول 🔍":
        await update.message.reply_text("🔍 نام محصول را وارد کنید:"); return
    wait = await update.message.reply_text(f"⏳ جستجوی '{query}'...")
    try:
        res = requests.get(f"https://banehstoore.ir/search/{query}", headers=HEADERS, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        kb, seen = [], set()
        for link in soup.find_all('a', href=True):
            text, href = link.get_text().strip(), link['href']
            if query in text and "/product/" in href:
                full_url = href if href.startswith("http") else "https://banehstoore.ir" + href
                if full_url not in seen and len(text) > 3:
                    kb.append([InlineKeyboardButton(f"📦 {text}", url=full_url)])
                    seen.add(full_url)
        if kb:
            await wait.delete()
            await update.message.reply_text(f"✅ نتایج:", reply_markup=InlineKeyboardMarkup(kb))
        else: await wait.edit_text("❌ موردی یافت نشد.")
    except: await wait.edit_text("❌ خطا در اتصال.")

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text
    msg = await update.message.reply_text("⏳ در حال پردازش...")
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        title = soup.find("meta", attrs={"property": "og:title"})["content"]
        img = soup.find("meta", attrs={"property": "og:image"})["content"]
        p_elem = soup.find(attrs={"data-price": True}) or soup.select_one(".product-price")
        p_val = "".join(filter(str.isdigit, p_elem.text if p_elem else ""))
        price = "{:,} تومان".format(int(p_val)//10) if p_val else "تماس بگیرید"
        caption = f"🛍 **{title}**\n\n💰 قیمت: {price}\n\n🔗 خرید مستقیم 👇"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ثبت سفارش", url=url)], [InlineKeyboardButton("👨‍💻 پشتیبانی", url=SUPPORT_URL)]])
        await context.bot.send_photo(CHANNEL_ID, img, caption, parse_mode='Markdown', reply_markup=kb)
        await msg.edit_text("✅ منتشر شد.")
    except: await msg.edit_text("❌ خطا در استخراج.")

# --- ۷. اجرای نهایی ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # هندلر پیگیری برای کاربر
        track_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^پیگیری سفارش 📦$"), track_order_start)],
            states={TRACK_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_track_order)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        )

        # هندلر مدیریت (فول آپشن)
        admin_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^ورود به پنل مدیریت ⚙️$"), admin_menu)],
            states={
                ADMIN_PANEL: [
                    MessageHandler(filters.Regex("^آمار ربات 📊$"), bot_stats),
                    MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$"), pre_broadcast),
                    MessageHandler(filters.Regex("^ثبت فاکتور دستی ➕$"), add_order_start)
                ],
                BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, do_broadcast)],
                ORDER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_order_id)],
                CUST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_cust_name)],
                ORDER_ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_order_items)],
                ORDER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_order_price)],
            },
            fallbacks=[MessageHandler(filters.Regex("^خروج از پنل 🔙$"), start)], allow_reentry=True
        )

        # هندلر ثبت‌نام
        user_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)], PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        )

        app.add_handler(admin_handler)
        app.add_handler(track_handler)
        app.add_handler(user_handler)
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_products))
        
        print("🚀 Bot is Online!")
        app.run_polling()