import os
import asyncio
from flask import Flask, request

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from scraper import scrape_product

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 6690559792
CHANNEL_ID = "@banehstoore"

flask_app = Flask(__name__)

# ساخت Application تلگرام (بدون Updater)
application = Application.builder().token(BOT_TOKEN).build()

# ===== handlers =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋\nلطفاً لینک محصول سایت بانه استور را ارسال کن 🛒"
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    url = update.message.text
    data = scrape_product(url)

    if data.get("image"):
        await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=data["image"],
            caption=data["caption"]
        )
    else:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=data["caption"]
        )

    await update.message.reply_text("✅ محصول در کانال منتشر شد")

# ثبت هندلرها
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

# ===== webhook endpoint =====
@flask_app.route("/", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.get_event_loop().create_task(application.process_update(update))
    return "ok"
