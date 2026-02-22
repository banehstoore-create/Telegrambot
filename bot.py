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
ADMIN_PANEL, BROADCAST = range(3, 5)
TRACK_ORDER = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'fa-IR,fa;q=0.9',
}
CHANNEL_ID = "@banehstoore"
SUPPORT_URL = "https://t.me/+989180514202"

# --- ۴. توابع پیگیری و ثبت هوشمند ---

async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نقطه شروع پیگیری سفارش وقتی دکمه زده می‌شود"""
    await update.message.reply_text("🔢 لطفاً شماره سفارش خود را وارد کنید:")
    return TRACK_ORDER

async def do_track_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش فاکتور به مشتری"""
    order_no = update.message.text.strip()
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT items FROM orders WHERE order_id = %s", (order_no,))
        order = cur.fetchone(); cur.close(); conn.close()
        
        if order:
            await update.message.reply_text(f"📄 **اطلاعات سفارش شما:**\n\n{order[0]}", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ فاکتوری با این شماره یافت نشد. لطفاً از صحت شماره اطمینان حاصل کنید.")
    except:
        await update.message.reply_text("❌ خطا در سیستم پیگیری.")
    return ConversationHandler.END

async def process_pasted_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش هوشمند فاکتور کپی شده از سایت توسط ادمین"""
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    
    text = update.message.text
    try:
        order_id_match = re.search(r'شماره\s*:\s*(\d+)', text)
        customer_match = re.search(r'تحویل گیرنده\s*:\s*(.*)', text)
        price_match = re.search(r'مبلغ کل\s*:\s*([\d,٬]+)', text)
        
        if not order_id_match: return

        order_id = order_id_match.group(1)
        customer_name = customer_match.group(1).strip() if customer_match else "نامشخص"
        total_price = price_match.group(1).strip() if price_match else "نامشخص"
        
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO orders (order_id, customer_name, items, total_price, status) 
            VALUES (%s, %s, %s, %s, %s) 
            ON CONFLICT (order_id) DO UPDATE SET 
            customer_name=EXCLUDED.customer_name, items=EXCLUDED.items, total_price=EXCLUDED.total_price
        """, (order_id, customer_name, text, total_price, "ثبت شده"))
        conn.commit(); cur.close(); conn.close()
        
        await update.message.reply_text(f"✅ فاکتور شماره {order_id} با موفقیت ذخیره شد.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در پردازش: {e}")

# --- ۵. سایر توابع (جستجو، ثبت‌نام، پنل) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    main_kb = [["جستجوی محصول 🔍", "پیگیری سفارش 📦"]]
    if str(user_id) == admin_id: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
        user_exists = cur.fetchone()
        cur.close(); conn.close()
        
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

async def search_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    if query == "جستجوی محصول 🔍":
        await update.message.reply_text("🔍 نام محصول را وارد کنید:"); return
    wait = await update.message.reply_text(f"⏳ در حال جستجوی '{query}'...")
    try:
        res = requests.get(f"https://banehstoore.ir/search/{query}", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        kb, seen = [], set()
        for link in soup.find_all('a', href=True):
            t, h = link.get_text().strip(), link['href']
            if query in t and "/product/" in h:
                url = h if h.startswith("http") else "https://banehstoore.ir" + h
                if url not in seen and len(t) > 3:
                    kb.append([InlineKeyboardButton(f"📦 {t}", url=url)])
                    seen.add(url)
        if kb:
            await wait.delete()
            await update.message.reply_text("✅ نتایج:", reply_markup=InlineKeyboardMarkup(kb))
        else: await wait.edit_text("❌ محصولی یافت نشد.")
    except: await wait.edit_text("❌ خطا در اتصال.")

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text
    msg = await update.message.reply_text("⏳ در حال انتشار...")
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        title = (soup.find("meta", attrs={"property": "og:title"}) or soup.find("h1")).get("content", soup.find("h1").text)
        img = soup.find("meta", attrs={"property": "og:image"})["content"]
        p_elem = soup.find(attrs={"data-price": True}) or soup.select_one(".product-price")
        p_val = "".join(filter(str.isdigit, p_elem.text if p_elem else ""))
        price = "{:,} تومان".format(int(p_val)//10) if p_val else "تماس بگیرید"
        caption = f"🛍 **{title}**\n\n💰 قیمت: {price}\n\n🔗 خرید مستقیم 👇"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ثبت سفارش", url=url)], [InlineKeyboardButton("👨‍💻 پشتیبانی", url=SUPPORT_URL)]])
        await context.bot.send_photo(CHANNEL_ID, img, caption, parse_mode='Markdown', reply_markup=kb)
        await msg.edit_text("✅ منتشر شد.")
    except: await msg.edit_text("❌ خطا در استخراج.")

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

# --- ۶. اجرای نهایی ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # ۱. هندلر پیگیری سفارش
        track_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^پیگیری سفارش 📦$"), track_order_start)],
            states={TRACK_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_track_order)]},
            fallbacks=[CommandHandler('start', start)],
            allow_reentry=True
        )

        # ۲. هندلر ادمین
        admin_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^ورود به پنل مدیریت ⚙️$"), admin_menu)],
            states={
                ADMIN_PANEL: [MessageHandler(filters.Regex("^آمار ربات 📊$"), bot_stats), MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$"), pre_broadcast)],
                BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, do_broadcast)]
            },
            fallbacks=[MessageHandler(filters.Regex("^خروج از پنل 🔙$"), start)],
            allow_reentry=True
        )

        # ۳. هندلر ثبت‌نام
        user_reg_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)], PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)],
            allow_reentry=True
        )

        app.add_handler(track_handler)
        app.add_handler(admin_handler)
        app.add_handler(user_reg_handler)
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'جزییات سفارش شماره'), process_pasted_invoice))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_products))
        
        print("🚀 Bot is Online!")
        app.run_polling()