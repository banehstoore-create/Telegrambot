import os
import psycopg2
from threading import Thread
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes
)

# --- ۱. وب‌سرور برای زنده نگه داشتن سرور ---
web_app = Flask('')
@web_app.route('/')
def home(): return "Bot is Online!"

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- ۲. تنظیمات هوشمند دیتابیس ---
def get_db_connection():
    raw_url = os.getenv('DATABASE_URL')
    # اصلاح فرمت لینک برای سازگاری با psycopg2
    if raw_url and raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql://", 1)
    
    # حذف پارامترهای دردسرساز و اضافه کردن SSL
    if raw_url and "sslmode" not in raw_url:
        separator = "&" if "?" in raw_url else "?"
        raw_url += f"{separator}sslmode=require"
        
    return psycopg2.connect(raw_url)

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                full_name TEXT,
                phone_number TEXT,
                username TEXT
            )
        ''')
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database initialized successfully!")
    except Exception as e:
        print(f"❌ Database Init Error: {e}")

# --- ۳. منطق ثبت‌نام ربات ---
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
    except: pass # اگر دیتابیس قطع بود، باز هم اجازه بده ثبت‌نام شروع شود

    await update.message.reply_text("سلام! خوش آمدید. لطفاً نام و نام خانوادگی خود را وارد کنید:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    btn = [[KeyboardButton("ارسال شماره موبایل 📱", request_contact=True)]]
    await update.message.reply_text(
        "لطفاً با دکمه زیر شماره خود را تایید کنید:",
        reply_markup=ReplyKeyboardMarkup(btn, one_time_keyboard=True, resize_keyboard=True)
    )
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact:
        await update.message.reply_text("لطفاً فقط از دکمه استفاده کنید.")
        return PHONE

    user_id = update.effective_user.id
    full_name = context.user_data.get('full_name')
    phone = update.message.contact.phone_number
    username = update.effective_user.username or "None"

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (user_id, full_name, phone_number, username) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET phone_number = EXCLUDED.phone_number",
            (user_id, full_name, phone, username)
        )
        conn.commit()
        cur.close()
        conn.close()

        await update.message.reply_text("ثبت‌نام شما با موفقیت انجام شد! ✅", reply_markup=ReplyKeyboardRemove())

        # اطلاع به ادمین
        admin_id = os.getenv('ADMIN_ID')
        if admin_id:
            msg = f"🔔 مشتری جدید:\n👤 {full_name}\n📞 {phone}\n🆔 `{user_id}`"
            await context.bot.send_message(chat_id=admin_id, text=msg, parse_mode='Markdown')

    except Exception as e:
        print(f"Error in saving: {e}")
        await update.message.reply_text("خطایی در ذخیره اطلاعات رخ داد. لطفاً دوباره /start بزنید.")
    
    return ConversationHandler.END

# --- ۴. اجرای نهایی ---
if __name__ == '__main__':
    # بیدار نگه داشتن وب‌سرور
    Thread(target=run_flask, daemon=True).start()
    
    # مقداردهی دیتابیس
    init_db()
    
    # اجرای ربات
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        conv = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
                PHONE: [MessageHandler(filters.CONTACT, get_phone)],
            },
            fallbacks=[CommandHandler('start', start)],
        )
        app.add_handler(conv)
        print("🚀 Bot is running...")
        app.run_polling()