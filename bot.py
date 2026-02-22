import json
import os
import requests
import psycopg2
from threading import Thread
from flask import Flask
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes
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
        cur.execute('''DO $$ BEGIN BEGIN ALTER TABLE users ADD COLUMN username TEXT; 
                       EXCEPTION WHEN duplicate_column THEN NULL; END; END $$;''')
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database Ready!")
    except Exception as e: print(f"❌ DB Error: {e}")

# --- ۳. منطق ثبت‌نام و مدیریت ---
NAME, PHONE = range(2)
ADMIN_PANEL, BROADCAST = range(3, 5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    
    # کیبورد اصلی
    main_kb = [["جستجوی محصول 🔍"]]
    if str(user_id) == admin_id:
        main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])

    # بررسی ثبت‌نام
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user or str(user_id) == admin_id:
            await update.message.reply_text(f"خوش آمدید! از منوی زیر انتخاب کنید:", 
                reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
            return ConversationHandler.END
    except: pass

    await update.message.reply_text("سلام! خوش آمدید. برای شروع نام خود را وارد کنید:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    btn = [[KeyboardButton("ارسال شماره موبایل 📱", request_contact=True)]]
    await update.message.reply_text("لطفاً شماره خود را تایید کنید:", 
        reply_markup=ReplyKeyboardMarkup(btn, one_time_keyboard=True, resize_keyboard=True))
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact: return PHONE
    user_id, phone = update.effective_user.id, update.message.contact.phone_number
    full_name = context.user_data.get('full_name')
    username = update.effective_user.username or "None"
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, full_name, phone_number, username) VALUES (%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET phone_number=EXCLUDED.phone_number", (user_id, full_name, phone, username))
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text("✅ ثبت‌نام موفق!", reply_markup=ReplyKeyboardMarkup([["جستجوی محصول 🔍"]], resize_keyboard=True))
    except Exception as e: print(f"Save Error: {e}")
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
    await update.message.reply_text(f"👥 کاربران: {count}")

async def pre_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام را بفرستید:")
    return BROADCAST

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT user_id FROM users")
    users = cur.fetchall(); cur.close(); conn.close()
    for u in users:
        try: await context.bot.copy_message(u[0], update.message.chat_id, update.message.message_id)
        except: pass
    await update.message.reply_text("✅ ارسال شد.")
    return ADMIN_PANEL

# --- ۵. جستجو و استخراج (میکسین) ---
CHANNEL_ID = "@banehstoore" 
SUPPORT_URL = "https://t.me/+989180514202"

async def search_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    if query == "جستجوی محصول 🔍":
        await update.message.reply_text("لطفاً نام محصول مورد نظر را بنویسید (مثلاً: سرخ کن):")
        return

    wait = await update.message.reply_text(f"🔎 در حال جستجوی '{query}' در بانه استور...")
    try:
        # تست دو مدل آدرس جستجوی متداول در میکسین
        search_urls = [
            f"https://banehstoore.ir/search/{query}",
            f"https://banehstoore.ir/?s={query}"
        ]
        
        items = []
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        for url in search_urls:
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # پیدا کردن کارت‌های محصول (با کلاس‌های متنوع میکسین)
            items = soup.select(".product-item, .product-card, .product-grid-item, .item-product")
            if items: break

        if not items:
            await wait.edit_text(f"❌ محصولی با عنوان '{query}' در سایت یافت نشد.\nلطفاً کلمه دیگری را امتحان کنید.")
            return

        kb = []
        for it in items[:10]: # محدود به ۱۰ نتیجه
            # پیدا کردن نام و لینک با دقت بالا
            link_tag = it.select_one("a")
            title_tag = it.select_one(".product-title, h3, .name, .title")
            
            if link_tag and title_tag:
                title = title_tag.text.strip()
                link = link_tag['href']
                if not link.startswith("http"):
                    link = "https://banehstoore.ir" + link
                
                # جلوگیری از تکرار لینک‌های مشابه
                if [btn for btn in kb if btn[0].url == link]: continue
                
                kb.append([InlineKeyboardButton(title, url=link)])
        
        if kb:
            await wait.delete()
            await update.message.reply_text(f"📦 نتایج یافت شده برای '{query}':", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await wait.edit_text("❌ نتایج یافت شد اما استخراج لینک‌ها با خطا مواجه شد.")

    except Exception as e:
        print(f"Detailed Search Error: {e}")
        await wait.edit_text("❌ خطا در برقراری ارتباط با سایت.")

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text
    msg = await update.message.reply_text("⏳ در حال استخراج...")
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        title = soup.find("meta", attrs={"property": "og:title"})["content"]
        img = soup.find("meta", attrs={"property": "og:image"})["content"]
        
        # استخراج و تقسیم قیمت بر ۱۰
        p_elem = soup.find(attrs={"data-price": True}) or soup.find(attrs={"itemprop": "price"})
        p_val = "".join(filter(str.isdigit, p_elem.get("data-price") or p_elem.text))
        price = "{:,} تومان".format(int(p_val)//10) if p_val else "تماس بگیرید"

        caption = f"🛍 **{title}**\n\n💰 قیمت: {price}\n\n🔗 خرید مستقیم 👇"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ثبت سفارش", url=url)], [InlineKeyboardButton("👨‍💻 پشتیبانی", url=SUPPORT_URL)]])
        await context.bot.send_photo(CHANNEL_ID, img, caption, parse_mode='Markdown', reply_markup=kb)
        await msg.edit_text("✅ منتشر شد.")
    except: await msg.edit_text("❌ خطا.")

# --- ۶. اجرا ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        
        admin_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^ورود به پنل مدیریت ⚙️$"), admin_menu)],
            states={ADMIN_PANEL: [MessageHandler(filters.Regex("^آمار ربات 📊$"), bot_stats), MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$"), pre_broadcast)],
                    BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, do_broadcast)]},
            fallbacks=[MessageHandler(filters.Regex("^خروج از پنل 🔙$"), start)],
            allow_reentry=True
        )
        
        user_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
                    PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)],
            allow_reentry=True
        )

        app.add_handler(admin_handler)
        app.add_handler(user_handler)
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_products))
        
        print("🚀 Bot is running...")
        app.run_polling()