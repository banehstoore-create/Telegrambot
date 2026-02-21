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

# --- ۱. تنظیمات وب‌سرور برای بیدار ماندن در Render ---
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    # Render پورت را به صورت خودکار تعیین می‌کند
    port = int(os.environ.get('PORT', 8080))
    web_app.run(host='0.0.0.0', port=port)

# --- ۲. تنظیمات دیتابیس NEON ---
DB_URL = os.getenv('DATABASE_URL')
ADMIN_ID = os.getenv('ADMIN_ID')
TOKEN = os.getenv('BOT_TOKEN')

def init_db():
    """ایجاد جدول کاربران در صورتی که وجود نداشته باشد"""
    conn = psycopg2.connect(DB_URL)
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

# --- ۳. مراحل گفت‌وگو (Conversation States) ---
NAME, PHONE = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # بررسی وجود کاربر در دیتابیس
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user:
        await update.message.reply_text(f"خوش آمدید {user[0]} عزیز! به فروشگاه ما خوش آمدید. 🛍")
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "سلام! برای دسترسی به خدمات فروشگاه، ابتدا باید ثبت‌نام کنید.\n\n"
            "لطفاً **نام و نام خانوادگی** خود را وارد کنید:"
        )
        return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    
    # دکمه درخواست شماره تماس
    contact_keyboard = [[KeyboardButton("ارسال شماره موبایل 📱", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(contact_keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        f"ممنون {update.message.text}. حالا لطفاً با زدن دکمه زیر، شماره موبایل خود را تایید کنید:",
        reply_markup=reply_markup
    )
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact:
        await update.message.reply_text("لطفاً فقط از دکمه زیر برای ارسال شماره استفاده کنید.")
        return PHONE

    contact = update.message.contact
    full_name = context.user_data['full_name']
    user_id = update.effective_user.id
    username = update.effective_user.username or "No Username"
    phone = contact.phone_number

    # ذخیره در دیتابیس
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (user_id, full_name, phone_number, username) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (user_id) DO NOTHING",
            (user_id, full_name, phone, username)
        )
        conn.commit()
        cur.close()
        conn.close()

        # تایید به کاربر
        await update.message.reply_text(
            "ثبت‌نام شما با موفقیت تکمیل شد! ✅\nحالا می‌توانید از منوی فروشگاه استفاده کنید.",
            reply_markup=ReplyKeyboardRemove()
        )

        # اطلاع‌رسانی به ادمین
        if ADMIN_ID:
            admin_msg = (
                f"🔔 **عضو جدید در ربات!**\n\n"
                f"👤 نام: {full_name}\n"
                f"📞 شماره: `{phone}`\n"
                f"🆔 آیدی: `{user_id}`\n"
                f"🏷 یوزرنیم: @{username}"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode='Markdown')

    except Exception as e:
        print(f"Error: {e}")
        await update.message.reply_text("خطایی در ثبت اطلاعات رخ داد. لطفاً دوباره /start را بزنید.")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ثبت‌نام لغو شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- ۴. اجرای اصلی برنامه ---
if __name__ == '__main__':
    # راه اندازی دیتابیس و وب‌سرور
    init_db()
    Thread(target=run_flask).start()
    
    # راه‌اندازی ربات
    if not TOKEN:
        print("Error: BOT_TOKEN not found in environment variables!")
    else:
        app = ApplicationBuilder().token(TOKEN).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
                PHONE: [MessageHandler(filters.CONTACT, get_phone)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        app.add_handler(conv_handler)
        
        print("Bot is up and running...")
        app.run_polling()