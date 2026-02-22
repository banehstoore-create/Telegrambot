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

# --- ۳. منطق ثبت‌نام ---
NAME, PHONE = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user:
            await update.message.reply_text(f"خوش آمدید {user[0]} عزیز! 🛍")
            return ConversationHandler.END
    except: pass
    await update.message.reply_text("سلام! خوش آمدید. لطفاً نام و نام خانوادگی خود را وارد کنید:")
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
        await update.message.reply_text("✅ ثبت‌نام موفق!", reply_markup=ReplyKeyboardRemove())
        admin_id = os.getenv('ADMIN_ID')
        if admin_id: await context.bot.send_message(chat_id=admin_id, text=f"👤 مشتری: {full_name}\n📞 {phone}")
    except Exception as e: print(f"Save Error: {e}")
    return ConversationHandler.END

# --- ۴. استخراج محصول (مخصوص میکسین) ---
CHANNEL_ID = "@banehstoore" 
SUPPORT_URL = "https://t.me/+989180514202"

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text
    if not url.startswith("https://banehstoore.ir"): return
    
    msg = await update.message.reply_text("⏳ در حال استخراج قیمت هوشمند...")
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')

        # استخراج نام و عکس
        title = soup.find("meta", property="og:title")["content"] if soup.find("meta", property="og:title") else soup.title.string
        img_url = soup.find("meta", property="og:image")["content"] if soup.find("meta", property="og:image") else None
        
        # --- استخراج قیمت به روش JSON-LD (مخصوص سایت‌های مدرن و میکسین) ---
        price = "تماس بگیرید"
        try:
            # جستجو در اسکریپت‌های مخصوص گوگل (Schema.org)
            json_ld = soup.find_all('script', type='application/ld+json')
            for script in json_ld:
                data = json.loads(script.string)
                # اگر لیست بود یا دیکشنری
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Product" or "offers" in item:
                        offers = item.get("offers")
                        if isinstance(offers, dict):
                            price = offers.get("price")
                        elif isinstance(offers, list):
                            price = offers[0].get("price")
                        break
        except:
            pass

        # اگر قیمت پیدا شد، فرمت‌بندی کن
        if price and price != "تماس بگیرید":
            try:
                # جدا کردن سه رقم سه رقم برای زیبایی
                price = "{:,}".format(int(float(price))) + " تومان"
            except:
                price = str(price) + " تومان"
        
        # موجودی
        stock = "موجود در انبار ✅" if "InStock" in res.text or "موجود" in res.text else "ناموجود ❌"

        caption = f"🛍 **{title}**\n\n💰 قیمت: {price}\n📦 وضعیت: {stock}\n\n🔗 خرید از سایت 👇"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ثبت سفارش و خرید", url=url)],
                                         [InlineKeyboardButton("👨‍💻 پشتیبانی", url=SUPPORT_URL)]])

        if img_url:
            await context.bot.send_photo(chat_id=CHANNEL_ID, photo=img_url, caption=caption, parse_mode='Markdown', reply_markup=keyboard)
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=caption, parse_mode='Markdown', reply_markup=keyboard)
        
        await msg.delete() # حذف پیام در حال استخراج
    except Exception as e:
        await msg.edit_text(f"❌ خطا: {str(e)}")
# --- ۵. اجرای نهایی ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
                    PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)]))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        print("🚀 Bot is running...")
        app.run_polling()