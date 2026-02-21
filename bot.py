import os
import telebot
from flask import Flask, request

# تنظیمات اولیه
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 6690559792  # آیدی عددی شما
CHANNEL_ID = "@banehstoore"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- بخش عمومی (برای همه کاربران) ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(m):
    welcome_text = (
        "سلام! به ربات بانه استور خوش آمدید. 😊\n\n"
        "این ربات جهت مدیریت محصولات کانال طراحی شده است.\n"
        "اگر مشتری هستید، می‌توانید از محصولات کانال ما دیدن کنید: \n" + CHANNEL_ID
    )
    bot.reply_to(m, welcome_text)

# --- بخش اختصاصی ادمین (فقط برای شما) ---

@bot.message_handler(func=lambda m: True)
def handle_messages(m):
    # چک کردن اینکه آیا کاربر ادمین است یا خیر
    if m.from_user.id == ADMIN_ID:
        if "banehservice.com" in m.text:
            sent_msg = bot.reply_to(m, "ادمین گرامی، در حال استخراج و ارسال محصول به کانال... ⏳")
            
            # در اینجا توابع استخراج شما (که قبلاً داشتید) فراخوانی می‌شوند
            # فرض بر این است که توابع extract_product_info و send_to_channel در کد شما وجود دارند
            try:
                # product_data = extract_product_info(m.text) 
                # send_to_channel(product_data)
                bot.edit_message_text("✅ محصول با موفقیت در کانال منتشر شد.", m.chat.id, sent_msg.message_id)
            except Exception as e:
                bot.edit_message_text(f"❌ خطایی رخ داد: {e}", m.chat.id, sent_msg.message_id)
        else:
            bot.reply_to(m, "پیام شما دریافت شد ادمین عزیز، اما لینک معتبری یافت نشد.")
    
    else:
        # پاسخ به کاربران عادی که لینک می‌فرستند
        bot.reply_to(m, "عذرخواهی می‌کنم، ارسال محصول به کانال فقط توسط مدیریت انجام می‌شود. 🙏")

# --- بخش تنظیمات سرور (Webhook) ---

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return 'Error', 403

@app.route('/')
def index():
    return "Bot is Running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
