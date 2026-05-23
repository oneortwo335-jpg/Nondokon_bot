import os
import asyncio
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",")]
DAILY_LIMIT = 1500

CLIENT_TYPES = {"bozor": "🛒 Bozor", "dokon": "🏪 Do'kon", "cafe": "☕ Cafe", "restoran": "🍽️ Restoran"}

orders = {}
order_counter = 0
daily_used = 0
last_reset_date = date.today()
all_clients = []

CHOOSE_TYPE, ENTER_NAME, ENTER_QTY, ENTER_PHONE, ENTER_ADDRESS, CONFIRM = range(6)

def reset_daily():
    global daily_used, last_reset_date
    today = date.today()
    if today > last_reset_date:
        daily_used = 0
        last_reset_date = today

def get_remaining():
    reset_daily()
    return DAILY_LIMIT - daily_used

def next_id():
    global order_counter
    order_counter += 1
    return order_counter

def main_menu(is_admin=False):
    buttons = [["📦 Zakaz berish"], ["📊 Mavjud mahsulot", "📋 Mening zakazlarim"]]
    if is_admin:
        buttons.append(["⚙️ Admin panel"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def admin_menu():
    buttons = [["📋 Barcha zakazlar", "📊 Statistika"], ["📢 Xabar yuborish"], ["🏠 Asosiy menyu"]]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def type_keyboard():
    buttons = [[InlineKeyboardButton(v, callback_data=f"type_{k}")] for k, v in CLIENT_TYPES.items()]
    return InlineKeyboardMarkup(buttons)

def action_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_{order_id}"),
         InlineKeyboardButton("🚚 Yetkazilmoqda", callback_data=f"delivering_{order_id}")],
        [InlineKeyboardButton("✔️ Yetkazildi", callback_data=f"delivered_{order_id}"),
         InlineKeyboardButton("❌ Bekor", callback_data=f"cancel_{order_id}")]
    ])

def order_text(order):
    status_icons = {"kutilmoqda": "⏳", "tasdiqlandi": "✅", "yetkazilmoqda": "🚚", "yetkazildi": "✔️", "bekor_qilindi": "❌"}
    icon = status_icons.get(order["status"], "📦")
    return (f"📦 *Zakaz #{order['id']}*\n"
            f"👤 {order['client_name']}\n"
            f"🏷️ {CLIENT_TYPES.get(order['client_type'], '')}\n"
            f"📊 Miqdor: *{order['quantity']} ta*\n"
            f"📞 {order['phone']}\n"
            f"📍 {order['address']}\n"
            f"🕐 {order['created_at']}\n"
            f"📌 {icon} {order['status']}\n"
            f"⬜ Qolgan: *{get_remaining()} ta*")

async def notify_clients(app, except_id, qty):
    remaining = get_remaining()
    if remaining <= 0:
        msg = "⚠️ *DIQQAT!* Bugungi mahsulot *tugadi* ❌\nErtaga qaytib keling!"
    elif remaining <= 100:
        msg = f"🔴 *OXIRGI {remaining} TA MAHSULOT!*\nYangi zakaz: {qty} ta\nTez buyurtma bering!"
    elif remaining <= 300:
        msg = f"🟡 *Mahsulot kamayyapti!*\nYangi zakaz: {qty} ta\nQolgan: *{remaining} ta*"
    else:
        msg = f"🟢 Yangi zakaz qabul qilindi: {qty} ta\nQolgan: *{remaining} ta*"

    for uid in all_clients:
        if uid == except_id:
            continue
        try:
            await app.bot.send_message(uid, msg, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except Exception:
            pass

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in all_clients:
        all_clients.append(uid)
    is_admin = uid in ADMIN_IDS
    await update.message.reply_text(
        f"👋 Salom *{update.effective_user.first_name}*!\n\n"
        f"🏭 Ishlab chiqarish sexi botiga xush kelibsiz!\n"
        f"📦 Bugun *{get_remaining()} ta* mahsulot mavjud.",
        parse_mode="Markdown", reply_markup=main_menu(is_admin))

async def check_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    r = get_remaining()
    status = "🟢 Yetarli" if r > 300 else ("🟡 Kam qoldi" if r > 100 else ("🔴 Kritik kam" if r > 0 else "❌ Tugagan"))
    await update.message.reply_text(
        f"📊 *Bugungi holat*\n📦 Limit: {DAILY_LIMIT}\n✅ Sotilgan: {daily_used}\n⬜ Qolgan: *{r}*\n{status}",
        parse_mode="Markdown")

async def my_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_orders = [o for o in orders.values() if o["user_id"] == uid]
    if not user_orders:
        await update.message.reply_text("📭 Sizda zakazlar yo'q.")
        return
    text = "📋 *Sizning zakazlaringiz:*\n\n"
    for o in sorted(user_orders, key=lambda x: x["id"], reverse=True)[:5]:
        icons = {"kutilmoqda": "⏳", "tasdiqlandi": "✅", "yetkazilmoqda": "🚚", "yetkazildi": "✔️", "bekor_qilindi": "❌"}
        text += f"#{o['id']} — {o['quantity']} ta {icons.get(o['status'], '')} {o['status']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def start_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if get_remaining() <= 0:
        await update.message.reply_text("❌ Bugungi limit tugadi! Ertaga keling.")
        return ConversationHandler.END
    await update.message.reply_text(
        f"📦 *Yangi zakaz*\nMavjud: *{get_remaining()} ta*\n\nMuassasa turini tanlang:",
        parse_mode="Markdown", reply_markup=type_keyboard())
    return CHOOSE_TYPE

async def choose_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctype = query.data.replace("type_", "")
    ctx.user_data["client_type"] = ctype
    await query.edit_message_text(f"✅ {CLIENT_TYPES[ctype]}\n\n📝 Muassasa nomini kiriting:")
    return ENTER_NAME

async def enter_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["client_name"] = update.message.text
    await update.message.reply_text(f"📊 Nechta kerak? (max: *{get_remaining()} ta*)", parse_mode="Markdown")
    return ENTER_QTY

async def enter_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("❌ Faqat raqam kiriting!")
        return ENTER_QTY
    qty = int(update.message.text)
    if qty <= 0 or qty > get_remaining():
        await update.message.reply_text(f"❌ 1 dan {get_remaining()} gacha kiriting!")
        return ENTER_QTY
    ctx.user_data["quantity"] = qty
    await update.message.reply_text("📞 Telefon raqamingiz:")
    return ENTER_PHONE

async def enter_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["phone"] = update.message.text
    await update.message.reply_text("📍 Yetkazish manzili:")
    return ENTER_ADDRESS

async def enter_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["address"] = update.message.text
    d = ctx.user_data
    text = (f"📋 *Zakazni tasdiqlang:*\n\n"
            f"🏷️ {CLIENT_TYPES.get(d['client_type'])}\n"
            f"👤 {d['client_name']}\n"
            f"📊 {d['quantity']} ta\n"
            f"📞 {d['phone']}\n"
            f"📍 {d['address']}\n\nTasdiqlaysizmi?")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha", callback_data="yes_order"),
        InlineKeyboardButton("❌ Yo'q", callback_data="no_order")
    ]])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    return CONFIRM

async def confirm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global daily_used
    query = update.callback_query
    await query.answer()
    if query.data == "no_order":
        await query.edit_message_text("❌ Bekor qilindi.")
        return ConversationHandler.END

    d = ctx.user_data
    uid = update.effective_user.id
    if d["quantity"] > get_remaining():
        await query.edit_message_text("❌ Yetarli mahsulot qolmadi!")
        return ConversationHandler.END

    oid = next_id()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    order = {"id": oid, "user_id": uid, "client_type": d["client_type"],
             "client_name": d["client_name"], "quantity": d["quantity"],
             "phone": d["phone"], "address": d["address"],
             "status": "kutilmoqda", "created_at": now}
    orders[oid] = order
    daily_used += d["quantity"]

    await query.edit_message_text(
        f"🎉 *Zakaz #{oid} qabul qilindi!*\n📊 {d['quantity']} ta\n⏳ Kutilmoqda",
        parse_mode="Markdown")

    for admin_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(admin_id, f"🔔 *YANGI ZAKAZ!*\n\n" + order_text(order),
                                       parse_mode="Markdown", reply_markup=action_keyboard(oid))
        except Exception:
            pass

    asyncio.create_task(notify_clients(ctx.application, uid, d["quantity"]))
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=main_menu(update.effective_user.id in ADMIN_IDS))
    return ConversationHandler.END

async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    active = len([o for o in orders.values() if o["status"] in ["kutilmoqda", "tasdiqlandi", "yetkazilmoqda"]])
    await update.message.reply_text(
        f"⚙️ *Admin Panel*\n📦 Qolgan: *{get_remaining()} ta*\n📋 Faol zakazlar: *{active}*\n👥 Mijozlar: *{len(all_clients)}*",
        parse_mode="Markdown", reply_markup=admin_menu())

async def all_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    active = [o for o in orders.values() if o["status"] in ["kutilmoqda", "tasdiqlandi", "yetkazilmoqda"]]
    if not active:
        await update.message.reply_text("📭 Faol zakazlar yo'q.")
        return
    for o in active[-5:]:
        await update.message.reply_text(order_text(o), parse_mode="Markdown", reply_markup=action_keyboard(o["id"]))

async def statistics(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    by_status = {}
    total_qty = 0
    for o in orders.values():
        by_status[o["status"]] = by_status.get(o["status"], 0) + 1
        total_qty += o["quantity"]
    text = f"📊 *Statistika*\nJami zakazlar: *{len(orders)}*\nJami mahsulot: *{total_qty}*\nQolgan: *{get_remaining()}*\n\n"
    icons = {"kutilmoqda": "⏳", "tasdiqlandi": "✅", "yetkazilmoqda": "🚚", "yetkazildi": "✔️", "bekor_qilindi": "❌"}
    for s, c in by_status.items():
        text += f"{icons.get(s, '')} {s}: *{c}*\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS:
        return
    parts = query.data.split("_")
    action, oid = parts[0], int(parts[1])
    if oid not in orders:
        return
    order = orders[oid]
    status_map = {"confirm": "tasdiqlandi", "delivering": "yetkazilmoqda", "delivered": "yetkazildi", "cancel": "bekor_qilindi"}
    if action not in status_map:
        return
    global daily_used
    if action == "cancel" and order["status"] not in ["yetkazildi", "bekor_qilindi"]:
        daily_used = max(0, daily_used - order["quantity"])
    order["status"] = status_map[action]
    icons = {"tasdiqlandi": "✅", "yetkazilmoqda": "🚚", "yetkazildi": "✔️", "bekor_qilindi": "❌"}
    show_actions = order["status"] not in ["yetkazildi", "bekor_qilindi"]
    await query.edit_message_text(order_text(order), parse_mode="Markdown",
                                  reply_markup=action_keyboard(oid) if show_actions else None)
    try:
        await ctx.bot.send_message(order["user_id"],
            f"{icons.get(order['status'], '')} *Zakaz #{oid}* yangilandi!\nStatus: *{order['status']}*",
            parse_mode="Markdown")
    except Exception:
        pass

async def back_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    is_admin = update.effective_user.id in ADMIN_IDS
    await update.message.reply_text("🏠 Asosiy menyu", reply_markup=main_menu(is_admin))

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Text(["📦 Zakaz berish"]), start_order)],
        states={
            CHOOSE_TYPE: [CallbackQueryHandler(choose_type, pattern="^type_")],
            ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name)],
            ENTER_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_qty)],
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone)],
            ENTER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_address)],
            CONFIRM: [CallbackQueryHandler(confirm_order, pattern="^(yes|no)_order$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Text(["📊 Mavjud mahsulot"]), check_stock))
    app.add_handler(MessageHandler(filters.Text(["📋 Mening zakazlarim"]), my_orders))
    app.add_handler(MessageHandler(filters.Text(["⚙️ Admin panel"]), admin_panel))
    app.add_handler(MessageHandler(filters.Text(["📋 Barcha zakazlar"]), all_orders))
    app.add_handler(MessageHandler(filters.Text(["📊 Statistika"]), statistics))
    app.add_handler(MessageHandler(filters.Text(["🏠 Asosiy menyu"]), back_main))
    app.add_handler(CallbackQueryHandler(handle_action, pattern="^(confirm|delivering|delivered|cancel)_"))

    logger.info("Bot ishga tushdi!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
