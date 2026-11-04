
import asyncio
import logging
import os
import sqlite3
from datetime import date

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# ==========================================
# SOZLAMALAR
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo")
OWNER_ID = int(os.getenv("ADMIN_ID", "5200398952"))

DB_PATH = os.getenv("DB_PATH", "/var/data/bot.sqlite3")

REFERRAL_BONUS = 2
DAILY_BONUS = 1

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==========================================
# MA'LUMOTLAR BAZASI
# ==========================================

def connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        balance INTEGER DEFAULT 0,
        earned INTEGER DEFAULT 0,
        referrer INTEGER,
        ref_paid INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0,
        daily_date TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT UNIQUE,
        title TEXT,
        invite_link TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS promo_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        amount INTEGER,
        active INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS promo_uses (
        user_id INTEGER,
        promo_id INTEGER,
        UNIQUE(user_id, promo_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute(
        "INSERT OR IGNORE INTO admins(user_id) VALUES(?)",
        (OWNER_ID,)
    )

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = connect()
    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    return row


def is_admin(user_id):
    conn = connect()
    row = conn.execute(
        "SELECT user_id FROM admins WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    return row is not None


def add_transaction(user_id, amount, description):
    conn = connect()
    conn.execute("""
        INSERT INTO transactions(user_id, amount, description)
        VALUES(?,?,?)
    """, (user_id, amount, description))
    conn.commit()
    conn.close()


def register_user(user, referrer=None):
    conn = connect()
    cur = conn.cursor()

    existing = cur.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    ).fetchone()

    if not existing:
        if referrer == user.id:
            referrer = None

        if referrer:
            ref_exists = cur.execute(
                "SELECT user_id FROM users WHERE user_id=?",
                (referrer,)
            ).fetchone()

            if not ref_exists:
                referrer = None

        cur.execute("""
            INSERT INTO users(
                user_id, username, full_name, referrer
            )
            VALUES(?,?,?,?)
        """, (
            user.id,
            user.username or "",
            user.full_name,
            referrer
        ))
    else:
        cur.execute("""
            UPDATE users
            SET username=?, full_name=?
            WHERE user_id=?
        """, (
            user.username or "",
            user.full_name,
            user.id
        ))

    conn.commit()
    conn.close()


def pay_referral(user_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute("BEGIN IMMEDIATE")

    user = cur.execute("""
        SELECT referrer, ref_paid
        FROM users WHERE user_id=?
    """, (user_id,)).fetchone()

    if user and user["referrer"] and not user["ref_paid"]:
        referrer = user["referrer"]

        cur.execute("""
            UPDATE users
            SET balance=balance+?, earned=earned+?
            WHERE user_id=?
        """, (REFERRAL_BONUS, REFERRAL_BONUS, referrer))

        cur.execute("""
            UPDATE users SET ref_paid=1
            WHERE user_id=?
        """, (user_id,))

        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?,?,?)
        """, (
            referrer,
            REFERRAL_BONUS,
            "Referal bonusi"
        ))

    conn.commit()
    conn.close()


# ==========================================
# FSM HOLATLARI
# ==========================================

class PromoStates(StatesGroup):
    waiting_code = State()


class AdminStates(StatesGroup):
    promo_name = State()
    promo_amount = State()

    channel_id = State()
    channel_link = State()

    broadcast = State()

    search_user = State()
    balance_user = State()
    balance_amount = State()

    add_admin = State()
    remove_admin = State()


class SupportStates(StatesGroup):
    waiting_message = State()
    waiting_reply = State()


# ==========================================
# KLAVIATURALAR
# ==========================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👥 Referal"),
                KeyboardButton(text="💰 Mening hisobim")
            ],
            [
                KeyboardButton(text="🎁 Gift yechish"),
                KeyboardButton(text="📦 Buyurtmalarim")
            ],
            [
                KeyboardButton(text="🎟 Promokod"),
                KeyboardButton(text="🌟 Kunlik bonus")
            ],
            [
                KeyboardButton(text="📩 Adminga murojaat"),
                KeyboardButton(text="📖 Qo‘llanma")
            ]
        ],
        resize_keyboard=True
    )


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📊 Statistika",
                callback_data="admin_stats"
            )
        ],
        [
            InlineKeyboardButton(
                text="👥 Foydalanuvchilar",
                callback_data="admin_users"
            ),
            InlineKeyboardButton(
                text="🔎 Foydalanuvchi qidirish",
                callback_data="admin_search"
            )
        ],
        [
            InlineKeyboardButton(
                text="💰 Balans boshqarish",
                callback_data="admin_balance"
            )
        ],
        [
            InlineKeyboardButton(
                text="📢 Reklama tarqatish",
                callback_data="admin_broadcast"
            )
        ],
        [
            InlineKeyboardButton(
                text="📡 Kanal qo‘shish",
                callback_data="admin_add_channel"
            ),
            InlineKeyboardButton(
                text="📋 Kanallar",
                callback_data="admin_channels"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎟 Promokod yaratish",
                callback_data="admin_promo"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎁 Buyurtmalar",
                callback_data="admin_orders"
            )
        ],
        [
            InlineKeyboardButton(
                text="➕ Admin qo‘shish",
                callback_data="admin_add_admin"
            ),
            InlineKeyboardButton(
                text="➖ Admin o‘chirish",
                callback_data="admin_remove_admin"
            )
        ]
    ])


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True
    )


# ==========================================
# OBUNA TEKSHIRISH
# ==========================================

def get_channels():
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM channels ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return rows


async def check_subscription(user_id):
    channels = get_channels()

    for channel in channels:
        try:
            member = await bot.get_chat_member(
                chat_id=channel["chat_id"],
                user_id=user_id
            )

            if member.status in ("left", "kicked"):
                return False

        except Exception:
            return False

    return True


async def subscription_screen(message):
    channels = get_channels()

    buttons = []

    for channel in channels:
        link = channel["invite_link"]

        if link:
            buttons.append([
                InlineKeyboardButton(
                    text=f"➕ {channel['title']}",
                    url=link
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    await message.answer(
        "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ==========================================
# START
# ==========================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    referrer = None
    args = message.text.split(maxsplit=1)

    if len(args) > 1 and args[1].isdigit():
        referrer = int(args[1])

    register_user(message.from_user, referrer)

    user = get_user(message.from_user.id)

    if user["banned"]:
        await message.answer("🚫 Siz botdan foydalanish huquqidan mahrum qilingansiz.")
        return

    if not await check_subscription(message.from_user.id):
        await subscription_screen(message)
        return

    pay_referral(message.from_user.id)

    await message.answer(
        "👋 Assalomu alaykum!\n\n"
        "Botimizga xush kelibsiz!",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    if not await check_subscription(callback.from_user.id):
        await callback.answer(
            "❌ Hali barcha kanallarga obuna bo‘lmagansiz!",
            show_alert=True
        )
        return

    pay_referral(callback.from_user.id)

    await callback.message.answer(
        "✅ Obuna tasdiqlandi!",
        reply_markup=main_keyboard()
    )
    await callback.answer()


# ==========================================
# UMUMIY TEKSHIRUV
# ==========================================

@dp.message(Command("cancel"))
@dp.message(F.text == "❌ Bekor qilish")
async def cancel_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Amal bekor qilindi.",
        reply_markup=main_keyboard()
    )


# ==========================================
# FOYDALANUVCHI PANELI
# ==========================================

@dp.message(F.text == "💰 Mening hisobim")
async def my_balance(message: Message):
    user = get_user(message.from_user.id)

    if not user:
        return

    conn = connect()
    refs = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE referrer=? AND ref_paid=1",
        (message.from_user.id,)
    ).fetchone()["n"]
    conn.close()

    await message.answer(
        f"💰 Hisobingiz\n\n"
        f"⭐ Balans: {user['balance']} Stars\n"
        f"🏆 Jami ishlab topilgan: {user['earned']} Stars\n"
        f"👥 Referallar: {refs}"
    )


@dp.message(F.text == "👥 Referal")
async def referral(message: Message):
    link = f"https://t.me/{(await bot.get_me()).username}?start={message.from_user.id}"

    conn = connect()
    count = conn.execute("""
        SELECT COUNT(*) AS n
        FROM users
        WHERE referrer=? AND ref_paid=1
    """, (message.from_user.id,)).fetchone()["n"]
    conn.close()

    await message.answer(
        f"👥 Referal tizimi\n\n"
        f"🔗 Sizning havolangiz:\n{link}\n\n"
        f"💎 Har bir yangi foydalanuvchi uchun {REFERRAL_BONUS} Stars.\n"
        f"👤 Taklif qilganlaringiz: {count}"
    )


@dp.message(F.text == "🌟 Kunlik bonus")
async def daily_bonus(message: Message):
    conn = connect()
    cur = conn.cursor()

    cur.execute("BEGIN IMMEDIATE")

    user = cur.execute(
        "SELECT daily_date FROM users WHERE user_id=?",
        (message.from_user.id,)
    ).fetchone()

    if not user:
        conn.rollback()
        conn.close()
        return

    today = date.today().isoformat()

    if user["daily_date"] == today:
        conn.rollback()
        conn.close()
        await message.answer("⏳ Bugungi bonusni olib bo‘lgansiz.")
        return

    cur.execute("""
        UPDATE users
        SET balance=balance+?, earned=earned+?, daily_date=?
        WHERE user_id=?
    """, (
        DAILY_BONUS,
        DAILY_BONUS,
        today,
        message.from_user.id
    ))

    cur.execute("""
        INSERT INTO transactions(user_id, amount, description)
        VALUES(?,?,?)
    """, (
        message.from_user.id,
        DAILY_BONUS,
        "Kunlik bonus"
    ))

    conn.commit()
    conn.close()

    await message.answer(
        f"🎉 Sizga {DAILY_BONUS} Stars bonus berildi!"
    )


@dp.message(F.text == "📖 Qo‘llanma")
async def guide(message: Message):
    await message.answer(
        "📖 BOT QO‘LLANMASI\n\n"
        "👥 Referal — do‘stlaringizni taklif qiling.\n"
        "💰 Mening hisobim — balansingizni ko‘ring.\n"
        "🎁 Gift yechish — 15 yoki 25 Stars uchun so‘rov yuboring.\n"
        "📦 Buyurtmalarim — buyurtmalaringizni ko‘ring.\n"
        "🎟 Promokod — kod orqali Stars oling.\n"
        "🌟 Kunlik bonus — har kuni bonus oling."
    )


# ==========================================
# GIFT YECHISH
# ==========================================

@dp.message(F.text == "🎁 Gift yechish")
async def gift_menu(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="15 ⭐",
                callback_data="gift_15"
            ),
            InlineKeyboardButton(
                text="25 ⭐",
                callback_data="gift_25"
            )
        ]
    ])

    await message.answer(
        "🎁 Gift miqdorini tanlang:",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.in_(["gift_15", "gift_25"]))
async def create_gift(callback: CallbackQuery):
    amount = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    conn = connect()
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    user = cur.execute(
        "SELECT balance FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not user or user["balance"] < amount:
        conn.rollback()
        conn.close()
        await callback.answer(
            "Mablag‘ yetarli emas!",
            show_alert=True
        )
        return

    cur.execute("""
        UPDATE users SET balance=balance-?
        WHERE user_id=?
    """, (amount, user_id))

    cur.execute("""
        INSERT INTO orders(user_id, amount)
        VALUES(?,?)
    """, (user_id, amount))

    order_id = cur.lastrowid

    cur.execute("""
        INSERT INTO transactions(user_id, amount, description)
        VALUES(?,?,?)
    """, (user_id, -amount, f"Gift buyurtmasi #{order_id}"))

    conn.commit()
    conn.close()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"approve_{order_id}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"reject_{order_id}"
            )
        ]
    ])

    user = callback.from_user

    for admin_id in get_admin_ids():
        try:
            await bot.send_message(
                admin_id,
                f"🎁 YANGI GIFT BUYURTMASI\n\n"
                f"🆔 Buyurtma: #{order_id}\n"
                f"👤 Foydalanuvchi: {user.full_name}\n"
                f"🆔 ID: {user_id}\n"
                f"⭐ Miqdor: {amount}",
                reply_markup=keyboard
            )
        except Exception:
            pass

    await callback.message.answer(
        f"✅ Buyurtmangiz yuborildi!\n"
        f"🆔 Buyurtma: #{order_id}\n"
        f"⭐ Miqdor: {amount} Stars\n\n"
        f"Admin javobini kuting."
    )

    await callback.answer("Buyurtma yaratildi!")


def get_admin_ids():
    conn = connect()
    rows = conn.execute("SELECT user_id FROM admins").fetchall()
    conn.close()
    return [row["user_id"] for row in rows]


# ==========================================
# ADMIN BUYURTMANI TASDIQLASH / RAD ETISH
# ==========================================

async def decide_order(callback: CallbackQuery, order_id: int, approve: bool):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    conn = connect()
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    order = cur.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

    if not order or order["status"] != "pending":
        conn.rollback()
        conn.close()
        await callback.answer(
            "Bu buyurtma allaqachon ko‘rib chiqilgan!",
            show_alert=True
        )
        return

    if approve:
        cur.execute(
            "UPDATE orders SET status='approved' WHERE id=?",
            (order_id,)
        )
        status_text = "tasdiqlandi"
    else:
        cur.execute(
            "UPDATE orders SET status='rejected' WHERE id=?",
            (order_id,)
        )

        cur.execute("""
            UPDATE users
            SET balance=balance+?
            WHERE user_id=?
        """, (order["amount"], order["user_id"]))

        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?,?,?)
        """, (
            order["user_id"],
            order["amount"],
            f"Rad etilgan buyurtma #{order_id} qaytarimi"
        ))

        status_text = "rad etildi, Stars qaytarildi"

    conn.commit()
    conn.close()

    try:
        await bot.send_message(
            order["user_id"],
            f"🎁 #{order_id} buyurtmangiz {status_text}."
        )
    except Exception:
        pass

    await callback.message.edit_text(
        f"Buyurtma #{order_id} {status_text}."
    )
    await callback.answer("Bajarildi!")


@dp.callback_query(F.data.startswith("approve_"))
async def approve_order(callback: CallbackQuery):
    await decide_order(
        callback,
        int(callback.data.split("_")[1]),
        True
    )


@dp.callback_query(F.data.startswith("reject_"))
async def reject_order(callback: CallbackQuery):
    await decide_order(
        callback,
        int(callback.data.split("_")[1]),
        False
    )


@dp.message(F.text == "📦 Buyurtmalarim")
async def my_orders(message: Message):
    conn = connect()
    rows = conn.execute("""
        SELECT * FROM orders
        WHERE user_id=?
        ORDER BY id DESC LIMIT 20
    """, (message.from_user.id,)).fetchall()
    conn.close()

    if not rows:
        await message.answer("Sizda hali buyurtmalar yo‘q.")
        return

    text = "📦 BUYURTMALARIM\n\n"

    for order in rows:
        text += (
            f"🆔 #{order['id']}\n"
            f"⭐ {order['amount']} Stars\n"
            f"📌 Holat: {order['status']}\n\n"
        )

    await message.answer(text)


# ==========================================
# PROMOKOD
# ==========================================

@dp.message(F.text == "🎟 Promokod")
async def promo_start(message: Message, state: FSMContext):
    await state.set_state(PromoStates.waiting_code)

    await message.answer(
        "🎟 Promokod nomini yuboring:",
        reply_markup=cancel_keyboard()
    )


@dp.message(PromoStates.waiting_code)
async def promo_redeem(message: Message, state: FSMContext):
    code = message.text.strip().upper()

    conn = connect()
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    promo = cur.execute("""
        SELECT * FROM promo_codes
        WHERE code=? AND active=1
    """, (code,)).fetchone()

    if not promo:
        conn.rollback()
        conn.close()
        await message.answer("❌ Promokod topilmadi.")
        await state.clear()
        return

    used = cur.execute("""
        SELECT 1 FROM promo_uses
        WHERE user_id=? AND promo_id=?
    """, (message.from_user.id, promo["id"])).fetchone()

    if used:
        conn.rollback()
        conn.close()
        await message.answer("❌ Siz bu promokoddan oldin foydalangansiz.")
        await state.clear()
        return

    cur.execute("""
        INSERT INTO promo_uses(user_id, promo_id)
        VALUES(?,?)
    """, (message.from_user.id, promo["id"]))

    cur.execute("""
        UPDATE users
        SET balance=balance+?, earned=earned+?
        WHERE user_id=?
    """, (
        promo["amount"],
        promo["amount"],
        message.from_user.id
    ))

    cur.execute("""
        INSERT INTO transactions(user_id, amount, description)
        VALUES(?,?,?)
    """, (
        message.from_user.id,
        promo["amount"],
        f"Promokod: {code}"
    ))

    conn.commit()
    conn.close()

    await state.clear()

    await message.answer(
        f"🎉 Promokod qabul qilindi!\n"
        f"⭐ Hisobingizga {promo['amount']} Stars qo‘shildi.",
        reply_markup=main_keyboard()
    )


# ==========================================
# ADMiN PANEL
# ==========================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Siz admin emassiz.")
        return

    await message.answer(
        "⚙️ ADMIN PANEL",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    conn = connect()

    users = conn.execute(
        "SELECT COUNT(*) AS n FROM users"
    ).fetchone()["n"]

    orders = conn.execute(
        "SELECT COUNT(*) AS n FROM orders"
    ).fetchone()["n"]

    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE status='pending'"
    ).fetchone()["n"]

    balance = conn.execute(
        "SELECT COALESCE(SUM(balance),0) AS n FROM users"
    ).fetchone()["n"]

    conn.close()

    await callback.message.answer(
        f"📊 STATISTIKA\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"📦 Buyurtmalar: {orders}\n"
        f"⏳ Kutilayotgan: {pending}\n"
        f"⭐ Jami balans: {balance}"
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    conn = connect()
    rows = conn.execute("""
        SELECT user_id, full_name, balance, banned
        FROM users ORDER BY user_id DESC LIMIT 20
    """).fetchall()
    conn.close()

    if not rows:
        await callback.message.answer("Foydalanuvchilar yo‘q.")
        return

    text = "👥 OXIRGI FOYDALANUVCHILAR\n\n"

    for row in rows:
        text += (
            f"👤 {row['full_name']}\n"
            f"🆔 {row['user_id']}\n"
            f"⭐ {row['balance']}\n"
            f"🚫 Blok: {'Ha' if row['banned'] else 'Yo‘q'}\n\n"
        )

    await callback.message.answer(text)
    await callback.answer()


# ==========================================
# FOYDALANUVCHI QIDIRISH
# ==========================================

@dp.callback_query(F.data == "admin_search")
async def admin_search(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(AdminStates.search_user)
    await callback.message.answer("Foydalanuvchi ID raqamini yuboring:")
    await callback.answer()


@dp.message(AdminStates.search_user)
async def admin_search_result(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text.isdigit():
        await message.answer("ID faqat raqamlardan iborat bo‘lishi kerak.")
        return

    user_id = int(message.text)
    user = get_user(user_id)

    await state.clear()

    if not user:
        await message.answer("Foydalanuvchi topilmadi.")
        return

    conn = connect()

    refs = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE referrer=?",
        (user_id,)
    ).fetchone()["n"]

    orders = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE user_id=?",
        (user_id,)
    ).fetchone()["n"]

    conn.close()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🚫 Bloklash",
                callback_data=f"ban_{user_id}"
            ),
            InlineKeyboardButton(
                text="✅ Blokdan chiqarish",
                callback_data=f"unban_{user_id}"
            )
        ]
    ])

    await message.answer(
        f"👤 FOYDALANUVCHI\n\n"
        f"🆔 ID: {user_id}\n"
        f"👤 Ism: {user['full_name']}\n"
        f"⭐ Balans: {user['balance']}\n"
        f"🏆 Ishlab topgan: {user['earned']}\n"
        f"👥 Referallar: {refs}\n"
        f"📦 Buyurtmalar: {orders}\n"
        f"🚫 Bloklangan: {user['banned']}",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("ban_"))
async def ban_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    user_id = int(callback.data.split("_")[1])

    conn = connect()
    conn.execute(
        "UPDATE users SET banned=1 WHERE user_id=?",
        (user_id,)
    )
    conn.commit()
    conn.close()

    await callback.answer("Foydalanuvchi bloklandi!")
    await callback.message.answer(f"🚫 {user_id} bloklandi.")


@dp.callback_query(F.data.startswith("unban_"))
async def unban_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    user_id = int(callback.data.split("_")[1])

    conn = connect()
    conn.execute(
        "UPDATE users SET banned=0 WHERE user_id=?",
        (user_id,)
    )
    conn.commit()
    conn.close()

    await callback.answer("Blokdan chiqarildi!")
    await callback.message.answer(f"✅ {user_id} blokdan chiqarildi.")


# ==========================================
# BALANS BOSHQARISH
# ==========================================

@dp.callback_query(F.data == "admin_balance")
async def admin_balance_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(AdminStates.balance_user)
    await callback.message.answer("Foydalanuvchi ID raqamini yuboring:")
    await callback.answer()


@dp.message(AdminStates.balance_user)
async def admin_balance_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text.isdigit():
        await message.answer("ID raqam bo‘lishi kerak.")
        return

    user_id = int(message.text)

    if not get_user(user_id):
        await message.answer("Foydalanuvchi topilmadi.")
        await state.clear()
        return

    await state.update_data(target_user=user_id)
    await state.set_state(AdminStates.balance_amount)

    await message.answer(
        "Balans miqdorini yuboring.\n"
        "Masalan: 10 yoki -5"
    )


@dp.message(AdminStates.balance_amount)
async def admin_balance_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        amount = int(message.text)
    except (ValueError, TypeError):
        await message.answer("Butun son yuboring.")
        return

    if amount == 0:
        await message.answer("Miqdor 0 bo‘lmasligi kerak.")
        return

    data = await state.get_data()
    user_id = data["target_user"]

    conn = connect()
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    user = cur.execute(
        "SELECT balance FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not user or user["balance"] + amount < 0:
        conn.rollback()
        conn.close()
        await message.answer("Balans yetarli emas yoki foydalanuvchi topilmadi.")
        await state.clear()
        return

    cur.execute("""
        UPDATE users
        SET balance=balance+?,
            earned=CASE WHEN ? > 0 THEN earned+? ELSE earned END
        WHERE user_id=?
    """, (amount, amount, amount, user_id))

    cur.execute("""
        INSERT INTO transactions(user_id, amount, description)
        VALUES(?,?,?)
    """, (user_id, amount, "Admin balans o‘zgartirdi"))

    conn.commit()
    conn.close()

    await state.clear()

    await message.answer("✅ Balans o‘zgartirildi.")

    try:
        await bot.send_message(
            user_id,
            f"💰 Hisobingiz {amount} Stars ga o‘zgartirildi."
        )
    except Exception:
        pass


# ==========================================
# PROMOKOD YARATISH
# ==========================================

@dp.callback_query(F.data == "admin_promo")
async def admin_promo_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(AdminStates.promo_name)
    await callback.message.answer("Promokod nomini kiriting:")
    await callback.answer()


@dp.message(AdminStates.promo_name)
async def admin_promo_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    code = message.text.strip().upper()

    if not code or len(code) > 40:
        await message.answer("Promokod 1–40 ta belgidan iborat bo‘lsin.")
        return

    await state.update_data(promo_code=code)
    await state.set_state(AdminStates.promo_amount)

    await message.answer("Endi promokod beradigan Stars miqdorini yuboring:")


@dp.message(AdminStates.promo_amount)
async def admin_promo_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Musbat butun son yuboring.")
        return

    data = await state.get_data()
    code = data["promo_code"]
    amount = int(message.text)

    conn = connect()

    try:
        conn.execute("""
            INSERT INTO promo_codes(code, amount)
            VALUES(?,?)
        """, (code, amount))
        conn.commit()
    except sqlite3.IntegrityError:
        await message.answer("Bu promokod avval yaratilgan.")
        conn.close()
        await state.clear()
        return

    conn.close()
    await state.clear()

    await message.answer(
        f"✅ Promokod yaratildi!\n\n"
        f"🎟 Kod: {code}\n"
        f"⭐ Miqdor: {amount}"
    )


# ==========================================
# KANAL QO‘SHISH VA O‘CHIRISH
# ==========================================

@dp.callback_query(F.data == "admin_add_channel")
async def add_channel_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(AdminStates.channel_id)

    await callback.message.answer(
        "Kanal ID yoki @username yuboring.\n\n"
        "Masalan: @kanal_nomi yoki -1001234567890"
    )

    await callback.answer()


@dp.message(AdminStates.channel_id)
async def add_channel_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    chat_id = message.text.strip()

    try:
        chat = await bot.get_chat(chat_id)
    except Exception:
        await message.answer(
            "❌ Kanal topilmadi. Bot kanalga qo‘shilganini va ID to‘g‘riligini tekshiring."
        )
        return

    await state.update_data(
        channel_id=str(chat.id),
        channel_title=chat.title or chat.username or str(chat.id)
    )

    await state.set_state(AdminStates.channel_link)

    await message.answer(
        "Kanalga obuna bo‘lish havolasini yuboring.\n"
        "Ochiq kanal uchun https://t.me/username.\n"
        "Agar kanalga taklif havolasi bo‘lmasa, `yoq` deb yuboring."
    )


@dp.message(AdminStates.channel_link)
async def add_channel_link(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    link = message.text.strip()

    if link.lower() == "yoq":
        link = ""

    if link and not (
        link.startswith("https://t.me/")
        or link.startswith("http://t.me/")
    ):
        await message.answer("To‘g‘ri Telegram havolasini yuboring yoki yoq deb yozing.")
        return

    data = await state.get_data()

    conn = connect()

    try:
        conn.execute("""
            INSERT INTO channels(chat_id, title, invite_link)
            VALUES(?,?,?)
        """, (
            data["channel_id"],
            data["channel_title"],
            link
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        await message.answer("Bu kanal avval qo‘shilgan.")
        conn.close()
        await state.clear()
        return

    conn.close()
    await state.clear()

    await message.answer(
        f"✅ Kanal qo‘shildi!\n"
        f"📡 {data['channel_title']}\n\n"
        f"Bu kanal majburiy obuna va kanal reklamasi ro‘yxatiga qo‘shildi."
    )


@dp.callback_query(F.data == "admin_channels")
async def admin_channels(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    channels = get_channels()

    if not channels:
        await callback.message.answer("Kanallar ro‘yxati bo‘sh.")
        await callback.answer()
        return

    for channel in channels:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🗑 Kanalni o‘chirish",
                callback_data=f"delchannel_{channel['id']}"
            )
        ]])

        await callback.message.answer(
            f"📡 {channel['title']}\n"
            f"🆔 {channel['chat_id']}\n"
            f"🔗 {channel['invite_link'] or 'Havola yo‘q'}",
            reply_markup=keyboard
        )

    await callback.answer()


@dp.callback_query(F.data.startswith("delchannel_"))
async def delete_channel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    channel_id = int(callback.data.split("_")[1])

    conn = connect()
    conn.execute(
        "DELETE FROM channels WHERE id=?",
        (channel_id,)
    )
    conn.commit()
    conn.close()

    await callback.message.edit_text("🗑 Kanal o‘chirildi.")
    await callback.answer()


# ==========================================
# REKLAMA TARQATISH
# ==========================================

@dp.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="👥 Foydalanuvchilarga",
                callback_data="broadcast_users"
            )
        ],
        [
            InlineKeyboardButton(
                text="📡 Barcha kanallarga",
                callback_data="broadcast_channels"
            )
        ]
    ])

    await callback.message.answer(
        "Reklama qayerga yuborilsin?",
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data.in_(["broadcast_users", "broadcast_channels"]))
async def broadcast_target(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    target = (
        "users"
        if callback.data == "broadcast_users"
        else "channels"
    )

    await state.update_data(broadcast_target=target)
    await state.set_state(AdminStates.broadcast)

    await callback.message.answer(
        "📢 Endi reklama xabarini yuboring.\n\n"
        "Matn, rasm yoki video yuborishingiz mumkin.\n"
        "Xabar nusxasi tarqatiladi."
    )

    await callback.answer()


@dp.message(AdminStates.broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    target = data.get("broadcast_target")

    await state.clear()

    if target == "users":
        conn = connect()
        users = conn.execute(
            "SELECT user_id FROM users WHERE banned=0"
        ).fetchall()
        conn.close()

        success = 0
        failed = 0

        for user in users:
            try:
                await bot.copy_message(
                    chat_id=user["user_id"],
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
                success += 1
            except Exception:
                failed += 1

            await asyncio.sleep(0.04)

        await message.answer(
            f"✅ Foydalanuvchilarga tarqatish tugadi.\n"
            f"Yuborildi: {success}\n"
            f"Yuborilmadi: {failed}"
        )

    elif target == "channels":
        channels = get_channels()

        success = 0
        failed = 0

        for channel in channels:
            try:
                await bot.copy_message(
                    chat_id=channel["chat_id"],
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
                success += 1
            except Exception:
                failed += 1

            await asyncio.sleep(0.05)

        await message.answer(
            f"✅ Kanallarga reklama tarqatish tugadi.\n"
            f"Yuborildi: {success}\n"
            f"Yuborilmadi: {failed}"
        )


# ==========================================
# ADMINLARNI BOSHQARISH
# ==========================================

@dp.callback_query(F.data == "admin_add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Faqat asosiy admin!", show_alert=True)
        return

    await state.set_state(AdminStates.add_admin)
    await callback.message.answer("Yangi adminning Telegram ID raqamini yuboring:")
    await callback.answer()


@dp.message(AdminStates.add_admin)
async def add_admin_finish(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return

    if not message.text.isdigit():
        await message.answer("ID raqam bo‘lishi kerak.")
        return

    user_id = int(message.text)

    conn = connect()
    conn.execute(
        "INSERT OR IGNORE INTO admins(user_id) VALUES(?)",
        (user_id,)
    )
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(f"✅ {user_id} admin qilindi.")


@dp.callback_query(F.data == "admin_remove_admin")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Faqat asosiy admin!", show_alert=True)
        return

    await state.set_state(AdminStates.remove_admin)
    await callback.message.answer("O‘chiriladigan admin ID raqamini yuboring:")
    await callback.answer()


@dp.message(AdminStates.remove_admin)
async def remove_admin_finish(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return

    if not message.text.isdigit():
        await message.answer("ID raqam bo‘lishi kerak.")
        return

    user_id = int(message.text)

    if user_id == OWNER_ID:
        await message.answer("Asosiy adminni o‘chirib bo‘lmaydi.")
        await state.clear()
        return

    conn = connect()
    conn.execute(
        "DELETE FROM admins WHERE user_id=?",
        (user_id,)
    )
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(f"✅ {user_id} adminlar ro‘yxatidan o‘chirildi.")


# ==========================================
# FOYDALANUVCHIDAN MUROJAAT
# ==========================================

@dp.message(F.text == "📩 Adminga murojaat")
async def support_start(message: Message, state: FSMContext):
    await state.set_state(SupportStates.waiting_message)

    await message.answer(
        "📩 Xabaringizni yuboring. U adminlarga yetkaziladi.",
        reply_markup=cancel_keyboard()
    )


@dp.message(SupportStates.waiting_message)
async def support_send(message: Message, state: FSMContext):
    if not message.text and not message.photo and not message.video:
        await message.answer("Matn, rasm yoki video yuboring.")
        return

    await state.clear()

    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO support_messages(user_id, message_id)
        VALUES(?,?)
    """, (message.from_user.id, message.message_id))

    support_id = cur.lastrowid
    conn.commit()
    conn.close()

    for admin_id in get_admin_ids():
        try:
            await bot.send_message(
                admin_id,
                f"📩 YANGI MUROJAAT\n"
                f"👤 {message.from_user.full_name}\n"
                f"🆔 {message.from_user.id}\n"
                f"📝 Murojaat #{support_id}"
            )

            await bot.copy_message(
                chat_id=admin_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )

            await bot.send_message(
                admin_id,
                "Javob berish:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="✉️ Javob yozish",
                        callback_data=f"supportreply_{message.from_user.id}"
                    )
                ]])
            )
        except Exception:
            pass

    await message.answer(
        "✅ Murojaatingiz adminlarga yuborildi.",
        reply_markup=main_keyboard()
    )


@dp.callback_query(F.data.startswith("supportreply_"))
async def support_reply_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    user_id = int(callback.data.split("_")[1])

    await state.update_data(support_user=user_id)
    await state.set_state(SupportStates.waiting_reply)

    await callback.message.answer(
        f"📝 {user_id} foydalanuvchiga javob matnini yuboring:"
    )

    await callback.answer()


@dp.message(SupportStates.waiting_reply)
async def support_reply_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    user_id = data["support_user"]

    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        await message.answer("✅ Javob yuborildi.")
    except Exception:
        await message.answer("❌ Xabar yuborilmadi.")

    await state.clear()


# ==========================================
# BUYURTMALARNI ADMINDA KO‘RISH
# ==========================================

@dp.callback_query(F.data == "admin_orders")
async def admin_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    conn = connect()
    rows = conn.execute("""
        SELECT * FROM orders
        WHERE status='pending'
        ORDER BY id DESC LIMIT 20
    """).fetchall()
    conn.close()

    if not rows:
        await callback.message.answer("⏳ Kutilayotgan buyurtmalar yo‘q.")
        await callback.answer()
        return

    for order in rows:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash",
                    callback_data=f"approve_{order['id']}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=f"reject_{order['id']}"
                )
            ]
        ])

        await callback.message.answer(
            f"🎁 BUYURTMA #{order['id']}\n"
            f"👤 ID: {order['user_id']}\n"
            f"⭐ Miqdor: {order['amount']}",
            reply_markup=keyboard
        )

    await callback.answer()


# ==========================================
# RENDER UCHUN WEB SERVER
# ==========================================

async def health(request):
    return web.Response(text="Bot ishlayapti!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()


# ==========================================
# BOTNI ISHGA TUSHIRISH
# ==========================================

async def main():
    if BOT_TOKEN == "BOT_TOKENINGIZNI_KIRITING":
        raise RuntimeError("BOT_TOKEN muhit o‘zgaruvchisini kiriting!")

    init_db()

    await start_web_server()

    logging.info("Bot ishga tushdi!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
