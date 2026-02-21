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

# --- تنظیمات وب‌سرور برای بیدار ماندن ---
web_app = Flask('')
@web_app.route('/')
def home(): return "Bot is Online!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    web_app.run(host='0.0.0.0', port=port)

# --- تنظیمات دیتابیس NEON ---
DB_URL = os.getenv('DATABASE_URL')

def init_db():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            full_name TEXT,
            phone_number TEXT
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# --- مراحل گفت‌وگو (Conversation States) ---
NAME, PHONE = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # چک کردن اینکه کاربر قبلاً ثبت‌نام کرده یا نه
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user:
        await update.message.reply_text(f"خوش آمدید {user[0]} عزیز! چطور می‌توانم کمکتان کنم؟")
        return ConversationHandler.END
    else:
        await update.message.reply_text("سلام! به فروشگاه ما خوش آمدید. برای خدمات بهتر، لطفاً نام و نام خانوادگی خود را وارد کنید:")
        return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    
    # ساخت دکمه درخواست شماره تلفن
    contact_keyboard = [[KeyboardButton("ارسال شماره موبایل 📱", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(contact_keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(f"ممنون {update.message.text}. حالا لطفاً با زدن دکمه زیر، شماره موبایل خود را ارسال کنید:", reply_markup=reply_markup)
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    full_name = context.user_data['full_name']
    user_id = update.effective_user.id
    phone = contact.phone_number

    # ذخیره در دیتابیس Neon
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s, %s, %s)", (user_id, full_name, phone))
    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text("ثبت‌نام شما با موفقیت تکمیل شد! ✅", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

if __name__ == '__main__':
    # ۱. اجرای وب‌سرور
    Thread(target=run_flask).start()
    
    # ۲. آماده‌سازی دیتابیس
    init_db()
    
    # ۳. اجرای ربات
    TOKEN = os.getenv('BOT_TOKEN')
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
    
    print("Bot is running...")
    app.run_polling()