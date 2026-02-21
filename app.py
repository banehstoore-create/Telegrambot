import os
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN")

flask_app = Flask(__name__)

application = Application.builder().token(BOT_TOKEN).build()


@flask_app.route("/", methods=["POST", "GET"])
async def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), application.bot)
        await application.process_update(update)
        return "ok"
    return "Bot is running"


@application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("ربات فعال است ✅"))):
    pass


if __name__ == "__main__":
    flask_app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
