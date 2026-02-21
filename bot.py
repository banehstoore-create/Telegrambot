from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from scraper import scrape_product

BOT_TOKEN = "YOUR_BOT_TOKEN"
ADMIN_ID = 6690559792
CHANNEL_ID = "@banehstoore"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛒 ارسال لینک محصول", callback_data="send")]
    ]
    await update.message.reply_text(
        "سلام 👋\nلینک محصول سایت رو بفرست تا خودکار در کانال منتشر کنم",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    url = update.message.text
    data = scrape_product(url)

    if data["image"]:
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

    await update.message.reply_text("✅ محصول با موفقیت در کانال منتشر شد")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
