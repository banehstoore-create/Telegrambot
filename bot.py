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

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
SITE_URL = "https://banehstoore.ir"
CHANNEL_ID = "@banehstoore"
SUPPORT_URL = "https://t.me/+989180514202"
MIXIN_API_KEY = os.getenv('MIXIN_API_KEY')

# --- بخش استخراج قیمت دلار (بهینه‌سازی شده با AlanChand) ---
async def get_dollar_price():
    try:
        # استفاده از سایت Alanchand به عنوان منبع پایدار
        url = "https://alanchand.com/en"
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # پیدا کردن سطر مربوط به دلار آمریکا در جدول قیمت‌ها
        rows = soup.find_all('tr')
        price = None
        for row in rows:
            if "US Dollar" in row.get_text():
                cols = row.find_all('td')
                if len(cols) >= 3:
                    price = cols[2].get_text().strip() # ستون قیمت فروش
                    break
        
        if price:
            return f"💵 <b>قیمت لحظه‌ای دلار آمریکا:</b>\n\n💰 قیمت: <code>{price}</code> ریال\n✨ #بانه_استور"
        
        #Fallback به منبع دوم در صورت لزوم
        return "❌ متأسفانه قیمت در این لحظه دریافت نشد. لطفاً از دکمه پشتیبانی برای استعلام دستی استفاده کنید."
    except Exception as e:
        return f"❌ خطا در اتصال به مرجع قیمت."

async def show_dollar_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait = await update.message.reply_text("⏳ در حال استعلام قیمت از بازار آزاد...")
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
        "جهت ارتباط در سایر شبکه‌ها از دکمه‌های زیر استفاده کنید:"
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
                
                items_text = ""
                for idx, item in enumerate(data.get('items', []), 1):
                    p_name = item.get('product_title') or item.get('name') or "محصول"
                    items_text += f"{idx}. {p_name} (تعداد: {item.get('quantity', 1)})\n"

                invoice_url = f"{SITE_URL}/invoice/{order_no}/"
                msg = (f"📦 **اطلاعات سفارش {order_no}**\n\n"
                       f"👤 **تحویل گیرنده:** {customer_name}\n"
                       f"🚩 **وضعیت:** {status}\n"
                       f"💰 **مبلغ:** {total_price}\n"
                       f"📍 **آدرس:** {full_address}\n"
                       f"🆔 **کد رهگیری:** `{tracking_code if tracking_code else 'هنوز صادر نشده'}`\n\n"
                       f"📝 **اقلام:**\n{items_text}\n"
                       f"🔗 [مشاهده فاکتور در سایت]({invoice_url})")

                await wait.edit_text(msg, parse_mode='Markdown', disable_web_page_preview=False)
                return ConversationHandler.END
        except Exception as e: print(f"API Error: {e}")

    await wait.edit_text(f"❌ سفارش #{order_no} یافت نشد.")
    return ConversationHandler.END

# --- ۵. بخش جستجو و دسته‌بندی ---
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 نام محصول را وارد کنید:")
    return SEARCH_QUERY

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    ignore = ["جستجوی محصول 🔍", "پیگیری سفارش 📦", "ورود به پنل مدیریت ⚙️", "🗂 دسته‌بندی محصولات", "💰 استعلام قیمت لحظه‌ای", "📞 پشتیبانی و مشاوره", "💵 قیمت لحظه‌ای دلار"]
    if query in ignore: return ConversationHandler.END
    wait = await update.message.reply_text(f"⏳ در حال جستجو...")
    try:
        res = requests.get(f"{SITE_URL}/search?q={query}", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        kb, seen = [], set()
        for link in soup.find_all('a', href=True):
            url = link['href'] if link['href'].startswith('http') else SITE_URL + link['href']
            title = link.get_text().strip()
            if "/product/" in url and len(title) > 8 and url not in seen:
                clean_title = re.sub(r'مشاهده|خرید|تومان|قیمت', '', title).strip()
                kb.append([InlineKeyboardButton(f"📦 {clean_title}", url=url)])
                seen.add(url)
            if len(kb) >= 15: break
        if kb: await wait.delete(); await update.message.reply_text("✅ نتایج:", reply_markup=InlineKeyboardMarkup(kb))
        else: await wait.edit_text("❌ یافت نشد.")
    except: await wait.edit_text("❌ خطا.")
    return ConversationHandler.END 

async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait = await update.message.reply_text("⏳ دریافت دسته‌بندی‌ها...")
    try:
        res = requests.get(f"{SITE_URL}/api/management/v1/categories/", headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=15)
        if res.status_code == 200:
            cats = res.json().get('result', [])
            keyboard, row = [], []
            for c in cats:
                url = f"{SITE_URL}/category/{c['id']}/{quote(c['name'].replace(' ', '-'))}/"
                row.append(InlineKeyboardButton(c['name'], url=url))
                if len(row) == 2: keyboard.append(row); row = []
            if row: keyboard.append(row)
            await wait.delete(); await update.message.reply_text("🗂 دسته‌بندی محصولات:", reply_markup=InlineKeyboardMarkup(keyboard))
        else: await wait.edit_text("❌ خطا.")
    except: await wait.edit_text("❌ خطای فنی.")

# --- بخش مدیریت و ثبت‌نام ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, aid = update.effective_user.id, os.getenv('ADMIN_ID')
    main_kb = [
        ["جستجوی محصول 🔍", "پیگیری سفارش 📦"], 
        ["🗂 دسته‌بندی محصولات", "💰 استعلام قیمت لحظه‌ای"],
        ["💵 قیمت لحظه‌ای دلار", "📞 پشتیبانی و مشاوره"]
    ]
    if str(uid) == aid: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE user_id = %s", (uid,))
    user = cur.fetchone(); cur.close(); conn.close()
    if user or str(uid) == aid:
        name = user[0] if user else "مدیریت"
        await update.message.reply_text(f"سلام {name} عزیز، خوش آمدید:", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
        return ConversationHandler.END
    await update.message.reply_text("سلام! نام و نام خانوادگی خود را وارد کنید:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    btn = [[KeyboardButton("ارسال شماره موبایل 📱", request_contact=True)]]
    await update.message.reply_text("تایید شماره:", reply_markup=ReplyKeyboardMarkup(btn, one_time_keyboard=True, resize_keyboard=True))
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact: return PHONE
    uid, ph, nm = update.effective_user.id, update.message.contact.phone_number, context.user_data.get('name')
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, full_name, phone_number) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (uid, nm, ph))
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text(f"✅ ثبت شد.", reply_markup=ReplyKeyboardMarkup([["جستجوی محصول 🔍", "پیگیری سفارش 📦"], ["🗂 دسته‌بندی محصولات", "💰 استعلام قیمت لحظه‌ای"], ["💵 قیمت لحظه‌ای دلار", "📞 پشتیبانی و مشاوره"]], resize_keyboard=True))
    return ConversationHandler.END

# --- ۷. پنل ادمین ---
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    kb = [["آمار ربات 📊", "ارسال پیام همگانی 📢"], ["خروج از پنل 🔙"]]
    await update.message.reply_text("🛠 پنل مدیریت:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADMIN_PANEL

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM users")
    await update.message.reply_text(f"👥 کاربران: {cur.fetchone()[0]}"); cur.close(); conn.close()

async def pre_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام را بفرستید:"); return BROADCAST

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT user_id FROM users")
    for u in cur.fetchall():
        try: await context.bot.copy_message(u[0], update.message.chat_id, update.message.message_id)
        except: pass
    cur.close(); conn.close(); await update.message.reply_text("✅ ارسال شد."); return ADMIN_PANEL

# --- بخش ارسال محصول (با اصلاح دکمه پشتیبانی ثابت) ---
async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text.strip(); p_match = re.search(r'/product/(\d+)/', url)
    if not p_match: return
    p_id = p_match.group(1); wait = await update.message.reply_text(f"⏳ انتشار...")
    try:
        res = requests.get(f"{SITE_URL}/api/management/v1/products/{p_id}/", headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=15)
        if res.status_code == 200:
            d = res.json()
            name, price = d.get('name', 'محصول'), d.get('price', 0)
            old = d.get('old_price') or d.get('original_price')
            stk = d.get('inventory') or d.get('stock')
            status = f"✅ موجود ({stk} عدد)" if stk and int(stk) > 0 else "❌ ناموجود"
            
            cap = f"🛍 <b>{name}</b>\n\n💰 <b>قیمت ویژه:</b> {'{:,}'.format(int(price))} تومان\n"
            if old and int(old) > int(price): cap += f"❌ <b>قیمت قبل:</b> <s>{'{:,}'.format(int(old))}</s> تومان\n"
            cap += f"📦 <b>وضعیت:</b> {status}\n\n🚚 ارسال سریع | 💎 ضمانت اصالت\n\n✨ #بانه_استور"

            # بازگرداندن دکمه پشتیبانی زیر دکمه خرید
            kb = [
                [InlineKeyboardButton("🛒 خرید آنلاین", url=url)],
                [InlineKeyboardButton("💬 مشاوره و پشتیبانی", url=SUPPORT_URL)]
            ]
            
            img = None
            try:
                soup = BeautifulSoup(requests.get(url, headers=HEADERS).text, 'html.parser')
                meta = soup.find('meta', property='og:image')
                if meta: img = meta['content']
            except: pass
            
            if img: await context.bot.send_photo(CHANNEL_ID, photo=img, caption=cap, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
            else: await context.bot.send_message(CHANNEL_ID, text=cap, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
            await wait.edit_text("✅ منتشر شد.")
    except: await wait.edit_text("❌ خطا.")

# --- ۹. بخش استعلام قیمت دستی ---
async def ask_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 استعلام قیمت: نام محصول یا لینک را بفرستید:", reply_markup=ReplyKeyboardMarkup([["انصراف 🔙"]], resize_keyboard=True))
    return ASK_PRICE

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "انصراف 🔙": return await start(update, context)
    aid = os.getenv('ADMIN_ID')
    msg = f"📩 **استعلام قیمت**\n👤 {update.effective_user.full_name}\n🆔 `ID:{update.effective_user.id}`\n\n{update.message.text}"
    await context.bot.send_message(chat_id=aid, text=msg, parse_mode='Markdown')
    await update.message.reply_text("✅ ارسال شد."); return ConversationHandler.END

async def admin_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID') or not update.message.reply_to_message: return
    try:
        uid = re.search(r'ID:(\d+)', update.message.reply_to_message.text).group(1)
        await context.bot.send_message(chat_id=uid, text=f"💰 **پاسخ بانه استور:**\n\n{update.message.text}", parse_mode='Markdown')
        await update.message.reply_text("✅ ارسال شد.")
    except: pass

async def process_pasted_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    try:
        oid = re.search(r'شماره\s*:\s*(\d+)', update.message.text).group(1)
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO orders (order_id, items) VALUES (%s, %s) ON CONFLICT (order_id) DO UPDATE SET items=EXCLUDED.items", (oid, update.message.text))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text(f"✅ فاکتور {oid} ذخیره شد.")
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