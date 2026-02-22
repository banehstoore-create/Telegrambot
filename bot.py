import json
import os
import requests
import psycopg2
import re
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

HEADERS = {'User-Agent': 'Mozilla/5.0'}
SITE_URL = "https://banehstoore.ir"
CHANNEL_ID = "@banehstoore"
SUPPORT_URL = "https://t.me/+989180514202"
MIXIN_API_KEY = os.getenv('MIXIN_API_KEY')

# --- ۴. بخش پیگیری سفارش (نسخه نهایی با کد رهگیری پستی) ---

# --- بخش پیگیری سفارش (نسخه نهایی + دکمه مستقیم سامانه پست) ---

async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔢 لطفاً شماره سفارش خود را وارد کنید:")
    return TRACK_ORDER

async def do_track_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_no = update.message.text.strip()
    wait = await update.message.reply_text("⏳ در حال استخراج اطلاعات از بانه استور...")
    
    # دیتابیس داخلی
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT items FROM orders WHERE order_id = %s", (order_no,))
        local_order = cur.fetchone(); cur.close(); conn.close()
        if local_order:
            await wait.edit_text(f"📄 **جزئیات فاکتور (ثبت دستی):**\n\n{local_order[0]}", parse_mode='Markdown')
            return ConversationHandler.END
    except: pass

    if MIXIN_API_KEY:
        try:
            api_url = f"{SITE_URL}/api/management/v1/orders/{order_no}/"
            res = requests.get(api_url, headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=12)
            
            if res.status_code == 200:
                data = res.json()
                
                # استخراج اطلاعات طبق مستندات تصویر قبلی شما
                fname = data.get('first_name', '')
                lname = data.get('last_name', '')
                customer_name = f"{fname} {lname}".strip() or "نامشخص"

                raw_status = data.get('status', 'pending')
                status_map = {
                    "pending": "⏳ در انتظار بررسی",
                    "paid": "✅ پرداخت شده",
                    "canceled": "❌ لغو شده",
                    "preparing": "📦 در حال آماده‌سازی",
                    "sent": "🚚 ارسال شده"
                }
                status = status_map.get(raw_status.lower(), raw_status)

                f_price = data.get('final_price')
                try:
                    total_price = "{:,} تومان".format(int(f_price)) if f_price is not None else "نامشخص"
                except: total_price = "نامشخص"

                addr = data.get('shipping_address') or "ثبت نشده"
                prov = data.get('shipping_province', '')
                city = data.get('shipping_city', '')
                full_address = f"{prov}، {city}، {addr}".strip('، ')

                # کد رهگیری پستی
                tracking_code = data.get('shipping_tracking_code')
                
                # ایجاد دکمه شیشه‌ای برای رهگیری پست
                keyboard = []
                if tracking_code and tracking_code != "null":
                    post_url = f"https://tracking.post.ir/?id={tracking_code}"
                    keyboard.append([InlineKeyboardButton("🔎 رهگیری مستقیم از سامانه پست", url=post_url)])
                
                reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

                c_date = data.get('creation_date', 'نامشخص')
                display_date = str(c_date).split('T')[0] if 'T' in str(c_date) else str(c_date)

                items_text = ""
                items = data.get('items', [])
                for idx, item in enumerate(items, 1):
                    p_name = item.get('product_title') or item.get('name') or "محصول"
                    qty = item.get('quantity') or 1
                    items_text += f"{idx}. {p_name} (تعداد: {qty})\n"

                msg = (
                    f"📦 **اطلاعات کامل سفارش {order_no}**\n\n"
                    f"👤 **تحویل گیرنده:** {customer_name}\n"
                    f"🚩 **وضعیت فعلی:** {status}\n"
                    f"💰 **مبلغ کل سفارش:** {total_price}\n"
                    f"📍 **آدرس ارسال:** {full_address}\n"
                    f"🆔 **کد رهگیری پستی:** `{tracking_code if tracking_code else 'هنوز صادر نشده'}`\n\n"
                    f"📝 **لیست اقلام سفارش:**\n{items_text if items_text else 'جزئیات کالا یافت نشد'}\n"
                    f"📅 **تاریخ ثبت:** {display_date}\n\n"
                    f"💡 برای پیگیری دقیق‌تر با پشتیبانی در ارتباط باشید."
                )
                
                await wait.edit_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
                return ConversationHandler.END
        except Exception as e: print(f"API Error: {e}")

    await wait.edit_text(f"❌ سفارش #{order_no} یافت نشد.")
    return ConversationHandler.END

# --- سایر بخش‌ها (بدون هیچ تغییری) ---

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 نام محصول مورد نظر را وارد کنید:")
    return SEARCH_QUERY

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if query in ["جستجوی محصول 🔍", "پیگیری سفارش 📦", "ورود به پنل مدیریت ⚙️"]: return ConversationHandler.END
    wait = await update.message.reply_text(f"⏳ در حال جستجو برای «{query}»...")
    try:
        search_url = f"{SITE_URL}/search?q={query}"
        res = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        kb, seen = [], set()
        for link in soup.find_all('a', href=True):
            url = link['href']
            if url.startswith('/'): url = SITE_URL + url
            title = link.get_text().strip()
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    main_kb = [["جستجوی محصول 🔍", "پیگیری سفارش 📦"]]
    if str(user_id) == admin_id: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone(); cur.close(); conn.close()
    if user or str(user_id) == admin_id:
        await update.message.reply_text("خوش آمدید!", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
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
    await update.message.reply_text("✅ ثبت‌نام موفق!", reply_markup=ReplyKeyboardMarkup([["جستجوی محصول 🔍", "پیگیری سفارش 📦"]], resize_keyboard=True))
    return ConversationHandler.END

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    kb = [["آمار ربات 📊", "ارسال پیام همگانی 📢"], ["خروج از پنل 🔙"]]
    await update.message.reply_text("🛠 پنل مدیریت:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADMIN_PANEL

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM users")
    await update.message.reply_text(f"👥 تعداد کاربران: {cur.fetchone()[0]}")
    cur.close(); conn.close()

async def pre_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام را بفرستید:"); return BROADCAST

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor(); cur.execute("SELECT user_id FROM users")
    for u in cur.fetchall():
        try: await context.bot.copy_message(u[0], update.message.chat_id, update.message.message_id)
        except: pass
    cur.close(); conn.close()
    await update.message.reply_text("✅ ارسال شد."); return ADMIN_PANEL

async def post_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    url = update.message.text.strip()
    
    # ۱. استخراج ID محصول از لینک (مثلاً از لینک /product/108/ عدد 108 را برمی‌دارد)
    product_id_match = re.search(r'/product/(\d+)/', url)
    if not product_id_match:
        await update.message.reply_text("❌ لینک نامعتبر است. لطفاً لینک مستقیم محصول را بفرستید.")
        return

    product_id = product_id_match.group(1)
    wait = await update.message.reply_text(f"⏳ در حال استخراج اطلاعات محصول {product_id} از میکسین...")

    try:
        # ۲. فراخوانی API اطلاعات محصول طبق مستندات تصویر دوم
        api_url = f"{SITE_URL}/api/management/v1/products/{product_id}/"
        res = requests.get(api_url, headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=15)
        
        if res.status_code == 200:
            data = res.json()
            
            # استخراج فیلدها طبق تصویر مستندات
            name = data.get('name', 'محصول جدید')
            price = data.get('price', 0)
            is_available = data.get('available', False)
            stock = data.get('stock', 0)
            # تمیز کردن تگ‌های HTML از توضیحات
            description = data.get('description', '')
            clean_desc = re.sub('<[^<]+?>', '', description)[:150] + "..." 
            
            # وضعیت موجودی
            status_text = f"✅ موجود در انبار ({stock} عدد)" if is_available else "❌ فعلاً ناموجود"
            
            # مبلغ فرمت شده
            formatted_price = "{:,} تومان".format(int(price)) if price else "تماس بگیرید"

            # ۳. دریافت عکس محصول (از متاتگ صفحه برای کیفیت بهتر)
            page_res = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(page_res.text, 'html.parser')
            img_tag = soup.find("meta", attrs={"property": "og:image"})
            img_url = img_tag["content"] if img_tag else None

            # ۴. ساخت متن پست
            caption = (
                f"🛍 **{name}**\n\n"
                f"💰 **قیمت:** {formatted_price}\n"
                f"📦 **وضعیت:** {status_text}\n\n"
                f"📝 **مشخصات فنی:**\n{clean_desc}\n\n"
                f"🚚 ارسال سریع | 💎 ضمانت اصالت | 💳 پرداخت امن\n\n"
                f"✨ #بانه_استور #خرید #لوازم_خانگی\n"
            )

            # ۵. دکمه‌های شیشه‌ای
            keyboard = [
                [InlineKeyboardButton("🛒 مشاهده و خرید از سایت", url=url)],
                [InlineKeyboardButton("👨‍💻 مشاوره و فروش (تلگرام)", url="https://t.me/+989180514202")]
            ]
            
            if img_url:
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=img_url,
                    caption=caption,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            await wait.edit_text("✅ محصول با اطلاعات دقیق API در کانال منتشر شد.")
        else:
            await wait.edit_text("❌ خطا در دریافت اطلاعات از API سایت.")
            
    except Exception as e:
        await wait.edit_text(f"❌ خطا: {str(e)}")

async def process_pasted_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    text = update.message.text
    try:
        order_id = re.search(r'شماره\s*:\s*(\d+)', text).group(1)
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO orders (order_id, items) VALUES (%s, %s) ON CONFLICT (order_id) DO UPDATE SET items=EXCLUDED.items", (order_id, text))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text(f"✅ فاکتور {order_id} ذخیره شد.")
    except: pass

if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
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
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'جزییات سفارش شماره'), process_pasted_invoice))
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^https://banehstoore\.ir'), post_product))
        app.run_polling()