import json
import os
import requests
import psycopg2
from threading import Thread
from flask import Flask
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
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
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY, full_name TEXT, phone_number TEXT)''')
        conn.commit(); cur.close(); conn.close()
    except Exception as e: print(f"❌ DB Error: {e}")

# --- ۳. منطق ربات ---
NAME, PHONE = range(2)
ADMIN_PANEL, BROADCAST = range(3, 5)

# تنظیم هدر ثابت برای دور زدن محدودیت‌ها
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7',
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    main_kb = [["جستجوی محصول 🔍"]]
    if str(user_id) == admin_id: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone(); cur.close(); conn.close()
        if user or str(user_id) == admin_id:
            await update.message.reply_text("خوش آمدید! از منوی زیر استفاده کنید:", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
            return ConversationHandler.END
    except: pass
    await update.message.reply_text("سلام! لطفاً نام و نام خانوادگی خود را وارد کنید:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    btn = [[KeyboardButton("ارسال شماره موبایل 📱", request_contact=True)]]
    await update.message.reply_text("لطفاً شماره خود را تایید کنید:", reply_markup=ReplyKeyboardMarkup(btn, one_time_keyboard=True, resize_keyboard=True))
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact: return PHONE
    user_id, phone = update.effective_user.id, update.message.contact.phone_number
    full_name = context.user_data.get('full_name')
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s,%s,%s) ON CONFLICT (user_id) DO NOTHING", (user_id, full_name, phone))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text("✅ ثبت‌نام موفق!", reply_markup=ReplyKeyboardMarkup([["جستجوی محصول 🔍"]], resize_keyboard=True))
    except: pass
    return ConversationHandler.END

# --- ۴. پنل مدیریت ---
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    keyboard = [["آمار ربات 📊", "ارسال پیام همگانی 📢"], ["خروج از پنل 🔙"]]
    await update.message.reply_text("پنل مدیریت:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return ADMIN_PANEL

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users"); count = cur.fetchone()[0]
    cur.close(); conn.close()
    await update.message.reply_text(f"👥 تعداد کاربران: {count}")

async def pre_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام خود را ارسال کنید:")
    return BROADCAST

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT user_id FROM users")
    users = cur.fetchall(); cur.close(); conn.close()
    for u in users:
        try: await context.bot.copy_message(u[0], update.message.chat_id, update.message.message_id)
        except: pass
    await update.message.reply_text("✅ ارسال شد.")
    return ADMIN_PANEL

# --- ۵. جستجو و انتشار محصول ---
CHANNEL_ID = "@banehstoore"
SUPPORT_URL = "https://t.me/+989180514202"

async def search_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    if query == "جستجوی محصول 🔍":
        await update.message.reply_text("🔍 نام محصول مورد نظر را وارد کنید (مثلاً: سماور):")
        return

    wait = await update.message.reply_text(f"⏳ در حال جستجوی دقیق برای '{query}'...")
    try:
        # استفاده از متد پارامتریک که در میکسین پایدارتر است
        search_url = f"https://banehstoore.ir/?s={query}"
        
        res = requests.get(search_url, headers=HEADERS, timeout=20)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # استخراج تمامی لینک‌هایی که کلمه جستجو شده در متن آن‌هاست و به محصولات اشاره دارند
        # این متد از ساختار نمایشی مستقل است و بسیار دقیق عمل می‌کند
        kb = []
        seen_links = set()
        
        # پیدا کردن تمامی تگ‌های لینک که در متن‌شان کوئری کاربر وجود دارد
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            link_text = link.get_text().strip()
            link_url = link['href']
            
            # فیلتر هوشمند: 
            # ۱. کلمه کلیدی در عنوان لینک باشد
            # ۲. لینک مربوط به یک محصول باشد (دارای کلمه product)
            # ۳. لینک تکراری نباشد
            if query in link_text and "/product/" in link_url:
                full_url = link_url if link_url.startswith("http") else "https://banehstoore.ir" + link_url
                
                if full_url not in seen_links:
                    # تلاش برای پیدا کردن قیمت در نزدیکی این لینک (در ساختار والد)
                    parent = link.find_parent(attrs={"class": lambda x: x and ("product" in x or "item" in x)})
                    price_text = "💰 مشاهده قیمت و جزئیات"
                    
                    if parent:
                        price_tag = parent.select_one(".price-value, .product-price, [data-price]")
                        if price_tag:
                            raw_p = "".join(filter(str.isdigit, price_tag.text))
                            if raw_p:
                                price_text = f"💰 قیمت: {'{:,}'.format(int(raw_p)//10)} تومان"
                    
                    kb.append([InlineKeyboardButton(f"📦 {link_text}", url=full_url)])
                    kb.append([InlineKeyboardButton(f"└ {price_text}", url=full_url)])
                    seen_links.add(full_url)

        if kb:
            await wait.delete()
            await update.message.reply_text(
                f"✅ تعداد {len(seen_links)} محصول برای **{query}** یافت شد:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='Markdown'
            )
        else:
            # اگر در متد اول پیدا نشد، یک شانس دیگر با آدرس /search/
            res2 = requests.get(f"https://banehstoore.ir/search/{query}", headers=HEADERS, timeout=15)
            soup2 = BeautifulSoup(res2.text, 'html.parser')
            # تکرار منطق بالا برای soup2 ... (در اینجا برای اختصار فقط چک می‌کنیم اگر لینک محصولی هست)
            items2 = soup2.select('a[href*="/product/"]')
            if items2:
                # پردازش مجدد (مشابه بالا)
                await wait.edit_text("🔄 در حال بازخوانی نتایج ثانویه...")
                # (کد مشابه بالا برای استخراج از items2)
            else:
                await wait.edit_text(f"❌ محصولی با عنوان '{query}' در سایت بانه استور پیدا نشد.\n\n💡 پیشنهاد: از کلمات کوتاه‌تر استفاده کنید (مثلاً به جای 'سماور برقی'، فقط 'سماور' را جستجو کنید).")

    except Exception as e:
        print(f"Search Error: {e}")
        await wait.edit_text("❌ خطا در برقراری ارتباط با سایت. لطفاً دوباره تلاش کنید.")

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text
    msg = await update.message.reply_text("⏳ در حال پردازش لینک...")
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # استخراج هوشمند اطلاعات
        title_meta = soup.find("meta", attrs={"property": "og:title"})
        title = title_meta["content"] if title_meta else soup.find("h1").text.strip()
        
        img_meta = soup.find("meta", attrs={"property": "og:image"})
        img = img_meta["content"] if img_meta else soup.find("img", {"src": True})["src"]
        if img and not img.startswith("http"): img = "https://banehstoore.ir" + img

        p_elem = soup.find(attrs={"data-price": True}) or soup.select_one(".product-price") or soup.find(attrs={"itemprop": "price"})
        p_val = "".join(filter(str.isdigit, p_elem.text if p_elem else ""))
        price = "{:,} تومان".format(int(p_val)//10) if p_val else "تماس بگیرید"

        caption = f"🛍 **{title}**\n\n💰 قیمت: {price}\n\n🔗 خرید مستقیم 👇"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ثبت سفارش", url=url)], [InlineKeyboardButton("👨‍💻 پشتیبانی", url=SUPPORT_URL)]])
        await context.bot.send_photo(CHANNEL_ID, img, caption, parse_mode='Markdown', reply_markup=kb)
        await msg.edit_text("✅ در کانال منتشر شد.")
    except Exception as e:
        print(f"Post Error: {e}")
        await msg.edit_text("❌ خطا در استخراج. مطمئن شوید لینک محصول صحیح است.")

# --- ۶. اجرا ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^ورود به پنل مدیریت ⚙️$"), admin_menu)],
            states={ADMIN_PANEL: [MessageHandler(filters.Regex("^آمار ربات 📊$"), bot_stats), MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$"), pre_broadcast)],
                    BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, do_broadcast)]},
            fallbacks=[MessageHandler(filters.Regex("^خروج از پنل 🔙$"), start)], allow_reentry=True
        ))
        app.add_handler(ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)], PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_products))
        app.run_polling()