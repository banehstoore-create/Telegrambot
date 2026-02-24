import json
import os
import requests
import psycopg2
import re
from urllib.parse import quote
from threading import Thread
from flask import Flask
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
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
        cur.execute('''CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, customer_name TEXT, items TEXT, total_price TEXT, status TEXT)''')
        conn.commit(); cur.close(); conn.close()
    except Exception as e: print(f"❌ DB Error: {e}")

# --- ۳. تنظیمات ثابت ---
NAME, PHONE = range(2)
SEARCH_QUERY = 10
ADMIN_PANEL, BROADCAST = range(3, 5)
TRACK_ORDER = 15
ASK_PRICE = 20

HEADERS = {'User-Agent': 'Mozilla/5.0'}
SITE_URL = "https://banehstoore.ir"
CHANNEL_ID = "@banehstoore"
SUPPORT_URL = "https://t.me/+989180514202"
MIXIN_API_KEY = os.getenv('MIXIN_API_KEY')

# --- بخش استخراج قیمت دلار ---
async def get_dollar_price():
    try:
        url = "https://www.tgju.org/profile/price_dollar_rl"
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        price_element = soup.find('span', {'data-qtoken': 'current_price'})
        if price_element:
            price_text = price_element.get_text().strip()
            return f"💵 <b>قیمت لحظه‌ای دلار آمریکا:</b>\n\n💰 قیمت: <code>{price_text}</code> ریال\n✨ #بانه_استور"
        return "❌ متأسفانه در حال حاضر امکان دریافت قیمت وجود ندارد."
    except:
        return "❌ خطا در برقراری ارتباط با سایت مرجع."

async def show_dollar_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait = await update.message.reply_text("⏳ در حال استعلام قیمت دلار...")
    message = await get_dollar_price()
    await wait.delete()
    await update.message.reply_text(message, parse_mode='HTML')

# --- بخش پشتیبانی و مشاوره ---
async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📍 آدرس فروشگاه", url="https://maps.app.goo.gl/eWv6njTbL8ivfbYa6")],
        [InlineKeyboardButton("💬 ارتباط در واتس‌اپ", url="https://wa.me/989180514202")],
        [InlineKeyboardButton("📢 کانال تلگرامی", url="https://t.me/banehstoore"),
         InlineKeyboardButton("🌐 آدرس سایت", url="https://banehstoore.ir")],
        [InlineKeyboardButton("📸 پیج اینستاگرام", url="https://instagram.com/banehstoore.ir")]
    ]
    msg = (
        "🎧 **بخش پشتیبانی و مشاوره بانه استور**\n\n"
        "📞 **شماره تماس:** `09180514202`\n"
        "*(برای تماس مستقیم، روی شماره بالا کلیک کنید)*\n\n"
        "جهت ارتباط در سایر شبکه‌ها و دسترسی به آدرس ما از دکمه‌های زیر استفاده کنید:"
    )
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# --- ۴. بخش پیگیری سفارش ---
async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔢 لطفاً شماره سفارش خود را وارد کنید:")
    return TRACK_ORDER

async def do_track_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_no = update.message.text.strip()
    wait = await update.message.reply_text("⏳ در حال استخراج اطلاعات از بانه استور...")
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT items FROM orders WHERE order_id = %s", (order_no,))
        local_order = cur.fetchone(); cur.close(); conn.close()
        if local_order:
            await wait.edit_text(f"📄 **جزئیات فاکتور (ثبت دستی):**\n\n{local_order[0]}", parse_mode='Markdown')
            return ConversationHandler.END
    except Exception as e: print(f"DB Error: {e}")
    if MIXIN_API_KEY:
        try:
            api_url = f"{SITE_URL}/api/management/v1/orders/{order_no}/"
            res = requests.get(api_url, headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=12)
            if res.status_code == 200:
                data = res.json()
                customer_name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip() or "نامشخص"
                status_map = {"pending": "⏳ در انتظار بررسی", "paid": "✅ پرداخت شده", "canceled": "❌ لغو شده", "preparing": "📦 در حال آماده‌سازی", "sent": "🚚 ارسال شده"}
                status = status_map.get(data.get('status', 'pending').lower(), data.get('status'))
                f_price = data.get('final_price')
                total_price = "{:,} تومان".format(int(f_price)) if f_price else "نامشخص"
                full_address = f"{data.get('shipping_province', '')}، {data.get('shipping_city', '')}، {data.get('shipping_address', '')}".strip('، ')
                tracking_code = data.get('shipping_tracking_code')
                items_text = "".join([f"{i+1}. {item.get('product_title') or 'محصول'} (تعداد: {item.get('quantity', 1)})\n" for i, item in enumerate(data.get('items', []))])
                invoice_url = f"{SITE_URL}/invoice/{order_no}/"
                msg = (f"📦 **اطلاعات سفارش {order_no}**\n\n👤 **تحویل گیرنده:** {customer_name}\n🚩 **وضعیت:** {status}\n💰 **مبلغ:** {total_price}\n📍 **آدرس:** {full_address}\n🆔 **کد رهگیری:** `{tracking_code or 'هنوز صادر نشده'}`\n\n📝 **اقلام:**\n{items_text}\n🔗 [مشاهده فاکتور در سایت]({invoice_url})")
                await wait.edit_text(msg, parse_mode='Markdown', disable_web_page_preview=False)
                return ConversationHandler.END
        except: pass
    await wait.edit_text(f"❌ سفارش #{order_no} یافت نشد.")
    return ConversationHandler.END

# --- ۵. بخش جستجو و دسته‌بندی ---
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 نام محصول مورد نظر را وارد کنید:")
    return SEARCH_QUERY

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if query in ["جستجوی محصول 🔍", "پیگیری سفارش 📦", "ورود به پنل مدیریت ⚙️", "🗂 دسته‌بندی محصولات", "💰 استعلام قیمت لحظه‌ای", "📞 پشتیبانی و مشاوره", "💵 قیمت لحظه‌ای دلار"]: return ConversationHandler.END
    wait = await update.message.reply_text(f"⏳ در حال جستجو برای «{query}»...")
    try:
        res = requests.get(f"{SITE_URL}/search?q={query}", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        kb, seen = [], set()
        for link in soup.find_all('a', href=True):
            url = link['href']; title = link.get_text().strip()
            if url.startswith('/'): url = SITE_URL + url
            if "/product/" in url and len(title) > 8:
                clean_title = re.sub(r'مشاهده|خرید|افزودن|تومان|قیمت', '', title).strip()
                if url not in seen and clean_title:
                    kb.append([InlineKeyboardButton(f"📦 {clean_title}", url=url)])
                    seen.add(url)
            if len(kb) >= 15: break
        if kb:
            await wait.delete()
            await update.message.reply_text(f"✅ نتایج یافت شده:", reply_markup=InlineKeyboardMarkup(kb))
        else: await wait.edit_text(f"❌ محصولی پیدا نشد.")
    except: await wait.edit_text("❌ خطا در اتصال به سایت.")
    return ConversationHandler.END 

async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait = await update.message.reply_text("⏳ در حال دریافت لیست دسته‌بندی‌ها...")
    try:
        api_url = f"{SITE_URL}/api/management/v1/categories/"
        res = requests.get(api_url, headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=15)
        if res.status_code == 200:
            data = res.json(); categories = data.get('result', []) 
            if not categories: await wait.edit_text("📂 دسته‌بندی فعالی یافت نشد."); return
            keyboard, temp_row = [], []
            for cat in categories:
                c_id, c_name = cat.get('id'), cat.get('name', 'دسته')
                cat_url = f"{SITE_URL}/category/{c_id}/{quote(c_name.replace(' ', '-'))}/"
                temp_row.append(InlineKeyboardButton(c_name, url=cat_url))
                if len(temp_row) == 2: keyboard.append(temp_row); temp_row = []
            if temp_row: keyboard.append(temp_row)
            await wait.delete()
            await update.message.reply_text("🗂 **دسته‌بندی محصولات بانه استور**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else: await wait.edit_text(f"❌ خطا در دریافت دسته‌بندی.")
    except Exception as e: await wait.edit_text(f"❌ خطای فنی: {str(e)}")

# --- ۹. بخش استعلام قیمت ---
async def ask_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 **استعلام قیمت لحظه‌ای**\n\nلطفاً نام محصول یا لینک آن را بفرستید:", reply_markup=ReplyKeyboardMarkup([["انصراف 🔙"]], resize_keyboard=True))
    return ASK_PRICE

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "انصراف 🔙": return await start(update, context)
    user = update.effective_user; admin_id = os.getenv('ADMIN_ID')
    msg = f"📩 **استعلام قیمت جدید**\n\n👤 مشتری: {user.full_name}\n🆔 کد کاربر: `ID:{user.id}`\n\n📝 متن درخواست:\n{update.message.text}"
    await context.bot.send_message(chat_id=admin_id, text=msg, parse_mode='Markdown')
    await update.message.reply_text("✅ درخواست شما ارسال شد.")
    return ConversationHandler.END

async def admin_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID') or not update.message.reply_to_message: return
    try:
        user_id = re.search(r'ID:(\d+)', update.message.reply_to_message.text).group(1)
        resp = f"💰 **پاسخ کارشناس بانه استور:**\n\n{update.message.text}"
        await context.bot.send_message(chat_id=user_id, text=resp, parse_mode='Markdown')
        await update.message.reply_text("✅ پاسخ برای مشتری ارسال شد.")
    except: await update.message.reply_text("❌ خطا در شناسایی کاربر.")

# --- ۶. مدیریت و ثبت‌نام ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, admin_id = update.effective_user.id, os.getenv('ADMIN_ID')
    main_kb = [
        ["جستجوی محصول 🔍", "پیگیری سفارش 📦"], 
        ["🗂 دسته‌بندی محصولات", "💰 استعلام قیمت لحظه‌ای"],
        ["💵 قیمت لحظه‌ای دلار", "📞 پشتیبانی و مشاوره"]
    ]
    if str(user_id) == admin_id: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
    user_row = cur.fetchone(); cur.close(); conn.close()
    if user_row or str(user_id) == admin_id:
        user_name = user_row[0] if user_row else "مدیریت عزیز"
        await update.message.reply_text(f"سلام {user_name} عزیز، خوش آمدید:", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
        return ConversationHandler.END
    await update.message.reply_text("سلام! نام و نام خانوادگی خود را وارد کنید:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    btn = [[KeyboardButton("ارسال شماره موبایل 📱", request_contact=True)]]
    await update.message.reply_text("لطفاً شماره خود را تایید کنید:", reply_markup=ReplyKeyboardMarkup(btn, one_time_keyboard=True, resize_keyboard=True))
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact: return PHONE
    user_id, phone, name = update.effective_user.id, update.message.contact.phone_number, context.user_data.get('full_name')
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (user_id, name, phone))
    conn.commit(); cur.close(); conn.close()
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        alert = f"🆕 **کاربر جدید!**\n👤 نام: {name}\n📞 شماره: `{phone}`\n🆔 آیدی: `{user_id}`"
        try: await context.bot.send_message(chat_id=admin_id, text=alert, parse_mode='Markdown')
        except: pass
    await update.message.reply_text(f"✅ {name} عزیز، خوش آمدید!", reply_markup=ReplyKeyboardMarkup([
        ["جستجوی محصول 🔍", "پیگیری سفارش 📦"], 
        ["🗂 دسته‌بندی محصولات", "💰 استعلام قیمت لحظه‌ای"],
        ["💵 قیمت لحظه‌ای دلار", "📞 پشتیبانی و مشاوره"]
    ], resize_keyboard=True))
    return ConversationHandler.END

# --- ۷. پنل ادمین ---
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    kb = [["آمار ربات 📊", "ارسال پیام همگانی 📢"], ["خروج از پنل 🔙"]]
    await update.message.reply_text("🛠 پنل مدیریت:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADMIN_PANEL

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM users")
    await update.message.reply_text(f"👥 تعداد کاربران: {cur.fetchone()[0]}"); cur.close(); conn.close()

async def pre_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام را بفرستید:"); return BROADCAST

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT user_id FROM users")
    for u in cur.fetchall():
        try: await context.bot.copy_message(u[0], update.message.chat_id, update.message.message_id)
        except: pass
    cur.close(); conn.close()
    await update.message.reply_text("✅ ارسال شد."); return ADMIN_PANEL

# --- بخش ارسال محصول به کانال (به‌روزرسانی شده با کپشن سفارشی و دکمه پشتیبانی) ---
async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text.strip(); p_match = re.search(r'/product/(\d+)/', url)
    if not p_match: return
    p_id = p_match.group(1); wait = await update.message.reply_text(f"⏳ در حال استخراج و انتشار...")
    try:
        res = requests.get(f"{SITE_URL}/api/management/v1/products/{p_id}/", headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            name, price = data.get('name', 'محصول'), data.get('price', 0)
            old_price = data.get('old_price') or data.get('original_price')
            stock = data.get('inventory') or data.get('stock')
            status_text = f"✅ موجود ({stock} عدد)" if stock and int(stock) > 0 else "❌ ناموجود"
            
            caption = f"🛍 <b>{name}</b>\n\n💰 <b>قیمت ویژه:</b> {'{:,}'.format(int(price))} تومان\n"
            if old_price and int(old_price) > int(price):
                caption += f"❌ <b>قیمت قبل:</b> <s>{'{:,}'.format(int(old_price))}</s> تومان\n"
            caption += f"📦 <b>وضعیت:</b> {status_text}\n\n🚚 ارسال سریع | 💎 ضمانت اصالت\n\n✨ #بانه_استور"

            kb = [
                [InlineKeyboardButton("🛒 خرید آنلاین", url=url)],
                [InlineKeyboardButton("💬 مشاوره و پشتیبانی", url=SUPPORT_URL)]
            ]
            
            image_url = None
            try:
                html_res = requests.get(url, headers=HEADERS, timeout=15)
                soup = BeautifulSoup(html_res.text, 'html.parser')
                meta_img = soup.find('meta', property='og:image')
                if meta_img: image_url = meta_img['content']
            except: pass
            
            if image_url: await context.bot.send_photo(CHANNEL_ID, photo=image_url, caption=caption, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
            else: await context.bot.send_message(CHANNEL_ID, text=caption, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
            await wait.edit_text("✅ محصول با موفقیت منتشر شد.")
    except Exception as e: await wait.edit_text(f"❌ خطا: {e}")

async def process_pasted_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    try:
        order_id = re.search(r'شماره\s*:\s*(\d+)', update.message.text).group(1)
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO orders (order_id, items) VALUES (%s, %s) ON CONFLICT (order_id) DO UPDATE SET items=EXCLUDED.items", (order_id, update.message.text))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text(f"✅ فاکتور {order_id} ذخیره شد.")
    except: pass

# --- ۸. اجرای اصلی ربات ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.REPLY & filters.Chat(int(os.getenv('ADMIN_ID', 0))), admin_reply_handler))
        app.add_handler(MessageHandler(filters.Regex("^🗂 دسته‌بندی محصولات$"), show_categories))
        app.add_handler(MessageHandler(filters.Regex("^📞 پشتیبانی و مشاوره$"), show_support)) 
        app.add_handler(MessageHandler(filters.Regex("^💵 قیمت لحظه‌ای دلار$"), show_dollar_price))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'جزییات سفارش شماره'), process_pasted_invoice))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^💰 استعلام قیمت لحظه‌ای$"), ask_price_start)],
            states={ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, forward_to_admin)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^جستجوی محصول 🔍$"), search_start)],
            states={SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_search)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^پیگیری سفارش 📦$"), track_order_start)],
            states={TRACK_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_track_order)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^ورود به پنل مدیریت ⚙️$"), admin_menu)],
            states={
                ADMIN_PANEL: [MessageHandler(filters.Regex("^آمار ربات 📊$"), bot_stats), MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$"), pre_broadcast)],
                BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, do_broadcast)]
            },
            fallbacks=[MessageHandler(filters.Regex("^خروج از پنل 🔙$"), start)], allow_reentry=True
        ))
        app.add_handler(ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)], PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        app.run_polling()