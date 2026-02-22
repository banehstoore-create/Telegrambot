import json
import os
import requests
import psycopg2
from threading import Thread
from flask import Flask
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
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
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY, full_name TEXT, phone_number TEXT, username TEXT)''')
        conn.commit()
        cur.close(); conn.close()
    except Exception as e: print(f"❌ DB Error: {e}")

# --- ۳. منطق ربات ---
NAME, PHONE = range(2)
ADMIN_PANEL, BROADCAST = range(3, 5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    main_kb = [["جستجوی محصول 🔍"]]
    if str(user_id) == admin_id: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    
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
    user_id, phone = update.effective_user.id, update.message.contact.phone_number
    full_name = context.user_data.get('full_name')
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s,%s,%s) ON CONFLICT (user_id) DO NOTHING", (user_id, full_name, phone))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text("✅ ثبت‌نام موفق!", reply_markup=ReplyKeyboardMarkup([["جستجوی محصول 🔍"]], resize_keyboard=True))
    except: pass
    return ConversationHandler.END

# --- ۴. پنل مدیریت ---
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    keyboard = [["آمار ربات 📊", "ارسال پیام همگانی 📢"], ["خروج از پنل 🔙"]]
    await update.message.reply_text("پنل مدیریت:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return ADMIN_PANEL

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users"); count = cur.fetchone()[0]
    cur.close(); conn.close()
    await update.message.reply_text(f"👥 تعداد کاربران: {count}")

async def pre_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام خود را ارسال کنید:")
    return BROADCAST

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT user_id FROM users")
    users = cur.fetchall(); cur.close(); conn.close()
    for u in users:
        try: await context.bot.copy_message(u[0], update.message.chat_id, update.message.message_id)
        except: pass
    await update.message.reply_text("✅ پیام با موفقیت ارسال شد.")
    return ADMIN_PANEL

# --- ۵. موتور جستجوی هوشمند ---
async def search_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    if query == "جستجوی محصول 🔍":
        await update.message.reply_text("🔍 نام محصول مورد نظر را وارد کنید:")
        return

    wait = await update.message.reply_text(f"⏳ در حال جستجوی تمامی نتایج برای '{query}'...")
    try:
        url = f"https://banehstoore.ir/search/{query}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'fa-IR,fa;q=0.9'
        }
        res = requests.get(url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # پیدا کردن کارت‌های محصول
        items = soup.select(".product-box, .product-item, .product-card")
        
        # روش جایگزین اگر کلاس‌های بالا یافت نشد
        if not items:
            items = [a.parent for a in soup.select('a[href*="/product/"]') if len(a.text.strip()) > 5]

        if not items:
            await wait.edit_text(f"❌ محصولی با عنوان '{query}' یافت نشد.")
            return

        kb = []
        seen = set()

        for it in items:
            link_tag = it.find("a", href=True)
            title_tag = it.find(["h2", "h3", "h1"]) or it.select_one(".title, .name, .product-title")
            price_tag = it.select_one(".price-value, .product-price, [data-price]")
            
            if link_tag and title_tag:
                title = title_tag.text.strip()
                link = link_tag['href']
                if not link.startswith("http"): link = "https://banehstoore.ir" + link
                
                if link not in seen:
                    # پردازش قیمت (تقسیم بر ۱۰)
                    price_text = "💰 مشاهده قیمت در سایت"
                    if price_tag:
                        # استخراج عدد از متن قیمت
                        raw_p = "".join(filter(str.isdigit, price_tag.text))
                        if raw_p:
                            formatted_p = "{:,}".format(int(raw_p) // 10)
                            price_text = f"💰 قیمت: {formatted_p} تومان"
                    
                    # اضافه کردن دکمه‌ها (نام در یک ردیف، قیمت در ردیف پایین)
                    kb.append([InlineKeyboardButton(f"📦 {title}", url=link)])
                    kb.append([InlineKeyboardButton(f"└ {price_text}", url=link)])
                    seen.add(link)

        if kb:
            await wait.delete()
            # نمایش پیام نهایی با تمام نتایج
            await update.message.reply_text(
                f"✅ تعداد {len(seen)} مورد برای **{query}** یافت شد:\n(برای جزئیات روی محصول کلیک کنید)",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='Markdown'
            )
        else:
            await wait.edit_text("❌ نتایج یافت شد اما استخراج اطلاعات ناموفق بود.")

    except Exception as e:
        print(f"Error: {e}")
        await wait.edit_text("❌ خطا در اتصال به سایت یا پردازش اطلاعات.")

# --- ۶. انتشار محصول (ادمین) ---
CHANNEL_ID = "@banehstoore"
SUPPORT_URL = "https://t.me/+989180514202"

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text
    msg = await update.message.reply_text("⏳ استخراج و ارسال...")
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        title = soup.find("meta", attrs={"property": "og:title"})["content"]
        img = soup.find("meta", attrs={"property": "og:image"})["content"]
        
        p_elem = soup.find(attrs={"data-price": True}) or soup.find(attrs={"itemprop": "price"})
        p_val = "".join(filter(str.isdigit, p_elem.get("data-price") or p_elem.text))
        price = "{:,} تومان".format(int(p_val)//10) if p_val else "تماس بگیرید"

        caption = f"🛍 **{title}**\n\n💰 قیمت: {price}\n\n🔗 خرید مستقیم از سایت 👇"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ثبت سفارش", url=url)], [InlineKeyboardButton("👨‍💻 پشتیبانی", url=SUPPORT_URL)]])
        await context.bot.send_photo(CHANNEL_ID, img, caption, parse_mode='Markdown', reply_markup=kb)
        await msg.edit_text("✅ محصول در کانال منتشر شد.")
    except: await msg.edit_text("❌ خطا در استخراج لینک محصول.")

# --- ۷. اجرای نهایی ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # هندلرها
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^ورود به پنل مدیریت ⚙️$"), admin_menu)],
            states={ADMIN_PANEL: [MessageHandler(filters.Regex("^آمار ربات 📊$"), bot_stats), MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$"), pre_broadcast)],
                    BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, do_broadcast)]},
            fallbacks=[MessageHandler(filters.Regex("^خروج از پنل 🔙$"), start)], allow_reentry=True
        ))
        
        app.add_handler(ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)], PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_products))
        
        app.run_polling()