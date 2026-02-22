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
    admin_id = os.getenv('ADMIN_ID')

    # اگر کاربر ادمین بود
    if str(user_id) == admin_id:
        keyboard = [["ورود به پنل مدیریت ⚙️"]]
        await update.message.reply_text(
            "سلام مدیر عزیز! به پنل فرماندهی خوش آمدید:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return ConversationHandler.END

    # منطق قبلی برای کاربران عادی (بدون تغییر)
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

# وضعیت‌های جدید برای پنل مدیریت
ADMIN_PANEL, BROADCAST = range(3, 5)

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    
    keyboard = [["آمار ربات 📊", "ارسال پیام همگانی 📢"], ["خروج از پنل 🔙"]]
    await update.message.reply_text(
        "پنل مدیریت فعال شد. یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return ADMIN_PANEL

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        await update.message.reply_text(f"👥 تعداد کل کاربران ثبت‌نام شده: {count} نفر")
    except Exception as e:
        await update.message.reply_text(f"خطا در دریافت آمار: {e}")

async def pre_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لطفاً پیامی که می‌خواهید به همه کاربران ارسال شود را بفرستید (متن یا عکس):")
    return BROADCAST

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        users = cur.fetchall()
        cur.close()
        conn.close()

        success, fail = 0, 0
        for user in users:
            try:
                await context.bot.copy_message(chat_id=user[0], from_chat_id=msg.chat_id, message_id=msg.message_id)
                success += 1
            except:
                fail += 1
        
        await update.message.reply_text(f"✅ ارسال به پایان رسید.\nموفق: {success}\nناموفق (بلاک): {fail}")
    except Exception as e:
        await update.message.reply_text(f"خطا در ارسال: {e}")
    return ADMIN_PANEL

# --- ۴. استخراج محصول (مخصوص میکسین) ---
CHANNEL_ID = "@banehstoore" 
SUPPORT_URL = "https://t.me/+989180514202"

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text
    if not url.startswith("https://banehstoore.ir"): return
    
    msg = await update.message.reply_text("⏳ در حال استخراج اطلاعات دقیق از میکسین...")
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')

        # ۱. استخراج نام و عکس با متد اصلاح شده (بدون خطا)
        title_meta = soup.find("meta", attrs={"property": "og:title"})
        title = title_meta["content"] if title_meta else soup.title.string
        
        img_meta = soup.find("meta", attrs={"property": "og:image"})
        img_url = img_meta["content"] if img_meta else None
        
        # ۲. استخراج قیمت (جستجوی عمیق در ساختار میکسین)
        price = "تماس بگیرید"
        
        # الف) جستجو در تگ‌های دیتای میکسین (دقیق‌ترین روش برای این سایت‌ساز)
        price_element = soup.find(attrs={"data-price": True}) or \
                        soup.find(attrs={"itemprop": "price"}) or \
                        soup.select_one(".product-price") or \
                        soup.select_one(".price-value")

        if price_element:
            # اگر در اتریبیوت بود آن را بردار، در غیر این صورت متن تگ را
            price = price_element.get("data-price") or price_element.get("content") or price_element.text.strip()
        
        # ب) تمیز کردن و فرمت‌دهی عدد قیمت
        if price and price != "تماس بگیرید":
            try:
                # حذف هر چیزی به جز اعداد
                numeric_price = "".join(filter(str.isdigit, str(price)))
                if numeric_price:
                    # تبدیل به عدد، تقسیم بر ۱۰ و گرد کردن
                    final_price = int(numeric_price) // 10
                    # فرمت‌دهی با جداکننده هزارگان
                    price = "{:,}".format(final_price) + " تومان"
            except Exception as e:
                print(f"Price calculation error: {e}")
                pass

        # ۳. موجودی
        stock = "موجود در انبار ✅" if "InStock" in res.text or "موجود" in res.text else "ناموجود ❌"

        caption = f"🛍 **{title}**\n\n💰 قیمت: {price}\n📦 وضعیت: {stock}\n\n🔗 خرید از سایت 👇"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ثبت سفارش و خرید", url=url)],
                                         [InlineKeyboardButton("👨‍💻 پشتیبانی", url=SUPPORT_URL)]])

        if img_url:
            await context.bot.send_photo(chat_id=CHANNEL_ID, photo=img_url, caption=caption, parse_mode='Markdown', reply_markup=keyboard)
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=caption, parse_mode='Markdown', reply_markup=keyboard)
        
        await msg.delete()
    except Exception as e:
        print(f"Detailed Error: {e}")
        await msg.edit_text(f"❌ خطا در استخراج اطلاعات. لینک محصول را بررسی کنید.")

# --- ۵. اجرای نهایی ---
if __name__ == '__main__':
# هندلر مدیریت
        admin_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^ورود به پنل مدیریت ⚙️$"), admin_menu)],
            states={
                ADMIN_PANEL: [
                    MessageHandler(filters.Regex("^آمار ربات 📊$"), bot_stats),
                    MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$"), pre_broadcast),
                ],
                BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, do_broadcast)],
            },
            fallbacks=[MessageHandler(filters.Regex("^خروج از پنل 🔙$"), start)],
        )
        app.add_handler(admin_conv)
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