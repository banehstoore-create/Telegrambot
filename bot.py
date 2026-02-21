from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from scraper import scrape_product
import os

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 6690559792
CHANNEL_ID = "@banehstoore"

app = Flask(__name__)
bot = Bot(token=TOKEN)
application = Application.builder().bot(bot).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لینک محصول سایت رو ارسال کن 🛒")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    data = scrape_product(update.message.text)

    if data["image"]:
        await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=data["image"],
            caption=data["caption"]
        )
    else:
        await context.bot.send_message(
            chat_id=CHANNEL_ID, text=data["caption"]
        )

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

@app.route("/", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    application.update_queue.put_nowait(update)
    return "ok"
