#!/usr/bin/env python3
"""
Ishlab chiqarish sexi - Zakaz boshqaruv Telegram boti
Kunlik limit: 1500 ta mahsulot
"""

import asyncio
import logging
from datetime import datetime, date
from typing import Dict, List
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ==================== SOZLAMALAR ====================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # @BotFather dan olingan token
ADMIN_IDS = [123456789]            # Admin Telegram ID lari (ro'yxat)
DAILY_LIMIT = 1500                 # Kunlik mahsulot limiti

# Mijoz turlari
CLIENT_TYPES = {
    "bozor": "🛒 Bozor",
    "dokon": "🏪 Do'kon",
    "cafe": "☕ Cafe",
    "restoran": "🍽️ Restoran"
}

# ==================== MA'LUMOTLAR (xotira) ====================
# Haqiqiy loyihada PostgreSQL yoki SQLite ishlatish tavsiya etiladi

orders: Dict[int, dict] = {}        # {order_id: order_data}
order_counter = 0
daily_used = 0                       # Bugun sarflangan mahsulot soni
last_reset_date = date.today()       # Oxirgi reset sanasi
all_clients: List[int] = []          # Barcha ro'yxatdan o'tgan foydalanuvchilar

# ==================== HOLATLAR ====================
class OrderStates(StatesGroup):
    choosing_type = State()
    entering_name = State()
    entering_quantity = State()
    entering_phone = State()
    entering_address = State()
    confirming = State()

class AdminStates(StatesGroup):
    broadcasting = State()

# ==================== BOT VA DISPATCHER ====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== YORDAMCHI FUNKSIYALAR ====================

def reset_daily_if_needed():
    """Har yangi kunda limitni sıfırlash"""
    global daily_used, last_reset_date
    today = date.today()
    if today > last_reset_date:
        daily_used = 0
        last_reset_date = today
        logger.info(f"Kunlik limit yangilandi: {today}")

def get_remaining():
    """Qolgan mahsulot sonini qaytarish"""
    reset_daily_if_needed()
    return DAILY_LIMIT - daily_used

def next_order_id():
    global order_counter
    order_counter += 1
    return order_counter

def format_order_summary(order: dict) -> str:
    """Zakaz ma'lumotlarini chiroyli formatda ko'rsatish"""
    status_emoji = {
        "kutilmoqda": "⏳",
        "tasdiqlandi": "✅",
        "yetkazilmoqda": "🚚",
        "yetkazildi": "✔️",
        "bekor_qilindi": "❌"
    }
    emoji = status_emoji.get(order.get('status', 'kutilmoqda'), "📋")
    
    return (
        f"📦 *Zakaz #{order['id']}*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Mijoz: {order['client_name']}\n"
        f"🏷️ Tur: {CLIENT_TYPES.get(order['client_type'], order['client_type'])}\n"
        f"📊 Miqdor: *{order['quantity']} ta*\n"
        f"📞 Telefon: {order['phone']}\n"
        f"📍 Manzil: {order['address']}\n"
        f"🕐 Vaqt: {order['created_at']}\n"
        f"📌 Status: {emoji} {order['status'].capitalize()}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Qolgan mahsulot: *{get_remaining()} ta*"
    )

async def notify_all_clients_about_stock(except_user_id: int = None, new_order_qty: int = 0):
    """Barcha mijozlarga qoldiq haqida xabar yuborish"""
    remaining = get_remaining()
    
    # Bildirishnoma matni
    if remaining <= 0:
        msg = (
            "⚠️ *DIQQAT!*\n\n"
            "Bugungi mahsulot limiti *tugadi* ❌\n"
            f"Ertaga yana {DAILY_LIMIT} ta mahsulot bo'ladi.\n\n"
            "Ertangi kun uchun *oldindan buyurtma* bering! 📋"
        )
    elif remaining <= 100:
        msg = (
            f"🔴 *OXIRGI {remaining} TA MAHSULOT QOLDI!*\n\n"
            f"Yangi zakaz: *{new_order_qty} ta* buyurtma qabul qilindi.\n"
            f"Omborda faqat *{remaining} ta* mahsulot qoldi.\n\n"
            "⚡ Tez buyurtma bering!"
        )
    elif remaining <= 300:
        msg = (
            f"🟡 *Mahsulot kamayyapti!*\n\n"
            f"Yangi zakaz qabul qilindi: *{new_order_qty} ta*\n"
            f"Omborda *{remaining} ta* mahsulot qoldi.\n\n"
            "Bugun buyurtma berish tavsiya etiladi ✅"
        )
    else:
        msg = (
            f"🟢 *Zakaz qabul qilindi*\n\n"
            f"Yangi buyurtma: *{new_order_qty} ta*\n"
            f"Omborda *{remaining} ta* mahsulot mavjud."
        )
    
    # Barcha mijozlarga yuborish
    sent_count = 0
    for user_id in all_clients:
        if user_id == except_user_id:
            continue
        try:
            await bot.send_message(user_id, msg, parse_mode="Markdown")
            sent_count += 1
            await asyncio.sleep(0.05)  # Flood limitdan himoya
        except Exception as e:
            logger.warning(f"Xabar yuborilmadi {user_id}: {e}")
    
    logger.info(f"Bildirishnoma {sent_count} ta foydalanuvchiga yuborildi")

# ==================== ASOSIY MENYULAR ====================

def main_menu_keyboard(is_admin=False):
    buttons = [
        [KeyboardButton(text="📦 Zakaz berish")],
        [KeyboardButton(text="📊 Mavjud mahsulot"), KeyboardButton(text="📋 Mening zakazlarim")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="⚙️ Admin panel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def admin_keyboard():
    buttons = [
        [KeyboardButton(text="📋 Barcha zakazlar"), KeyboardButton(text="📊 Statistika")],
        [KeyboardButton(text="📢 Xabar yuborish"), KeyboardButton(text="🔄 Limit yangilash")],
        [KeyboardButton(text="🏠 Asosiy menyu")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def client_type_keyboard():
    builder = InlineKeyboardBuilder()
    for key, name in CLIENT_TYPES.items():
        builder.button(text=name, callback_data=f"type_{key}")
    builder.adjust(2)
    return builder.as_markup()

def order_action_keyboard(order_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Tasdiqlash", callback_data=f"confirm_{order_id}")
    builder.button(text="🚚 Yetkazilmoqda", callback_data=f"delivering_{order_id}")
    builder.button(text="✔️ Yetkazildi", callback_data=f"delivered_{order_id}")
    builder.button(text="❌ Bekor qilish", callback_data=f"cancel_{order_id}")
    builder.adjust(2)
    return builder.as_markup()

# ==================== HANDLERLAR ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id not in all_clients:
        all_clients.append(user_id)
    
    is_admin = user_id in ADMIN_IDS
    remaining = get_remaining()
    
    welcome_text = (
        f"👋 Salom, *{message.from_user.full_name}*!\n\n"
        f"🏭 *Ishlab chiqarish sexi* botiga xush kelibsiz!\n\n"
        f"📦 Bugun *{remaining} ta* mahsulot mavjud.\n\n"
        f"Buyurtma berish uchun *📦 Zakaz berish* tugmasini bosing."
    )
    if is_admin:
        welcome_text += "\n\n🔑 *Admin huquqlari faol*"
    
    await message.answer(welcome_text, parse_mode="Markdown",
                         reply_markup=main_menu_keyboard(is_admin))

@dp.message(F.text == "📊 Mavjud mahsulot")
async def check_stock(message: types.Message):
    remaining = get_remaining()
    total_orders = len([o for o in orders.values() 
                       if o['created_at'].startswith(str(date.today()))])
    
    if remaining <= 0:
        status = "🔴 *TUGAGAN*"
    elif remaining <= 100:
        status = "🟠 *Kritik kam*"
    elif remaining <= 300:
        status = "🟡 *Kam qoldi*"
    else:
        status = "🟢 *Yetarli*"
    
    text = (
        f"📊 *Bugungi holat*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Sana: {date.today().strftime('%d.%m.%Y')}\n"
        f"📦 Kunlik limit: *{DAILY_LIMIT} ta*\n"
        f"✅ Sotilgan: *{daily_used} ta*\n"
        f"⬜ Qolgan: *{remaining} ta*\n"
        f"📋 Bugungi zakazlar: *{total_orders} ta*\n"
        f"📈 Status: {status}\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📋 Mening zakazlarim")
async def my_orders(message: types.Message):
    user_id = message.from_user.id
    user_orders = [o for o in orders.values() if o['user_id'] == user_id]
    
    if not user_orders:
        await message.answer("📭 Sizda hozircha zakazlar yo'q.\n\n"
                             "Zakaz berish uchun *📦 Zakaz berish* tugmasini bosing.",
                             parse_mode="Markdown")
        return
    
    # Oxirgi 5 ta zakaz
    recent = sorted(user_orders, key=lambda x: x['id'], reverse=True)[:5]
    text = f"📋 *Sizning zakazlaringiz* (oxirgi {len(recent)} ta):\n\n"
    
    for order in recent:
        status_emoji = {"kutilmoqda": "⏳", "tasdiqlandi": "✅", 
                       "yetkazilmoqda": "🚚", "yetkazildi": "✔️", 
                       "bekor_qilindi": "❌"}.get(order['status'], "📦")
        text += (f"#{order['id']} — {order['quantity']} ta "
                f"{status_emoji} {order['status']}\n"
                f"📅 {order['created_at']}\n\n")
    
    await message.answer(text, parse_mode="Markdown")

# ==================== ZAKAZ BERISH JARAYONI ====================

@dp.message(F.text == "📦 Zakaz berish")
async def start_order(message: types.Message, state: FSMContext):
    remaining = get_remaining()
    
    if remaining <= 0:
        await message.answer(
            "❌ *Kechirasiz!*\n\n"
            "Bugungi mahsulot limiti tugadi.\n"
            "Ertaga yana buyurtma bera olasiz! 🌅",
            parse_mode="Markdown"
        )
        return
    
    await message.answer(
        f"📦 *Yangi zakaz*\n\n"
        f"Mavjud mahsulot: *{remaining} ta*\n\n"
        f"Muassasa turini tanlang:",
        parse_mode="Markdown",
        reply_markup=client_type_keyboard()
    )
    await state.set_state(OrderStates.choosing_type)

@dp.callback_query(F.data.startswith("type_"), StateFilter(OrderStates.choosing_type))
async def choose_type(callback: types.CallbackQuery, state: FSMContext):
    client_type = callback.data.replace("type_", "")
    await state.update_data(client_type=client_type)
    
    await callback.message.edit_text(
        f"✅ Tur: *{CLIENT_TYPES[client_type]}*\n\n"
        f"📝 Muassasa nomini kiriting:",
        parse_mode="Markdown"
    )
    await state.set_state(OrderStates.entering_name)
    await callback.answer()

@dp.message(StateFilter(OrderStates.entering_name))
async def enter_name(message: types.Message, state: FSMContext):
    await state.update_data(client_name=message.text)
    remaining = get_remaining()
    
    await message.answer(
        f"✅ Nom: *{message.text}*\n\n"
        f"📊 Nechta mahsulot kerak? (max: *{remaining} ta*)\n"
        f"Faqat raqam kiriting:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(OrderStates.entering_quantity)

@dp.message(StateFilter(OrderStates.entering_quantity))
async def enter_quantity(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Iltimos, faqat *raqam* kiriting!", parse_mode="Markdown")
        return
    
    qty = int(message.text)
    remaining = get_remaining()
    
    if qty <= 0:
        await message.answer("❌ Miqdor 0 dan katta bo'lishi kerak!")
        return
    
    if qty > remaining:
        await message.answer(
            f"❌ *Yetarli mahsulot yo'q!*\n\n"
            f"Siz: *{qty} ta*\n"
            f"Mavjud: *{remaining} ta*\n\n"
            f"Iltimos, kamroq miqdor kiriting:",
            parse_mode="Markdown"
        )
        return
    
    await state.update_data(quantity=qty)
    await message.answer(
        f"✅ Miqdor: *{qty} ta*\n\n"
        f"📞 Telefon raqamingizni kiriting:\n(+998901234567 ko'rinishida)",
        parse_mode="Markdown"
    )
    await state.set_state(OrderStates.entering_phone)

@dp.message(StateFilter(OrderStates.entering_phone))
async def enter_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if len(phone) < 9:
        await message.answer("❌ To'g'ri telefon raqam kiriting!")
        return
    
    await state.update_data(phone=phone)
    await message.answer(
        f"✅ Telefon: *{phone}*\n\n"
        f"📍 Yetkazish manzilini kiriting:",
        parse_mode="Markdown"
    )
    await state.set_state(OrderStates.entering_address)

@dp.message(StateFilter(OrderStates.entering_address))
async def enter_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    data = await state.get_data()
    
    confirm_text = (
        f"📋 *Zakazni tasdiqlang:*\n\n"
        f"🏷️ Tur: {CLIENT_TYPES.get(data['client_type'])}\n"
        f"👤 Nom: {data['client_name']}\n"
        f"📊 Miqdor: *{data['quantity']} ta*\n"
        f"📞 Telefon: {data['phone']}\n"
        f"📍 Manzil: {data['address']}\n\n"
        f"✅ Tasdiqlaysizmi?"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Ha, zakaz berish", callback_data="confirm_order")
    builder.button(text="❌ Bekor qilish", callback_data="cancel_order")
    builder.adjust(1)
    
    await message.answer(confirm_text, parse_mode="Markdown",
                         reply_markup=builder.as_markup())
    await state.set_state(OrderStates.confirming)

@dp.callback_query(F.data == "cancel_order", StateFilter(OrderStates.confirming))
async def cancel_order_creation(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS
    await callback.message.edit_text("❌ Zakaz bekor qilindi.")
    await callback.message.answer("🏠 Asosiy menyuga qaytdingiz.",
                                   reply_markup=main_menu_keyboard(is_admin))
    await callback.answer()

@dp.callback_query(F.data == "confirm_order", StateFilter(OrderStates.confirming))
async def confirm_new_order(callback: types.CallbackQuery, state: FSMContext):
    global daily_used
    data = await state.get_data()
    user_id = callback.from_user.id
    
    # Oxirgi tekshirish
    remaining = get_remaining()
    if data['quantity'] > remaining:
        await callback.message.edit_text(
            f"❌ Kechirasiz! Siz shakllantirgan paytda *{data['quantity']} ta* band bo'ldi.\n"
            f"Mavjud: *{remaining} ta*\n\nQaytadan urinib ko'ring.",
            parse_mode="Markdown"
        )
        await state.clear()
        await callback.answer()
        return
    
    # Zakaz yaratish
    order_id = next_order_id()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    
    order = {
        "id": order_id,
        "user_id": user_id,
        "client_type": data['client_type'],
        "client_name": data['client_name'],
        "quantity": data['quantity'],
        "phone": data['phone'],
        "address": data['address'],
        "status": "kutilmoqda",
        "created_at": now
    }
    
    orders[order_id] = order
    daily_used += data['quantity']
    
    await state.clear()
    
    # Mijozga tasdiqlash xabari
    success_text = (
        f"🎉 *Zakaz qabul qilindi!*\n\n"
        f"📦 Zakaz #*{order_id}*\n"
        f"📊 Miqdor: *{data['quantity']} ta*\n"
        f"🕐 Vaqt: {now}\n"
        f"📌 Status: ⏳ Kutilmoqda\n\n"
        f"✅ Tez orada bog'lanamiz!"
    )
    
    is_admin = user_id in ADMIN_IDS
    await callback.message.edit_text(success_text, parse_mode="Markdown")
    await callback.message.answer("🏠 Asosiy menyu",
                                   reply_markup=main_menu_keyboard(is_admin))
    
    # Adminlarga bildirishnoma
    admin_text = (
        f"🔔 *YANGI ZAKAZ!*\n\n"
        + format_order_summary(order)
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, parse_mode="Markdown",
                                  reply_markup=order_action_keyboard(order_id))
        except Exception as e:
            logger.error(f"Admin {admin_id} ga xabar yuborilmadi: {e}")
    
    # Boshqa mijozlarga qoldiq haqida xabar
    asyncio.create_task(
        notify_all_clients_about_stock(
            except_user_id=user_id,
            new_order_qty=data['quantity']
        )
    )
    
    await callback.answer("✅ Zakaz qabul qilindi!")

# ==================== ADMIN PANEL ====================

@dp.message(F.text == "⚙️ Admin panel")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Ruxsat yo'q!")
        return
    
    remaining = get_remaining()
    active_orders = len([o for o in orders.values() 
                        if o['status'] in ['kutilmoqda', 'tasdiqlandi', 'yetkazilmoqda']])
    
    text = (
        f"⚙️ *Admin Panel*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Qolgan mahsulot: *{remaining} ta*\n"
        f"📋 Faol zakazlar: *{active_orders} ta*\n"
        f"👥 Ro'yxatdagi mijozlar: *{len(all_clients)} ta*\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=admin_keyboard())

@dp.message(F.text == "📋 Barcha zakazlar")
async def all_orders_list(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    active = [o for o in orders.values() 
             if o['status'] in ['kutilmoqda', 'tasdiqlandi', 'yetkazilmoqda']]
    
    if not active:
        await message.answer("📭 Faol zakazlar yo'q.")
        return
    
    for order in sorted(active, key=lambda x: x['id'])[-10:]:
        text = format_order_summary(order)
        await message.answer(text, parse_mode="Markdown",
                            reply_markup=order_action_keyboard(order['id']))

@dp.message(F.text == "📊 Statistika")
async def show_statistics(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    total = len(orders)
    by_status = {}
    by_type = {}
    total_qty = 0
    
    for o in orders.values():
        by_status[o['status']] = by_status.get(o['status'], 0) + 1
        by_type[o['client_type']] = by_type.get(o['client_type'], 0) + 1
        total_qty += o['quantity']
    
    text = (
        f"📊 *Umumiy statistika*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Jami zakazlar: *{total} ta*\n"
        f"📦 Jami mahsulot: *{total_qty} ta*\n"
        f"⬜ Qolgan: *{get_remaining()} ta*\n\n"
        f"*Status bo'yicha:*\n"
    )
    
    status_names = {"kutilmoqda": "⏳ Kutilmoqda", "tasdiqlandi": "✅ Tasdiqlandi",
                   "yetkazilmoqda": "🚚 Yetkazilmoqda", "yetkazildi": "✔️ Yetkazildi",
                   "bekor_qilindi": "❌ Bekor qilingan"}
    
    for status, count in by_status.items():
        text += f"  {status_names.get(status, status)}: *{count}*\n"
    
    text += "\n*Mijoz turi bo'yicha:*\n"
    for ctype, count in by_type.items():
        text += f"  {CLIENT_TYPES.get(ctype, ctype)}: *{count}*\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📢 Xabar yuborish")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "📢 *Barcha mijozlarga yuborish uchun xabar yozing:*\n\n"
        "Bekor qilish uchun /cancel",
        parse_mode="Markdown"
    )
    await state.set_state(AdminStates.broadcasting)

@dp.message(StateFilter(AdminStates.broadcasting))
async def do_broadcast(message: types.Message, state: FSMContext):
    await state.clear()
    sent = 0
    for user_id in all_clients:
        try:
            await bot.send_message(user_id, f"📢 *Sexdan xabar:*\n\n{message.text}",
                                  parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ Xabar *{sent}* ta foydalanuvchiga yuborildi!",
                        parse_mode="Markdown")

@dp.message(Command("cancel"))
async def cancel_any(message: types.Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("❌ Bekor qilindi.", reply_markup=main_menu_keyboard(is_admin))

# ==================== ZAKAZ STATUS O'ZGARTIRISH ====================

@dp.callback_query(F.data.startswith(("confirm_", "delivering_", "delivered_", "cancel_")))
async def handle_order_action(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return
    
    parts = callback.data.split("_")
    action = parts[0]
    order_id = int(parts[1])
    
    if order_id not in orders:
        await callback.answer("❌ Zakaz topilmadi!", show_alert=True)
        return
    
    order = orders[order_id]
    
    status_map = {
        "confirm": ("tasdiqlandi", "✅ Zakaz tasdiqlandi!"),
        "delivering": ("yetkazilmoqda", "🚚 Yetkazish boshlandi!"),
        "delivered": ("yetkazildi", "✔️ Yetkazib berildi!"),
        "cancel": ("bekor_qilindi", "❌ Zakaz bekor qilindi!")
    }
    
    if action not in status_map:
        await callback.answer("Noma'lum amal")
        return
    
    new_status, status_msg = status_map[action]
    old_status = order['status']
    
    # Agar bekor qilinsa, mahsulotni qaytarish
    if action == "cancel" and old_status not in ["bekor_qilindi", "yetkazildi"]:
        global daily_used
        daily_used = max(0, daily_used - order['quantity'])
    
    order['status'] = new_status
    
    # Admin xabarini yangilash
    await callback.message.edit_text(
        format_order_summary(order),
        parse_mode="Markdown",
        reply_markup=order_action_keyboard(order_id) if new_status not in ["yetkazildi", "bekor_qilindi"] else None
    )
    
    # Mijozga bildirishnoma
    status_emoji = {"tasdiqlandi": "✅", "yetkazilmoqda": "🚚", 
                   "yetkazildi": "✔️", "bekor_qilindi": "❌"}
    
    client_msg = (
        f"{status_emoji.get(new_status, '📦')} *Zakaz #{order_id} yangilandi!*\n\n"
        f"📌 Yangi status: *{new_status.upper()}*\n"
        f"📊 Miqdor: {order['quantity']} ta\n"
        f"🕐 {datetime.now().strftime('%H:%M')}"
    )
    
    if new_status == "yetkazildi":
        client_msg += "\n\n🎉 Xarid uchun rahmat!"
    elif new_status == "bekor_qilindi":
        client_msg += "\n\nℹ️ Savollar uchun bog'laning."
    
    try:
        await bot.send_message(order['user_id'], client_msg, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Mijozga xabar yuborilmadi: {e}")
    
    await callback.answer(status_msg)

@dp.message(F.text == "🏠 Asosiy menyu")
async def back_to_main(message: types.Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("🏠 Asosiy menyu", reply_markup=main_menu_keyboard(is_admin))

# ==================== ISHGA TUSHIRISH ====================

async def main():
    logger.info("🤖 Bot ishga tushmoqda...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
