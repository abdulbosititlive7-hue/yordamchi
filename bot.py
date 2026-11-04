
import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

import aiosqlite
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


# =========================================================
# SOZLAMALAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo").strip()
ADMIN_ID_1 = int(os.getenv("ADMIN_ID_1", "5200398952"))
ADMIN_ID_2 = int(os.getenv("ADMIN_ID_2", "7676544759"))

DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")
PORT = int(os.getenv("PORT", "10000"))

REFERRAL_REWARD = int(os.getenv("REFERRAL_REWARD", "2"))
MIN_WITHDRAW = 15
MAX_WITHDRAW = 25

if not BOT_TOKEN:
    raise RuntimeError("Render Environment da BOT_TOKEN kiritilmagan!")

if not ADMIN_ID_1:
    raise RuntimeError("ADMIN_ID_1 kiritilmagan!")

ADMINS = {ADMIN_ID_1}
if ADMIN_ID_2:
    ADMINS.add(ADMIN_ID_2)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# =========================================================
# FSM HOLATLARI
# =========================================================

class UserState(StatesGroup):
    waiting_promo = State()
    waiting_support = State()


class AdminState(StatesGroup):
    waiting_balance = State()
    waiting_channel = State()
    waiting_broadcast = State()
    waiting_promo_create = State()
    waiting_news = State()
    waiting_task = State()
    waiting_reply = State()


# =========================================================
# MA'LUMOTLAR BAZASI
# =========================================================

async def db():
    return await aiosqlite.connect(DB_PATH)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as con:
        await con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            balance INTEGER DEFAULT 0,
            referrer_id INTEGER,
            blocked INTEGER DEFAULT 0,
            joined TEXT
        );

        CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS channels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE,
            invite_link TEXT
        );

        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS promos(
            code TEXT PRIMARY KEY,
            reward INTEGER,
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0,
            expires TEXT
        );

        CREATE TABLE IF NOT EXISTS promo_users(
            code TEXT,
            user_id INTEGER,
            PRIMARY KEY(code, user_id)
        );

        CREATE TABLE IF NOT EXISTS daily_claims(
            user_id INTEGER PRIMARY KEY,
            last_claim TEXT
        );

        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            link TEXT,
            reward INTEGER,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS task_claims(
            task_id INTEGER,
            user_id INTEGER,
            status TEXT DEFAULT 'pending',
            PRIMARY KEY(task_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS support(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS news(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            description TEXT,
            created TEXT
        );
        """)

        await con.execute(
            "INSERT OR IGNORE INTO admins(user_id, role) VALUES(?, 'main')",
            (ADMIN_ID_1,)
        )

        if ADMIN_ID_2:
            await con.execute(
                "INSERT OR IGNORE INTO admins(user_id, role) VALUES(?, 'admin')",
                (ADMIN_ID_2,)
            )

        await con.commit()


async def fetchone(query, args=()):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute(query, args)
        return await cur.fetchone()


async def fetchall(query, args=()):
    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute(query, args)
        return await cur.fetchall()


async def execute(query, args=()):
    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute(query, args)
        await con.commit()


async def add_transaction(user_id, amount, reason):
    await execute(
        "INSERT INTO transactions(user_id, amount, reason, created) VALUES(?,?,?,?)",
        (user_id, amount, reason, datetime.now().isoformat())
    )


async def change_balance(user_id, amount, reason):
    user = await fetchone(
        "SELECT balance FROM users WHERE user_id=?", (user_id,)
    )
    if not user:
        return False

    new_balance = user[0] + amount
    if new_balance < 0:
        return False

    await execute(
        "UPDATE users SET balance=? WHERE user_id=?",
        (new_balance, user_id)
    )
    await add_transaction(user_id, amount, reason)
    return True


# =========================================================
# UMUMIY FUNKSIYALAR
# =========================================================

def is_admin(user_id):
    return user_id in ADMINS


def is_main_admin(user_id):
    return user_id == ADMIN_ID_1


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👥 Referal", callback_data="referral"),
            InlineKeyboardButton(text="💰 Mening hisobim", callback_data="balance")
        ],
        [
            InlineKeyboardButton(text="⭐ Stars yechish", callback_data="withdraw"),
            InlineKeyboardButton(text="🎁 Promo-kod", callback_data="promo")
        ],
        [
            InlineKeyboardButton(text="📅 Kunlik bonus", callback_data="daily"),
            InlineKeyboardButton(text="📋 Topshiriqlar", callback_data="tasks")
        ],
        [
            InlineKeyboardButton(text="🏆 Reyting", callback_data="ranking"),
            InlineKeyboardButton(text="📰 Yangiliklar", callback_data="news")
        ],
        [
            InlineKeyboardButton(text="📨 Adminga murojaat", callback_data="support"),
            InlineKeyboardButton(text="📦 Buyurtmalar", callback_data="orders")
        ],
        [
            InlineKeyboardButton(text="📖 Qo‘llanma", callback_data="guide"),
            InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings")
        ]
    ])


def admin_menu(user_id):
    rows = [
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="a_stats"),
            InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="a_users")
        ],
        [
            InlineKeyboardButton(text="💰 Balans boshqarish", callback_data="a_balance"),
            InlineKeyboardButton(text="💸 Yechish so‘rovlari", callback_data="a_withdrawals")
        ],
        [
            InlineKeyboardButton(text="📢 Reklama tarqatish", callback_data="a_broadcast"),
            InlineKeyboardButton(text="📣 Kanallar", callback_data="a_channels")
        ],
        [
            InlineKeyboardButton(text="🎁 Promo yaratish", callback_data="a_promo"),
            InlineKeyboardButton(text="📋 Topshiriq qo‘shish", callback_data="a_task")
        ],
        [
            InlineKeyboardButton(text="📰 Yangilik yuborish", callback_data="a_news"),
            InlineKeyboardButton(text="📨 Murojaatlar", callback_data="a_support")
        ]
    ]

    if is_main_admin(user_id):
        rows.append([
            InlineKeyboardButton(text="⚙️ Admin sozlamalari", callback_data="a_settings")
        ])

    rows.append([
        InlineKeyboardButton(text="⬅️ Foydalanuvchi paneli", callback_data="back_home")
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def user_exists(user_id):
    return await fetchone(
        "SELECT user_id FROM users WHERE user_id=?", (user_id,)
    )


async def register_user(message: Message, referrer_id=None):
    user_id = message.from_user.id
    old = await user_exists(user_id)

    if old:
        await execute(
            "UPDATE users SET full_name=?, username=? WHERE user_id=?",
            (
                message.from_user.full_name,
                message.from_user.username or "",
                user_id
            )
        )
        return False

    if referrer_id == user_id:
        referrer_id = None

    if referrer_id and not await user_exists(referrer_id):
        referrer_id = None

    await execute("""
        INSERT INTO users(user_id, full_name, username, balance,
                          referrer_id, joined)
        VALUES(?,?,?,?,?,?)
    """, (
        user_id,
        message.from_user.full_name,
        message.from_user.username or "",
        0,
        referrer_id,
        datetime.now().isoformat()
    ))

    if referrer_id:
        await change_balance(
            referrer_id, REFERRAL_REWARD, "Referal mukofoti"
        )
        try:
            await bot.send_message(
                referrer_id,
                f"🎉 Yangi foydalanuvchi taklifingiz orqali kirdi!\n"
                f"Hisobingizga {REFERRAL_REWARD} Stars qo‘shildi."
            )
        except Exception:
            pass

    return True


async def check_subscription(user_id):
    channels = await fetchall("SELECT chat_id FROM channels")
    missing = []

    for (chat_id,) in channels:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in ("left", "kicked"):
                missing.append(chat_id)
        except Exception:
            missing.append(chat_id)

    return missing


async def subscription_keyboard(missing):
    rows = []
    for channel in missing:
        link = channel
        if str(channel).startswith("@"):
            link = "https://t.me/" + str(channel)[1:]

        rows.append([
            InlineKeyboardButton(
                text=f"➕ {channel} kanaliga obuna bo‘lish",
                url=link
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def allowed_user(user_id, message=None):
    if is_admin(user_id):
        return True

    user = await fetchone(
        "SELECT blocked FROM users WHERE user_id=?", (user_id,)
    )
    if user and user[0]:
        if message:
            await message.answer("⛔ Siz botdan foydalanish huquqidan mahrum qilingansiz.")
        return False

    missing = await check_subscription(user_id)
    if missing:
        if message:
            await message.answer(
                "❗ Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
                reply_markup=await subscription_keyboard(missing)
            )
        return False

    return True


async def safe_edit(call, text, reply_markup=None):
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await call.answer()


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    referrer = None
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].isdigit():
        referrer = int(parts[1])

    await register_user(message, referrer)

    if not await allowed_user(message.from_user.id, message):
        return

    text = (
        f"👋 Assalomu alaykum, {message.from_user.full_name}!\n\n"
        "🤖 Botimizga xush kelibsiz!\n"
        "Kerakli bo‘limni tanlang:"
    )

    await message.answer(text, reply_markup=main_menu())


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Siz admin emassiz.")

    await message.answer(
        "🛠 ADMIN PANEL",
        reply_markup=admin_menu(message.from_user.id)
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):
    missing = await check_subscription(call.from_user.id)

    if missing:
        await call.answer("❌ Hali barcha kanallarga obuna bo‘lmagansiz.", show_alert=True)
        return

    await call.answer("✅ Obuna tasdiqlandi!")
    await safe_edit(
        call,
        "✅ Obuna tasdiqlandi!\n\nAsosiy menyu:",
        main_menu()
    )


# =========================================================
# FOYDALANUVCHI PANELI
# =========================================================

@dp.callback_query(F.data == "back_home")
async def back_home(call: CallbackQuery):
    if not await allowed_user(call.from_user.id):
        await call.answer("Avval majburiy kanallarga obuna bo‘ling.", show_alert=True)
        return

    await safe_edit(call, "🏠 ASOSIY MENYU", main_menu())


@dp.callback_query(F.data == "referral")
async def referral(call: CallbackQuery):
    if not await allowed_user(call.from_user.id):
        return await call.answer("Kanalga obuna bo‘ling.", show_alert=True)

    me = await bot.get_me()
    count = await fetchone(
        "SELECT COUNT(*) FROM users WHERE referrer_id=?",
        (call.from_user.id,)
    )
    link = f"https://t.me/{me.username}?start={call.from_user.id}"

    await safe_edit(
        call,
        "👥 REFERAL TIZIMI\n\n"
        f"🔗 Sizning havolangiz:\n{link}\n\n"
        f"👤 Taklif qilganlaringiz: {count[0]}\n"
        f"🎁 Har bir referal uchun: {REFERRAL_REWARD} Stars",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]
        ])
    )


@dp.callback_query(F.data == "balance")
async def balance(call: CallbackQuery):
    row = await fetchone(
        "SELECT balance FROM users WHERE user_id=?",
        (call.from_user.id,)
    )
    amount = row[0] if row else 0

    await safe_edit(
        call,
        f"💰 HISOBINGIZ\n\n⭐ Balansingiz: {amount} Stars",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📜 Tarix", callback_data="history")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]
        ])
    )


@dp.callback_query(F.data == "history")
async def history(call: CallbackQuery):
    rows = await fetchall(
        "SELECT amount, reason, created FROM transactions "
        "WHERE user_id=? ORDER BY id DESC LIMIT 15",
        (call.from_user.id,)
    )

    text = "📜 BALANS TARIXI\n\n"
    if not rows:
        text += "Hozircha operatsiyalar mavjud emas."
    else:
        for amount, reason, created in rows:
            sign = "+" if amount > 0 else ""
            text += f"{sign}{amount} ⭐ — {reason}\n"

    await safe_edit(
        call, text,
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="balance")]
        ])
    )


@dp.callback_query(F.data == "withdraw")
async def withdraw(call: CallbackQuery):
    row = await fetchone(
        "SELECT balance FROM users WHERE user_id=?",
        (call.from_user.id,)
    )
    balance_amount = row[0] if row else 0

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="15 ⭐", callback_data="withdraw_15"),
            InlineKeyboardButton(text="25 ⭐", callback_data="withdraw_25")
        ],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]
    ])

    await safe_edit(
        call,
        f"⭐ STARS YECHISH\n\n"
        f"Balansingiz: {balance_amount} Stars\n"
        "Yechish miqdorini tanlang.\n"
        "So‘rov admin tomonidan ko‘rib chiqiladi.",
        keyboard
    )


async def create_withdrawal(call, amount):
    user_id = call.from_user.id

    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("BEGIN IMMEDIATE")
        cur = await con.execute(
            "SELECT balance FROM users WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()

        if not row or row[0] < amount:
            await con.rollback()
            await call.answer("❌ Balansingiz yetarli emas.", show_alert=True)
            return

        await con.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=?",
            (amount, user_id)
        )
        await con.execute(
            "INSERT INTO withdrawals(user_id, amount, created) VALUES(?,?,?)",
            (user_id, amount, datetime.now().isoformat())
        )
        await con.execute(
            "INSERT INTO transactions(user_id, amount, reason, created) VALUES(?,?,?,?)",
            (user_id, -amount, "Stars yechish so‘rovi", datetime.now().isoformat())
        )
        await con.commit()

    row = await fetchone(
        "SELECT id FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user_id,)
    )
    request_id = row[0]

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"wd_ok_{request_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"wd_no_{request_id}")
        ]
    ])

    for admin in ADMINS:
        try:
            await bot.send_message(
                admin,
                f"💸 YANGI YECHISH SO‘ROVI\n\n"
                f"ID: {request_id}\n"
                f"Foydalanuvchi: {user_id}\n"
                f"Miqdor: {amount} Stars",
                reply_markup=keyboard
            )
        except Exception:
            pass

    await call.answer("So‘rovingiz yuborildi!", show_alert=True)
    await safe_edit(
        call,
        "✅ Yechish so‘rovingiz adminga yuborildi.",
        main_menu()
    )


@dp.callback_query(F.data.startswith("withdraw_"))
async def withdraw_amount(call: CallbackQuery):
    try:
        amount = int(call.data.split("_")[1])
    except ValueError:
        return

    if amount not in (MIN_WITHDRAW, MAX_WITHDRAW):
        return await call.answer("Noto‘g‘ri miqdor.", show_alert=True)

    await create_withdrawal(call, amount)


@dp.callback_query(F.data.startswith("wd_ok_"))
async def withdrawal_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    request_id = int(call.data.split("_")[2])

    async with aiosqlite.connect(DB_PATH) as con:
        cur = await con.execute(
            "UPDATE withdrawals SET status='approved' "
            "WHERE id=? AND status='pending'",
            (request_id,)
        )
        await con.commit()
        changed = cur.rowcount

    if not changed:
        return await call.answer("Bu so‘rov oldin ko‘rib chiqilgan.", show_alert=True)

    row = await fetchone(
        "SELECT user_id, amount FROM withdrawals WHERE id=?",
        (request_id,)
    )
    if row:
        try:
            await bot.send_message(
                row[0],
                f"✅ {row[1]} Stars yechish so‘rovingiz tasdiqlandi."
            )
        except Exception:
            pass

    await call.message.edit_text(f"✅ #{request_id} so‘rov tasdiqlandi.")
    await call.answer("Tasdiqlandi.")


@dp.callback_query(F.data.startswith("wd_no_"))
async def withdrawal_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    request_id = int(call.data.split("_")[2])

    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("BEGIN IMMEDIATE")
        cur = await con.execute(
            "SELECT user_id, amount FROM withdrawals "
            "WHERE id=? AND status='pending'",
            (request_id,)
        )
        row = await cur.fetchone()

        if not row:
            await con.rollback()
            return await call.answer("So‘rov oldin ko‘rib chiqilgan.", show_alert=True)

        user_id, amount = row
        await con.execute(
            "UPDATE withdrawals SET status='rejected' WHERE id=?",
            (request_id,)
        )
        await con.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (amount, user_id)
        )
        await con.execute(
            "INSERT INTO transactions(user_id, amount, reason, created) "
            "VALUES(?,?,?,?)",
            (user_id, amount, "Rad etilgan so‘rov qaytarildi", datetime.now().isoformat())
        )
        await con.commit()

    try:
        await bot.send_message(
            user_id,
            f"❌ {amount} Stars yechish so‘rovingiz rad etildi.\n"
            "Mablag‘ balansingizga qaytarildi."
        )
    except Exception:
        pass

    await call.message.edit_text(f"❌ #{request_id} so‘rov rad etildi. Mablag‘ qaytarildi.")
    await call.answer("Rad etildi.")


@dp.callback_query(F.data == "promo")
async def promo_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserState.waiting_promo)
    await call.message.answer("🎁 Promo-kodni yuboring:")
    await call.answer()


@dp.message(UserState.waiting_promo)
async def promo_enter(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    promo = await fetchone(
        "SELECT reward, max_uses, used_count, expires FROM promos WHERE code=?",
        (code,)
    )

    if not promo:
        await message.answer("❌ Bunday promo-kod topilmadi.")
        await state.clear()
        return

    reward, max_uses, used_count, expires = promo

    if used_count >= max_uses:
        await message.answer("❌ Promo-kod ishlatish limiti tugagan.")
        await state.clear()
        return

    if expires and datetime.now() > datetime.fromisoformat(expires):
        await message.answer("❌ Promo-kod muddati tugagan.")
        await state.clear()
        return

    used = await fetchone(
        "SELECT 1 FROM promo_users WHERE code=? AND user_id=?",
        (code, message.from_user.id)
    )
    if used:
        await message.answer("❌ Bu promo-kodni oldin ishlatgansiz.")
        await state.clear()
        return

    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("BEGIN IMMEDIATE")
        cur = await con.execute(
            "SELECT used_count, max_uses FROM promos WHERE code=?",
            (code,)
        )
        latest = await cur.fetchone()

        if not latest or latest[0] >= latest[1]:
            await con.rollback()
            await message.answer("❌ Promo-kod limiti tugagan.")
            await state.clear()
            return

        await con.execute(
            "INSERT INTO promo_users(code, user_id) VALUES(?,?)",
            (code, message.from_user.id)
        )
        await con.execute(
            "UPDATE promos SET used_count=used_count+1 WHERE code=?",
            (code,)
        )
        await con.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (reward, message.from_user.id)
        )
        await con.execute(
            "INSERT INTO transactions(user_id, amount, reason, created) "
            "VALUES(?,?,?,?)",
            (message.from_user.id, reward, f"Promo: {code}", datetime.now().isoformat())
        )
        await con.commit()

    await message.answer(f"🎉 Promo qabul qilindi!\n⭐ +{reward} Stars")
    await state.clear()


@dp.callback_query(F.data == "daily")
async def daily_bonus(call: CallbackQuery):
    today = datetime.now().date().isoformat()
    row = await fetchone(
        "SELECT last_claim FROM daily_claims WHERE user_id=?",
        (call.from_user.id,)
    )

    if row and row[0] == today:
        return await call.answer("Bugungi bonusni olib bo‘lgansiz.", show_alert=True)

    reward = 1

    async with aiosqlite.connect(DB_PATH) as con:
        await con.execute("BEGIN IMMEDIATE")
        cur = await con.execute(
            "SELECT last_claim FROM daily_claims WHERE user_id=?",
            (call.from_user.id,)
        )
        latest = await cur.fetchone()

        if latest and latest[0] == today:
            await con.rollback()
            return await call.answer("Bugungi bonusni olib bo‘lgansiz.", show_alert=True)

        await con.execute(
            "INSERT INTO daily_claims(user_id, last_claim) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_claim=excluded.last_claim",
            (call.from_user.id, today)
        )
        await con.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (reward, call.from_user.id)
        )
        await con.execute(
            "INSERT INTO transactions(user_id, amount, reason, created) "
            "VALUES(?,?,?,?)",
            (call.from_user.id, reward, "Kunlik bonus", datetime.now().isoformat())
        )
        await con.commit()

    await call.answer(f"🎁 +{reward} Stars olindi!", show_alert=True)


@dp.callback_query(F.data == "tasks")
async def tasks_list(call: CallbackQuery):
    rows = await fetchall(
        "SELECT id, title, link, reward FROM tasks WHERE active=1 ORDER BY id DESC"
    )

    if not rows:
        return await safe_edit(
            call, "📋 Hozircha topshiriqlar mavjud emas.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]
            ])
        )

    text = "📋 TOPSHIRIQLAR\n\n"
    buttons = []

    for task_id, title, link, reward in rows:
        text += f"• {title} — {reward} ⭐\n"
        buttons.append([
            InlineKeyboardButton(text=f"🔗 {title}", url=link)
        ])
        buttons.append([
            InlineKeyboardButton(
                text=f"📨 Bajardim: {title}",
                callback_data=f"task_claim_{task_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")
    ])

    await safe_edit(
        call, text,
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("task_claim_"))
async def task_claim(call: CallbackQuery):
    task_id = int(call.data.split("_")[2])
    task = await fetchone(
        "SELECT title, reward FROM tasks WHERE id=? AND active=1",
        (task_id,)
    )

    if not task:
        return await call.answer("Topshiriq topilmadi.", show_alert=True)

    exists = await fetchone(
        "SELECT status FROM task_claims WHERE task_id=? AND user_id=?",
        (task_id, call.from_user.id)
    )

    if exists:
        return await call.answer("So‘rovingiz oldin yuborilgan.", show_alert=True)

    await execute(
        "INSERT INTO task_claims(task_id, user_id) VALUES(?,?)",
        (task_id, call.from_user.id)
    )

    for admin in ADMINS:
        try:
            await bot.send_message(
                admin,
                f"📋 TOPSHIRIQ TEKSHIRUVI\n\n"
                f"Foydalanuvchi: {call.from_user.id}\n"
                f"Topshiriq: {task[0]}\n"
                f"Mukofot: {task[1]} Stars\n"
                f"So‘rov ID: {task_id}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Tasdiqlash",
                            callback_data=f"task_ok_{task_id}_{call.from_user.id}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Rad etish",
                            callback_data=f"task_no_{task_id}_{call.from_user.id}"
                        )
                    ]
                ])
            )
        except Exception:
            pass

    await call.answer("Tekshirish uchun adminga yuborildi.", show_alert=True)


@dp.callback_query(F.data.startswith("task_ok_"))
async def task_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    _, _, task_id, user_id = call.data.split("_")
    task_id, user_id = int(task_id), int(user_id)

    task = await fetchone(
        "SELECT reward FROM tasks WHERE id=?", (task_id,)
    )
    claim = await fetchone(
        "SELECT status FROM task_claims WHERE task_id=? AND user_id=?",
        (task_id, user_id)
    )

    if not task or not claim or claim[0] != "pending":
        return await call.answer("So‘rov oldin ko‘rib chiqilgan.", show_alert=True)

    await execute(
        "UPDATE task_claims SET status='approved' WHERE task_id=? AND user_id=?",
        (task_id, user_id)
    )
    await change_balance(user_id, task[0], "Topshiriq mukofoti")

    try:
        await bot.send_message(user_id, f"✅ Topshiriq tasdiqlandi! +{task[0]} Stars.")
    except Exception:
        pass

    await call.message.edit_text("✅ Topshiriq tasdiqlandi.")
    await call.answer()


@dp.callback_query(F.data.startswith("task_no_"))
async def task_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    _, _, task_id, user_id = call.data.split("_")
    task_id, user_id = int(task_id), int(user_id)

    await execute(
        "UPDATE task_claims SET status='rejected' "
        "WHERE task_id=? AND user_id=? AND status='pending'",
        (task_id, user_id)
    )

    try:
        await bot.send_message(user_id, "❌ Topshiriq so‘rovingiz rad etildi.")
    except Exception:
        pass

    await call.message.edit_text("❌ Topshiriq rad etildi.")
    await call.answer()


@dp.callback_query(F.data == "ranking")
async def ranking(call: CallbackQuery):
    rows = await fetchall("""
        SELECT u.user_id, u.full_name, COUNT(r.user_id) AS refs
        FROM users AS u
        JOIN users AS r ON r.referrer_id=u.user_id
        GROUP BY u.user_id, u.full_name
        ORDER BY refs DESC
        LIMIT 10
    """)

    text = "🏆 REFERAL REYTINGI\n\n"
    if not rows:
        text += "Hozircha reyting bo‘sh."
    else:
        for i, row in enumerate(rows, 1):
            text += f"{i}. {row[1]} — {row[2]} ta\n"

    await safe_edit(
        call, text,
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]
        ])
    )


@dp.callback_query(F.data == "support")
async def support_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserState.waiting_support)
    await call.message.answer("📨 Xabaringizni yuboring. Matn, rasm yoki video yuborishingiz mumkin.")
    await call.answer()


@dp.message(UserState.waiting_support)
async def support_receive(message: Message, state: FSMContext):
    content = message.text or message.caption or "[Media xabar]"
    await execute(
        "INSERT INTO support(user_id, message, created) VALUES(?,?,?)",
        (message.from_user.id, content, datetime.now().isoformat())
    )
    support_id = await fetchone(
        "SELECT id FROM support WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (message.from_user.id,)
    )

    for admin in ADMINS:
        try:
            await bot.send_message(
                admin,
                f"📨 YANGI MUROJAAT\n"
                f"ID: {support_id[0]}\n"
                f"Foydalanuvchi: {message.from_user.id}\n\n"
                f"{content}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✉️ Javob berish",
                        callback_data=f"reply_{message.from_user.id}"
                    )]
                ])
            )
            if message.photo:
                await bot.send_photo(admin, message.photo[-1].file_id)
            elif message.video:
                await bot.send_video(admin, message.video.file_id)
        except Exception:
            pass

    await message.answer("✅ Murojaatingiz adminga yuborildi.")
    await state.clear()


@dp.callback_query(F.data.startswith("reply_"))
async def support_reply_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    user_id = int(call.data.split("_")[1])
    await state.update_data(reply_user_id=user_id)
    await state.set_state(AdminState.waiting_reply)
    await call.message.answer(f"{user_id} foydalanuvchiga javob matnini yuboring:")
    await call.answer()


@dp.message(AdminState.waiting_reply)
async def support_reply_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    user_id = data.get("reply_user_id")

    try:
        await bot.send_message(
            user_id,
            "📨 ADMIN JAVOBI\n\n" + (message.text or message.caption or "Admin sizga xabar yubordi.")
        )
        if message.photo:
            await bot.send_photo(user_id, message.photo[-1].file_id)
        elif message.video:
            await bot.send_video(user_id, message.video.file_id)

        await message.answer("✅ Javob yuborildi.")
    except Exception:
        await message.answer("❌ Foydalanuvchiga xabar yuborilmadi.")

    await state.clear()


@dp.callback_query(F.data == "news")
async def news_list(call: CallbackQuery):
    rows = await fetchall("SELECT text, created FROM news ORDER BY id DESC LIMIT 10")

    text = "📰 YANGILIKLAR\n\n"
    if not rows:
        text += "Hozircha yangilik yo‘q."
    else:
        for item, created in rows:
            text += f"• {item}\n\n"

    await safe_edit(
        call, text,
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]
        ])
    )


@dp.callback_query(F.data == "orders")
async def orders_list(call: CallbackQuery):
    rows = await fetchall(
        "SELECT description, created FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (call.from_user.id,)
    )

    text = "📦 BUYURTMALARIM\n\n"
    if not rows:
        text += "Hozircha buyurtmalaringiz yo‘q."
    else:
        for description, created in rows:
            text += f"• {description}\n"

    await safe_edit(
        call, text,
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]
        ])
    )


@dp.callback_query(F.data == "guide")
async def guide(call: CallbackQuery):
    await safe_edit(
        call,
        "📖 QO‘LLANMA\n\n"
        "1. Referal bo‘limidan havolangizni oling.\n"
        "2. Do‘stlaringizni taklif qiling.\n"
        "3. Topshiriqlarni bajaring.\n"
        "4. Promo-kodlardan foydalaning.\n"
        "5. Balans yetarli bo‘lsa Stars yechish so‘rovini yuboring.\n\n"
        "Eslatma: botdagi Stars balansi ichki hisob birligidir.",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]
        ])
    )


@dp.callback_query(F.data == "settings")
async def settings(call: CallbackQuery):
    await safe_edit(
        call,
        "⚙️ SOZLAMALAR\n\n"
        f"Telegram ID: {call.from_user.id}\n"
        f"Username: @{call.from_user.username or 'yo‘q'}",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_home")]
        ])
    )


# =========================================================
# ADMIN PANELI
# =========================================================

@dp.callback_query(F.data == "a_stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    users = await fetchone("SELECT COUNT(*) FROM users")
    blocked = await fetchone("SELECT COUNT(*) FROM users WHERE blocked=1")
    channels = await fetchone("SELECT COUNT(*) FROM channels")
    pending = await fetchone("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    total_balance = await fetchone("SELECT COALESCE(SUM(balance),0) FROM users")

    await safe_edit(
        call,
        "📊 BOT STATISTIKASI\n\n"
        f"👥 Foydalanuvchilar: {users[0]}\n"
        f"🚫 Bloklanganlar: {blocked[0]}\n"
        f"📣 Kanallar: {channels[0]}\n"
        f"💸 Kutilayotgan yechishlar: {pending[0]}\n"
        f"⭐ Umumiy balans: {total_balance[0]}",
        admin_menu(call.from_user.id)
    )


@dp.callback_query(F.data == "a_users")
async def admin_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    rows = await fetchall(
        "SELECT user_id, full_name, username, balance, blocked "
        "FROM users ORDER BY joined DESC LIMIT 20"
    )

    text = "👥 OXIRGI FOYDALANUVCHILAR\n\n"
    for row in rows:
        text += (
            f"ID: {row[0]}\n"
            f"Ism: {row[1]}\n"
            f"Username: @{row[2] or 'yo‘q'}\n"
            f"Balans: {row[3]} ⭐\n"
            f"Holat: {'Bloklangan' if row[4] else 'Faol'}\n\n"
        )

    await safe_edit(
        call, text or "Foydalanuvchilar yo‘q.",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Admin panel", callback_data="admin_home")]
        ])
    )


@dp.callback_query(F.data == "a_balance")
async def admin_balance_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    await state.set_state(AdminState.waiting_balance)
    await call.message.answer(
        "Balansni o‘zgartirish uchun quyidagi shaklda yuboring:\n\n"
        "<code>USER_ID MIQDOR</code>\n"
        "Masalan: <code>123456789 10</code>\n"
        "Manfiy miqdor balansdan ayiradi.",
        parse_mode="HTML"
    )
    await call.answer()


@dp.message(AdminState.waiting_balance)
async def admin_balance_change(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        user_id, amount = map(int, message.text.split())
        if not await user_exists(user_id):
            await message.answer("❌ Foydalanuvchi topilmadi.")
        elif not await change_balance(user_id, amount, "Admin tomonidan o‘zgartirildi"):
            await message.answer("❌ Balans manfiy bo‘lib qolishi mumkin emas.")
        else:
            await message.answer("✅ Balans yangilandi.")
            try:
                await bot.send_message(
                    user_id,
                    f"💰 Balansingiz admin tomonidan o‘zgartirildi: {amount:+} Stars"
                )
            except Exception:
                pass
    except Exception:
        await message.answer("❌ Format xato. Masalan: 123456789 10")

    await state.clear()


@dp.callback_query(F.data == "a_channels")
async def admin_channels(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    rows = await fetchall("SELECT id, chat_id, invite_link FROM channels")
    text = "📣 KANALLAR\n\n"
    for row in rows:
        text += f"ID: {row[0]} | {row[1]}\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kanal qo‘shish", callback_data="a_add_channel")],
        [InlineKeyboardButton(text="➖ Kanal o‘chirish", callback_data="a_del_channel")],
        [InlineKeyboardButton(text="⬅️ Admin panel", callback_data="admin_home")]
    ])

    await safe_edit(call, text, keyboard)


@dp.callback_query(F.data == "a_add_channel")
async def add_channel_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    await state.set_state(AdminState.waiting_channel)
    await call.message.answer(
        "Kanal ma'lumotini yuboring:\n\n"
        "<code>@kanal_username</code>\n"
        "yoki\n"
        "<code>-1001234567890 https://t.me/+invite</code>\n\n"
        "Bot kanalga admin qilingan bo‘lishi kerak.",
        parse_mode="HTML"
    )
    await call.answer()


@dp.message(AdminState.waiting_channel)
async def add_channel_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    parts = message.text.strip().split(maxsplit=1)
    chat_id = parts[0]
    invite = parts[1] if len(parts) > 1 else ""

    try:
        chat = await bot.get_chat(chat_id)
        await bot.get_chat_member(chat.id, bot.id)

        await execute(
            "INSERT OR IGNORE INTO channels(chat_id, invite_link) VALUES(?,?)",
            (chat_id, invite)
        )
        await message.answer("✅ Kanal qo‘shildi.")
    except Exception as e:
        log.warning("Channel add error: %s", e)
        await message.answer(
            "❌ Kanalni tekshirib bo‘lmadi. Kanal ID/username to‘g‘ri ekanini "
            "va bot admin ekanini tekshiring."
        )

    await state.clear()


@dp.callback_query(F.data == "a_del_channel")
async def delete_channel_start(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    rows = await fetchall("SELECT id, chat_id FROM channels")
    buttons = [
        [InlineKeyboardButton(
            text=f"🗑 {chat_id}",
            callback_data=f"del_channel_{channel_id}"
        )]
        for channel_id, chat_id in rows
    ]
    buttons.append([
        InlineKeyboardButton(text="⬅️ Orqaga", callback_data="a_channels")
    ])

    await safe_edit(
        call, "O‘chirmoqchi bo‘lgan kanalni tanlang:",
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("del_channel_"))
async def delete_channel(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    channel_id = int(call.data.split("_")[-1])
    await execute("DELETE FROM channels WHERE id=?", (channel_id,))
    await call.answer("Kanal o‘chirildi.")
    await admin_channels(call)


@dp.callback_query(F.data == "a_broadcast")
async def broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    await state.set_state(AdminState.waiting_broadcast)
    await call.message.answer(
        "📢 Tarqatiladigan xabarni yuboring.\n"
        "Matn, rasm, video yoki boshqa Telegram xabarini yuborishingiz mumkin.\n"
        "Xabar foydalanuvchilarga va qo‘shilgan kanallarga nusxalanadi."
    )
    await call.answer()


@dp.message(AdminState.waiting_broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    users = await fetchall("SELECT user_id FROM users WHERE blocked=0")
    channels = await fetchall("SELECT chat_id FROM channels")

    sent = 0
    failed = 0

    await message.answer(
        f"⏳ Tarqatish boshlandi.\n"
        f"Foydalanuvchilar: {len(users)}\nKanallar: {len(channels)}"
    )

    for (user_id,) in users:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1

    for (chat_id,) in channels:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            sent += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    await message.answer(
        f"✅ Tarqatish yakunlandi.\n"
        f"Yuborildi: {sent}\n"
        f"Xatolik: {failed}"
    )
    await state.clear()


@dp.callback_query(F.data == "a_promo")
async def admin_promo_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    await state.set_state(AdminState.waiting_promo_create)
    await call.message.answer(
        "Promo yaratish formati:\n\n"
        "<code>KOD MUKOFOT LIMIT</code>\n"
        "Masalan: <code>START10 10 100</code>\n\n"
        "Promo muddati hozircha cheklanmaydi.",
        parse_mode="HTML"
    )
    await call.answer()


@dp.message(AdminState.waiting_promo_create)
async def admin_promo_create(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        code, reward, limit = message.text.upper().split()
        reward, limit = int(reward), int(limit)

        if not re.fullmatch(r"[A-Z0-9_-]{3,30}", code):
            raise ValueError()

        if reward <= 0 or limit <= 0:
            raise ValueError()

        await execute(
            "INSERT INTO promos(code, reward, max_uses) VALUES(?,?,?)",
            (code, reward, limit)
        )
        await message.answer(
            f"✅ Promo yaratildi!\n"
            f"Kod: {code}\nMukofot: {reward} Stars\nLimit: {limit}"
        )
    except aiosqlite.IntegrityError:
        await message.answer("❌ Bu promo-kod oldin yaratilgan.")
    except Exception:
        await message.answer("❌ Format xato. Masalan: START10 10 100")

    await state.clear()


@dp.callback_query(F.data == "a_task")
async def admin_task_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    await state.set_state(AdminState.waiting_task)
    await call.message.answer(
        "Topshiriq formati:\n\n"
        "<code>NOMI | LINK | MUKOFOT</code>\n"
        "Masalan:\n"
        "<code>Kanalga obuna | https://t.me/example | 5</code>",
        parse_mode="HTML"
    )
    await call.answer()


@dp.message(AdminState.waiting_task)
async def admin_task_create(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        title, link, reward = [x.strip() for x in message.text.split("|")]
        reward = int(reward)

        if not link.startswith(("https://", "http://")) or reward <= 0:
            raise ValueError()

        await execute(
            "INSERT INTO tasks(title, link, reward) VALUES(?,?,?)",
            (title, link, reward)
        )
        await message.answer("✅ Topshiriq qo‘shildi.")
    except Exception:
        await message.answer(
            "❌ Format xato. Misol:\n"
            "Kanalga obuna | https://t.me/example | 5"
        )

    await state.clear()


@dp.callback_query(F.data == "a_news")
async def admin_news_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    await state.set_state(AdminState.waiting_news)
    await call.message.answer("📰 Yangilik matni yoki media xabarini yuboring:")
    await call.answer()


@dp.message(AdminState.waiting_news)
async def admin_news_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    content = message.text or message.caption or "[Media yangilik]"
    await execute(
        "INSERT INTO news(text, created) VALUES(?,?)",
        (content, datetime.now().isoformat())
    )

    users = await fetchall("SELECT user_id FROM users WHERE blocked=0")
    sent = 0

    for (user_id,) in users:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            sent += 1
        except Exception:
            pass

    await message.answer(f"✅ Yangilik saqlandi. {sent} foydalanuvchiga yuborildi.")
    await state.clear()


@dp.callback_query(F.data == "a_withdrawals")
async def admin_withdrawals(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    rows = await fetchall(
        "SELECT id, user_id, amount, created FROM withdrawals "
        "WHERE status='pending' ORDER BY id DESC LIMIT 20"
    )

    text = "💸 KUTILAYOTGAN SO‘ROVLAR\n\n"
    buttons = []

    for request_id, user_id, amount, created in rows:
        text += f"#{request_id} | {user_id} | {amount} Stars\n"
        buttons.append([
            InlineKeyboardButton(
                text=f"Ko‘rish #{request_id}",
                callback_data=f"wd_view_{request_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="⬅️ Admin panel", callback_data="admin_home")
    ])

    await safe_edit(
        call, text if rows else "Kutilayotgan so‘rovlar yo‘q.",
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("wd_view_"))
async def admin_withdraw_view(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    request_id = int(call.data.split("_")[-1])
    row = await fetchone(
        "SELECT user_id, amount, status FROM withdrawals WHERE id=?",
        (request_id,)
    )

    if not row:
        return await call.answer("So‘rov topilmadi.", show_alert=True)

    await safe_edit(
        call,
        f"💸 SO‘ROV #{request_id}\n\n"
        f"Foydalanuvchi: {row[0]}\n"
        f"Miqdor: {row[1]} Stars\n"
        f"Holat: {row[2]}",
        InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"wd_ok_{request_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"wd_no_{request_id}")
            ],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="a_withdrawals")]
        ])
    )


@dp.callback_query(F.data == "a_support")
async def admin_support_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    rows = await fetchall(
        "SELECT id, user_id, message FROM support ORDER BY id DESC LIMIT 15"
    )

    text = "📨 OXIRGI MUROJAATLAR\n\n"
    buttons = []

    for support_id, user_id, content in rows:
        text += f"#{support_id} | {user_id}: {content[:80]}\n"
        buttons.append([
            InlineKeyboardButton(
                text=f"Javob berish: {user_id}",
                callback_data=f"reply_{user_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="⬅️ Admin panel", callback_data="admin_home")
    ])

    await safe_edit(
        call, text if rows else "Murojaatlar mavjud emas.",
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data == "a_settings")
async def admin_settings(call: CallbackQuery):
    if not is_main_admin(call.from_user.id):
        return await call.answer("Faqat asosiy admin uchun.", show_alert=True)

    await safe_edit(
        call,
        "⚙️ ASOSIY ADMIN SOZLAMALARI\n\n"
        f"Referal mukofoti: {REFERRAL_REWARD} Stars\n"
        f"Asosiy admin: {ADMIN_ID_1}\n"
        f"Ikkinchi admin: {ADMIN_ID_2 or 'Belgilanmagan'}\n\n"
        "Referal miqdorini Render Environment dagi "
        "REFERRAL_REWARD orqali o‘zgartiring.",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Admin panel", callback_data="admin_home")]
        ])
    )


@dp.callback_query(F.data == "admin_home")
async def admin_home(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo‘q.", show_alert=True)

    await safe_edit(
        call, "🛠 ADMIN PANEL",
        admin_menu(call.from_user.id)
    )


# =========================================================
# BLOKLASH VA UMUMIY XATOLARNI USHLASH
# =========================================================

@dp.message()
async def fallback_message(message: Message):
    if not await user_exists(message.from_user.id):
        await register_user(message)

    if not await allowed_user(message.from_user.id, message):
        return

    await message.answer(
        "Menyudan kerakli bo‘limni tanlang:",
        reply_markup=main_menu()
    )


@dp.callback_query()
async def fallback_callback(call: CallbackQuery):
    await call.answer("Bu tugma mavjud emas yoki eskirgan.", show_alert=True)


# =========================================================
# RENDER HEALTH CHECK
# =========================================================

async def health(request):
    return web.Response(text="Bot is running", status=200)


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    log.info("Health server started on port %s", PORT)


# =========================================================
# ISHGA TUSHIRISH
# =========================================================

async def main():
    await init_db()

    await start_web_server()

    me = await bot.get_me()
    log.info("Bot started: @%s", me.username)

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
