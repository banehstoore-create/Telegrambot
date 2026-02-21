import os
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ۱. ساخت یک اپلیکیشن ساده Flask برای بیدار ماندن
web_app = Flask('')

@web_app.route('/')
def home():
    return "I am alive!"

def run_flask():
    # Render پورت را از طریق Environment Variable به ما می‌دهد
    port = int(os.environ.get('PORT', 8080))
    web_app.run(host='0.0.0.0', port=port)

# ۲. کد اصلی ربات تلگرام
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات فروشگاهی شما آنلاین است.")

if __name__ == '__main__':
    # اجرای Flask در یک Thread جداگانه که مانع اجرای ربات نشود
    Thread(target=run_flask).start()
    
    # اجرای ربات تلگرام
    TOKEN = os.getenv('BOT_TOKEN')
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    
    print("Bot & WebServer are running...")
    app.run_polling()