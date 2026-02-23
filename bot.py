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
    ApplicationBuilder, CommandHandler, MessageHandler, filters, 
    ConversationHandler, ContextTypes, CallbackQueryHandler
)
from telegram.error import BadRequest

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
SUPPORT_PHONE = "09180514202"
SUPPORT_MAP = "https://maps.app.goo.gl/eWv6njTbL8ivfbYa6"
MIXIN_API_KEY = os.getenv('MIXIN_API_KEY')

# --- توابع کمکی عضویت اجباری ---
async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception: return True 

async def send_join_request(update: Update):
    keyboard = [
        [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_ID.replace('@','')}")],
        [InlineKeyboardButton("✅ عضو شدم (تایید)", callback_data="check_join")]
    ]
    msg = "⚠️ برای استفاده از امکانات ربات، ابتدا باید در کانال ما عضو شوید 👇"
    if update.message:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

# --- بخش پشتیبانی و مشاوره ---
async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # چک کردن عضویت قبل از نمایش پشتیبانی
    if not await is_subscribed(context, update.effective_user.id):
        await send_join_request(update); return

    kb = [
        [InlineKeyboardButton("📍 مشاهده آدرس روی نقشه", url=SUPPORT_MAP)],
        [InlineKeyboardButton("📞 تماس مستقیم", url=f"tel:{SUPPORT_PHONE}"), 
         InlineKeyboardButton("💬 واتساپ", url=f"https://wa.me/{SUPPORT_PHONE.replace('0','+98',1)}")],
        [InlineKeyboardButton("📢 کانال تلگرام ما", url=f"https://t.me/{CHANNEL_ID.replace('@','')}")]
    ]
    await update.message.reply_text(
        "🎧 **بخش پشتیبانی و مشاوره بانه استور**\n\nجهت ارتباط با ما از دکمه‌های زیر استفاده کنید:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )

# --- ۴. پیگیری سفارش ---
async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(context, update.effective_user.id):
        await send_join_request(update); return ConversationHandler.END
    await update.message.reply_text("🔢 لطفاً شماره سفارش خود را وارد کنید:")
    return TRACK_ORDER

async def do_track_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_no = update.message.text.strip()
    wait = await update.message.reply_text("⏳ در حال استخراج...")
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT items FROM orders WHERE order_id = %s", (order_no,))
        local_order = cur.fetchone(); cur.close(); conn.close()
        if local_order:
            await wait.edit_text(f"📄 **جزئیات فاکتور:**\n\n{local_order[0]}", parse_mode='Markdown')
            return ConversationHandler.END
    except: pass

    if MIXIN_API_KEY:
        try:
            api_url = f"{SITE_URL}/api/management/v1/orders/{order_no}/"
            res = requests.get(api_url, headers={"Authorization": f"Api-Key {MIXIN_API_KEY}"}, timeout=12)
            if res.status_code == 200:
                data = res.json()
                customer_name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip() or "نامشخص"
                status = data.get('status', 'pending')
                f_price = data.get('final_price')
                total_price = "{:,} تومان".format(int(f_price)) if f_price else "نامشخص"
                full_address = f"{data.get('shipping_province', '')} {data.get('shipping_city', '')} {data.get('shipping_address', '')}"
                items_text = "".join([f"{i}. {item.get('product_title') or 'محصول'} (تعداد: {item.get('quantity', 1)})\n" for i, item in enumerate(data.get('items', []), 1)])
                msg = (f"📦 **سفارش {order_no}**\n👤 مشتری: {customer_name}\n🚩 وضعیت: {status}\n💰 مبلغ: {total_price}\n📍 آدرس: {full_address}\n\n📝 اقلام:\n{items_text}")
                await wait.edit_text(msg, parse_mode='Markdown')
                return ConversationHandler.END
        except: pass
    await wait.edit_text(f"❌ سفارش #{order_no} یافت نشد.")
    return ConversationHandler.END

# --- ۵. جستجو ---
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(context, update.effective_user.id):
        await send_join_request(update); return ConversationHandler.END
    await update.message.reply_text("🔍 نام محصول را وارد کنید:")
    return SEARCH_QUERY

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if query in ["جستجوی محصول 🔍", "پیگیری سفارش 📦", "ورود به پنل مدیریت ⚙️", "🗂 دسته‌بندی محصولات", "💰 استعلام قیمت لحظه‌ای", "📞 پشتیبانی و مشاوره"]: return ConversationHandler.END
    wait = await update.message.reply_text(f"⏳ جستجو برای «{query}»...")
    try:
        res = requests.get(f"{SITE_URL}/search?q={query}", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        kb = []
        for link in soup.find_all('a', href=True):
            url = link['href'] if link['href'].startswith('http') else SITE_URL + link['href']
            title = link.get_text().strip()
            if "/product/" in url and len(title) > 8:
                kb.append([InlineKeyboardButton(f"📦 {title[:40]}...", url=url)])
            if len(kb) >= 10: break
        if kb:
            await wait.delete()
            await update.message.reply_text(f"✅ نتایج:", reply_markup=InlineKeyboardMarkup(kb))
        else: await wait.edit_text(f"❌ موردی یافت نشد.")
    except: await wait.edit_text("❌ خطا در اتصال.")
    return ConversationHandler.END 

# --- ۶. استعلام قیمت ---
async def ask_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(context, update.effective_user.id):
        await send_join_request(update); return ConversationHandler.END
    await update.message.reply_text("💰 نام محصول را بفرستید:", reply_markup=ReplyKeyboardMarkup([["انصراف 🔙"]], resize_keyboard=True))
    return ASK_PRICE

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "انصراف 🔙": return await start(update, context)
    admin_id = os.getenv('ADMIN_ID')
    msg = f"📩 **استعلام قیمت**\n👤 مشتری: {update.effective_user.full_name}\n🆔 کد: `ID:{update.effective_user.id}`\n\n📝 درخواست:\n{update.message.text}"
    await context.bot.send_message(chat_id=admin_id, text=msg, parse_mode='Markdown')
    await update.message.reply_text("✅ ارسال شد.")
    return ConversationHandler.END

# --- ۷. مدیریت و استارت ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv('ADMIN_ID')
    
    main_kb = [
        ["جستجوی محصول 🔍", "پیگیری سفارش 📦"],
        ["🗂 دسته‌بندی محصولات", "💰 استعلام قیمت لحظه‌ای"],
        ["📞 پشتیبانی و مشاوره"]
    ]
    if str(user_id) == admin_id: main_kb.insert(0, ["ورود به پنل مدیریت ⚙️"])
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
    user_row = cur.fetchone(); cur.close(); conn.close()
    
    if user_row or str(user_id) == admin_id:
        if not await is_subscribed(context, user_id):
            await send_join_request(update); return ConversationHandler.END
        name = user_row[0] if user_row else "مدیر"
        await update.message.reply_text(f"سلام {name} عزیز، خوش آمدید:", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
        return ConversationHandler.END
    await update.message.reply_text("سلام! نام و نام خانوادگی خود را وارد کنید:")
    return NAME

async def handle_callback_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if await is_subscribed(context, query.from_user.id):
        await query.message.delete()
        await start(update, context)
    else: await context.bot.send_message(chat_id=query.from_user.id, text="❌ هنوز عضو نشده‌اید.")

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
    if not await is_subscribed(context, user_id): await send_join_request(update)
    else: await start(update, context)
    return ConversationHandler.END

# سایر هندلرهای ادمین
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv('ADMIN_ID'): return
    kb = [["آمار ربات 📊", "ارسال پیام همگانی 📢"], ["خروج از پنل 🔙"]]
    await update.message.reply_text("🛠 پنل مدیریت:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADMIN_PANEL

# --- ۸. اجرای اصلی ---
if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # هندلرهای ثابت (بالاترین اولویت)
        app.add_handler(CallbackQueryHandler(handle_callback_check, pattern="check_join"))
        app.add_handler(MessageHandler(filters.Regex("^📞 پشتیبانی و مشاوره$"), show_support))
        
        # گفتگوهای چندمرحله‌ای
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
            entry_points=[CommandHandler('start', start)],
            states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)], PHONE: [MessageHandler(filters.CONTACT, get_phone)]},
            fallbacks=[CommandHandler('start', start)], allow_reentry=True
        ))
        
        # اجرای پولینگ
        app.run_polling()