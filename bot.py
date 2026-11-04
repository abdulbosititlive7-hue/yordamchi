import asyncio
import logging
import os
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager

import aiosqlite
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


# =========================================================
# 1. SOZLAMALAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo").strip()
ADMIN_ID_1 = int(os.getenv("ADMIN_ID_1", "5200398952"))
ADMIN_ID_2 = int(os.getenv("ADMIN_ID_2", "7676544759"))
DB_PATH = os.getenv("DB_PATH", "/var/data/bot.sqlite3")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN kiritilmagan!")

if ADMIN_ID_1 <= 0 or ADMIN_ID_2 <= 0:
    raise RuntimeError("Ikkala admin ID ham kiritilishi kerak!")

if ADMIN_ID_1 == ADMIN_ID_2:
    raise RuntimeError("Admin ID lar bir xil bo'lishi mumkin emas!")

ADMIN_IDS = {ADMIN_ID_1, ADMIN_ID_2}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("telegram-bot")


# =========================================================
# 2. BOT VA DISPATCHER
# =========================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())


# =========================================================
# 3. FSM HOLATLARI
# =========================================================

class PromoState(StatesGroup):
    enter = State()


class SupportState(StatesGroup):
    message = State()


class AdminState(StatesGroup):
    add_channel = State()
    add_promo_code = State()
    add_promo_amount = State()
    add_promo_limit = State()
    search_user = State()
    balance_user = State()
    balance_amount = State()
    broadcast = State()
    add_task_title = State()
    add_task_link = State()
    add_task_reward = State()
    add_news = State()
    reply_support = State()


# =========================================================
# 4. VAQT VA YORDAMCHI FUNKSIYALAR
# =========================================================

def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def today():
    return date.today().isoformat()


def is_admin(user_id: int):
    return user_id in ADMIN_IDS


def main_admin(user_id: int):
    return user_id == ADMIN_ID_1


def user_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👥 Referal"),
                KeyboardButton(text="💰 Mening hisobim")
            ],
            [
                KeyboardButton(text="⭐ Stars yechish"),
                KeyboardButton(text="📦 Buyurtmalarim")
            ],
            [
                KeyboardButton(text="🎁 Promokod"),
                KeyboardButton(text="📅 Kunlik bonus")
            ],
            [
                KeyboardButton(text="📋 Vazifalar"),
                KeyboardButton(text="🏆 Reyting")
            ],
            [
                KeyboardButton(text="💬 Adminga murojaat"),
                KeyboardButton(text="📰 Yangiliklar")
            ],
            [
                KeyboardButton(text="📖 Qo‘llanma"),
                KeyboardButton(text="⚙️ Sozlamalar")
            ]
        ],
        resize_keyboard=True
    )


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="a:stats"),
            InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="a:users")
        ],
        [
            InlineKeyboardButton(text="📦 Buyurtmalar", callback_data="a:orders"),
            InlineKeyboardButton(text="🎁 Promokodlar", callback_data="a:promos")
        ],
        [
            InlineKeyboardButton(text="📢 Kanallar", callback_data="a:channels"),
            InlineKeyboardButton(text="📣 Reklama", callback_data="a:broadcast")
        ],
        [
            InlineKeyboardButton(text="📋 Vazifalar", callback_data="a:tasks"),
            InlineKeyboardButton(text="💬 Murojaatlar", callback_data="a:support")
        ],
        [
            InlineKeyboardButton(text="📰 Yangilik joylash", callback_data="a:news"),
            InlineKeyboardButton(text="📈 Reyting", callback_data="a:rating")
        ],
        [
            InlineKeyboardButton(text="⚙️ Bonus sozlamalari", callback_data="a:settings")
        ],
        [
            InlineKeyboardButton(text="❌ Yopish", callback_data="a:close")
        ]
    ])


def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")]
    ])


def subscription_keyboard(channels):
    rows = []
    for channel in channels:
        link = channel["invite_link"]
        if link:
            rows.append([
                InlineKeyboardButton(
                    text=f"➕ {channel['title']}",
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


async def db_execute(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(query, params)
        await db.commit()


async def db_fetchone(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, params)
        row = await cur.fetchone()
        return dict(row) if row else None


async def db_fetchall(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, params)
        return [dict(x) for x in await cur.fetchall()]


# =========================================================
# 5. DATABASE VA MIGRATSIYA
# =========================================================

async def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            username TEXT,
            balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
            total_earned INTEGER NOT NULL DEFAULT 0,
            total_spent INTEGER NOT NULL DEFAULT 0,
            referrer_id INTEGER,
            is_banned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_active TEXT NOT NULL,
            last_daily TEXT,
            daily_streak INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(referrer_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS channels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            invite_link TEXT,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL CHECK(amount IN (15,25)),
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            decided_at TEXT,
            decided_by INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            kind TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS promo_codes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE COLLATE NOCASE NOT NULL,
            amount INTEGER NOT NULL,
            usage_limit INTEGER NOT NULL DEFAULT 0,
            used_count INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS promo_uses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promo_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            used_at TEXT NOT NULL,
            UNIQUE(promo_id,user_id)
        );

        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT,
            reward INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS task_completions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            UNIQUE(task_id,user_id)
        );

        CREATE TABLE IF NOT EXISTS support_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            admin_id INTEGER,
            message_id INTEGER,
            text TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS news(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS admin_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS broadcasts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            target TEXT NOT NULL,
            success INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
        """)

        defaults = {
            "referral_reward": "2",
            "daily_bonus": "1",
            "weekly_bonus": "5",
            "daily_enabled": "1",
            "weekly_enabled": "1"
        }

        for key, value in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (key, value)
            )

        await db.commit()


async def get_setting(key, default="0"):
    row = await db_fetchone(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    )
    return row["value"] if row else default


async def set_setting(key, value):
    await db_execute("""
        INSERT INTO settings(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, str(value)))


# =========================================================
# 6. BALANSNI XAVFSIZ O'ZGARTIRISH
# =========================================================

async def change_balance(user_id, amount, kind, description=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")

        cur = await db.execute(
            "SELECT balance FROM users WHERE user_id=?",
            (user_id,)
        )
        row = await cur.fetchone()

        if not row or row[0] + amount < 0:
            await db.rollback()
            return False

        await db.execute("""
            UPDATE users
            SET balance=balance+?,
                total_earned=total_earned+?,
                total_spent=total_spent+?
            WHERE user_id=?
        """, (
            amount,
            max(amount, 0),
            max(-amount, 0),
            user_id
        ))

        await db.execute("""
            INSERT INTO transactions(user_id,amount,kind,description,created_at)
            VALUES(?,?,?,?,?)
        """, (user_id, amount, kind, description, now()))

        await db.commit()
        return True


# =========================================================
# 7. OBUNANI TEKSHIRISH
# =========================================================

async def get_channels():
    return await db_fetchall(
        "SELECT * FROM channels WHERE active=1"
    )


async def check_subscription(user_id):
    channels = await get_channels()

    for channel in channels:
        try:
            member = await bot.get_chat_member(
                chat_id=channel["chat_id"],
                user_id=user_id
            )
            if member.status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.KICKED
            ):
                return False
        except TelegramAPIError:
            log.exception("Kanal obunasini tekshirishda xato")
            return False

    return True


async def subscription_required(message: Message):
    channels = await get_channels()
    if not channels:
        return True

    if await check_subscription(message.from_user.id):
        return True

    await message.answer(
        "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
        reply_markup=subscription_keyboard(channels)
    )
    return False


# =========================================================
# 8. FOYDALANUVCHINI RO'YXATDAN O'TKAZISH
# =========================================================

async def register_user(user, referrer_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("BEGIN IMMEDIATE")

        cur = await db.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (user.id,)
        )
        existing = await cur.fetchone()

        if existing:
            await db.execute("""
                UPDATE users SET full_name=?, username=?, last_active=?
                WHERE user_id=?
            """, (
                user.full_name,
                user.username,
                now(),
                user.id
            ))
            await db.commit()
            return False

        if referrer_id == user.id:
            referrer_id = None

        if referrer_id:
            cur = await db.execute(
                "SELECT user_id FROM users WHERE user_id=?",
                (referrer_id,)
            )
            if not await cur.fetchone():
                referrer_id = None

        await db.execute("""
            INSERT INTO users(
                user_id,full_name,username,referrer_id,created_at,last_active
            ) VALUES(?,?,?,?,?,?)
        """, (
            user.id,
            user.full_name,
            user.username,
            referrer_id,
            now(),
            now()
        ))

        if referrer_id:
            cur = await db.execute(
                "SELECT value FROM settings WHERE key='referral_reward'"
            )
            reward_row = await cur.fetchone()
            reward = int(reward_row[0]) if reward_row else 2

            await db.execute("""
                UPDATE users
                SET balance=balance+?,
                    total_earned=total_earned+?
                WHERE user_id=?
            """, (reward, reward, referrer_id))

            await db.execute("""
                INSERT INTO transactions(user_id,amount,kind,description,created_at)
                VALUES(?,?,?,?,?)
            """, (
                referrer_id,
                reward,
                "referral",
                f"Referal: {user.id}",
                now()
            ))

        await db.commit()
        return True


# =========================================================
# 9. START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    args = message.text.split(maxsplit=1)
    referrer_id = None

    if len(args) > 1:
        payload = args[1].strip()
        if payload.isdigit():
            referrer_id = int(payload)

    await register_user(message.from_user, referrer_id)

    user = await db_fetchone(
        "SELECT * FROM users WHERE user_id=?",
        (message.from_user.id,)
    )

    if user and user["is_banned"]:
        await message.answer("⛔ Siz botdan foydalanish huquqidan mahrum qilingansiz.")
        return

    if not await subscription_required(message):
        return

    await message.answer(
        f"👋 Assalomu alaykum, <b>{message.from_user.full_name}</b>!\n\n"
        "Botimizga xush kelibsiz. Kerakli bo‘limni tanlang:",
        reply_markup=user_keyboard()
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.answer(
            "✅ Obuna tasdiqlandi!",
            reply_markup=user_keyboard()
        )
    else:
        await call.answer(
            "Hali barcha kanallarga obuna bo‘lmagansiz.",
            show_alert=True
        )


# =========================================================
# 10. FOYDALANUVCHI PANELI
# =========================================================

@dp.message(F.text == "👥 Referal")
async def referral_handler(message: Message):
    if not await subscription_required(message):
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"

    user = await db_fetchone(
        "SELECT COUNT(*) AS n FROM users WHERE referrer_id=?",
        (message.from_user.id,)
    )
    reward = await get_setting("referral_reward", "2")

    await message.answer(
        "👥 <b>Referal bo‘limi</b>\n\n"
        f"🔗 Sizning havolangiz:\n<code>{link}</code>\n\n"
        f"👤 Taklif qilganlaringiz: {user['n']}\n"
        f"⭐ Har bir haqiqiy referal uchun: {reward} Stars"
    )


@dp.message(F.text == "💰 Mening hisobim")
async def balance_handler(message: Message):
    if not await subscription_required(message):
        return

    user = await db_fetchone(
        "SELECT * FROM users WHERE user_id=?",
        (message.from_user.id,)
    )

    await message.answer(
        "💰 <b>Sizning hisobingiz</b>\n\n"
        f"⭐ Joriy balans: <b>{user['balance']}</b>\n"
        f"📈 Jami daromad: {user['total_earned']}\n"
        f"📉 Sarflangan: {user['total_spent']}\n"
    )

    rows = await db_fetchall("""
        SELECT amount,kind,description,created_at
        FROM transactions WHERE user_id=?
        ORDER BY id DESC LIMIT 10
    """, (message.from_user.id,))

    if rows:
        text = "\n<b>Oxirgi tranzaksiyalar:</b>\n"
        for row in rows:
            sign = "+" if row["amount"] > 0 else ""
            text += (
                f"\n{sign}{row['amount']} ⭐ — {row['kind']}"
                f"\n<code>{row['created_at']}</code>\n"
            )
        await message.answer(text)


# =========================================================
# 11. KUNLIK BONUS
# =========================================================

@dp.message(F.text == "📅 Kunlik bonus")
async def daily_bonus(message: Message):
    if not await subscription_required(message):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")

        cur = await db.execute(
            "SELECT last_daily,daily_streak FROM users WHERE user_id=?",
            (message.from_user.id,)
        )
        row = await cur.fetchone()

        if row[0] == today():
            await db.rollback()
            await message.answer("⏳ Bugungi bonusni olib bo‘lgansiz.")
            return

        streak = row[1] + 1 if row[0] == (date.today() - timedelta(days=1)).isoformat() else 1
        reward = int(await get_setting("daily_bonus", "1"))
        enabled = await get_setting("daily_enabled", "1")

        if enabled != "1":
            await db.rollback()
            await message.answer("Kunlik bonus vaqtincha o‘chirilgan.")
            return

        await db.execute("""
            UPDATE users
            SET balance=balance+?,
                total_earned=total_earned+?,
                last_daily=?,
                daily_streak=?
            WHERE user_id=?
        """, (reward, reward, today(), streak, message.from_user.id))

        await db.execute("""
            INSERT INTO transactions(user_id,amount,kind,description,created_at)
            VALUES(?,?,?,?,?)
        """, (
            message.from_user.id,
            reward,
            "daily_bonus",
            f"Ketma-ket kun: {streak}",
            now()
        ))

        await db.commit()

    await message.answer(
        f"🎉 Siz {reward} Stars bonus oldingiz!\n"
        f"🔥 Ketma-ket kunlar: {streak}"
    )


# =========================================================
# 12. STARS YECHISH
# =========================================================

@dp.message(F.text == "⭐ Stars yechish")
async def withdraw_menu(message: Message):
    if not await subscription_required(message):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="15 ⭐", callback_data="withdraw:15"),
            InlineKeyboardButton(text="25 ⭐", callback_data="withdraw:25")
        ],
        [
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")
        ]
    ])

    await message.answer(
        "⭐ Yechmoqchi bo‘lgan miqdoringizni tanlang:",
        reply_markup=kb
    )


@dp.callback_query(F.data.startswith("withdraw:"))
async def withdraw_create(call: CallbackQuery):
    amount = int(call.data.split(":")[1])

    if amount not in (15, 25):
        await call.answer("Noto‘g‘ri miqdor.", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")

        cur = await db.execute(
            "SELECT balance FROM users WHERE user_id=?",
            (call.from_user.id,)
        )
        row = await cur.fetchone()

        if not row or row[0] < amount:
            await db.rollback()
            await call.answer("Balansingiz yetarli emas!", show_alert=True)
            return

        await db.execute(
            "UPDATE users SET balance=balance-?,total_spent=total_spent+? WHERE user_id=?",
            (amount, amount, call.from_user.id)
        )

        cur = await db.execute("""
            INSERT INTO orders(user_id,amount,status,created_at)
            VALUES(?,?,'pending',?)
        """, (call.from_user.id, amount, now()))

        order_id = cur.lastrowid

        await db.execute("""
            INSERT INTO transactions(user_id,amount,kind,description,created_at)
            VALUES(?,?,?,?,?)
        """, (
            call.from_user.id,
            -amount,
            "withdraw",
            f"Buyurtma #{order_id}",
            now()
        ))

        await db.commit()

    user = call.from_user
    username = f"@{user.username}" if user.username else "Yo‘q"

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"order:approve:{order_id}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"order:reject:{order_id}"
            )
        ]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "📦 <b>Yangi buyurtma!</b>\n\n"
                f"🆔 Buyurtma: #{order_id}\n"
                f"👤 Ism: {user.full_name}\n"
                f"🔗 Username: {username}\n"
                f"🆔 Telegram ID: <code>{user.id}</code>\n"
                f"⭐ Miqdor: {amount}\n"
                f"🕒 Vaqt: {now()}",
                reply_markup=admin_kb
            )
        except TelegramAPIError:
            log.exception("Adminga buyurtma yuborilmadi: %s", admin_id)

    await call.message.answer(
        f"✅ #{order_id} buyurtmangiz qabul qilindi.\n"
        "Holati: ⏳ Kutilmoqda."
    )
    await call.answer()


@dp.callback_query(F.data.startswith("order:"))
async def order_decision(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Sizda ruxsat yo‘q.", show_alert=True)
        return

    _, action, order_id_text = call.data.split(":")
    order_id = int(order_id_text)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")

        cur = await db.execute(
            "SELECT user_id,amount,status FROM orders WHERE id=?",
            (order_id,)
        )
        order = await cur.fetchone()

        if not order or order[2] != "pending":
            await db.rollback()
            await call.answer("Buyurtma allaqachon ko‘rib chiqilgan.", show_alert=True)
            return

        user_id, amount, status = order

        if action == "approve":
            new_status = "approved"
        elif action == "reject":
            new_status = "rejected"
            await db.execute("""
                UPDATE users
                SET balance=balance+?,
                    total_earned=total_earned+?
                WHERE user_id=?
            """, (amount, amount, user_id))

            await db.execute("""
                INSERT INTO transactions(user_id,amount,kind,description,created_at)
                VALUES(?,?,?,?,?)
            """, (
                user_id,
                amount,
                "refund",
                f"Buyurtma #{order_id} qaytarildi",
                now()
            ))
        else:
            await db.rollback()
            return

        await db.execute("""
            UPDATE orders
            SET status=?,decided_at=?,decided_by=?
            WHERE id=? AND status='pending'
        """, (new_status, now(), call.from_user.id, order_id))

        await db.execute("""
            INSERT INTO admin_logs(admin_id,action,created_at)
            VALUES(?,?,?)
        """, (
            call.from_user.id,
            f"Order {order_id}: {new_status}",
            now()
        ))

        await db.commit()

    await bot.send_message(
        user_id,
        f"📦 #{order_id} buyurtmangiz holati: "
        f"{'✅ Tasdiqlandi' if action == 'approve' else '❌ Rad etildi'}"
        + ("\nStars balansingizga qaytarildi." if action == "reject" else "")
    )

    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Qaror saqlandi.")


@dp.message(F.text == "📦 Buyurtmalarim")
async def my_orders(message: Message):
    rows = await db_fetchall("""
        SELECT id,amount,status,created_at
        FROM orders WHERE user_id=?
        ORDER BY id DESC LIMIT 20
    """, (message.from_user.id,))

    if not rows:
        await message.answer("Sizda hali buyurtmalar mavjud emas.")
        return

    text = "📦 <b>Buyurtmalaringiz</b>\n"
    for row in rows:
        text += (
            f"\n🆔 #{row['id']} — {row['amount']} ⭐"
            f"\nHolati: {row['status']}"
            f"\nVaqti: {row['created_at']}\n"
        )

    await message.answer(text)


# =========================================================
# 13. PROMOKOD
# =========================================================

@dp.message(F.text == "🎁 Promokod")
async def promo_start(message: Message, state: FSMContext):
    await state.set_state(PromoState.enter)
    await message.answer(
        "🎁 Promokodni yuboring:",
        reply_markup=cancel_keyboard()
    )


@dp.message(PromoState.enter)
async def promo_use(message: Message, state: FSMContext):
    code = message.text.strip().upper()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")

        cur = await db.execute("""
            SELECT id,amount,usage_limit,used_count,expires_at,active
            FROM promo_codes WHERE code=? COLLATE NOCASE
        """, (code,))
        promo = await cur.fetchone()

        if not promo or promo[5] != 1:
            await db.rollback()
            await message.answer("❌ Promokod topilmadi yoki faol emas.")
            return

        promo_id, amount, limit_count, used_count, expires_at, active = promo

        if limit_count > 0 and used_count >= limit_count:
            await db.rollback()
            await message.answer("❌ Promokod limiti tugagan.")
            return

        if expires_at and datetime.fromisoformat(expires_at) < datetime.utcnow():
            await db.rollback()
            await message.answer("⌛ Promokod muddati tugagan.")
            return

        try:
            await db.execute("""
                INSERT INTO promo_uses(promo_id,user_id,used_at)
                VALUES(?,?,?)
            """, (promo_id, message.from_user.id, now()))
        except aiosqlite.IntegrityError:
            await db.rollback()
            await message.answer("Siz bu koddan avval foydalangansiz.")
            return

        await db.execute("""
            UPDATE promo_codes SET used_count=used_count+1 WHERE id=?
        """, (promo_id,))

        await db.execute("""
            UPDATE users
            SET balance=balance+?,total_earned=total_earned+?
            WHERE user_id=?
        """, (amount, amount, message.from_user.id))

        await db.execute("""
            INSERT INTO transactions(user_id,amount,kind,description,created_at)
            VALUES(?,?,?,?,?)
        """, (
            message.from_user.id,
            amount,
            "promo",
            f"Promokod {code}",
            now()
        ))

        await db.commit()

    await state.clear()
    await message.answer(f"🎉 Promokod qabul qilindi! +{amount} Stars.")


# =========================================================
# 14. VAZIFALAR
# =========================================================

@dp.message(F.text == "📋 Vazifalar")
async def tasks_list(message: Message):
    tasks = await db_fetchall(
        "SELECT * FROM tasks WHERE active=1 ORDER BY id DESC"
    )

    if not tasks:
        await message.answer("Hozircha faol vazifalar yo‘q.")
        return

    for task in tasks:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Vazifani ochish",
                    url=task["link"]
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Bajarishni yuborish",
                    callback_data=f"task:{task['id']}"
                )
            ]
        ]) if task["link"] else InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Bajarishni yuborish",
                    callback_data=f"task:{task['id']}"
                )
            ]
        ])

        await message.answer(
            f"📋 <b>{task['title']}</b>\n"
            f"⭐ Mukofot: {task['reward']} Stars\n\n"
            "Bajarishni tekshirish uchun yuboring.",
            reply_markup=kb
        )


@dp.callback_query(F.data.startswith("task:"))
async def task_complete(call: CallbackQuery):
    task_id = int(call.data.split(":")[1])

    task = await db_fetchone(
        "SELECT * FROM tasks WHERE id=? AND active=1",
        (task_id,)
    )

    if not task:
        await call.answer("Vazifa mavjud emas.", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("""
                INSERT INTO task_completions(task_id,user_id,status,created_at)
                VALUES(?,?,?,?)
            """, (task_id, call.from_user.id, "pending", now()))
            await db.commit()
        except aiosqlite.IntegrityError:
            await call.answer("Bu vazifani oldin yuborgansiz.", show_alert=True)
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"taskok:{task_id}:{call.from_user.id}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"taskno:{task_id}:{call.from_user.id}"
            )
        ]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📋 Vazifa tekshiruvi\n"
                f"Foydalanuvchi: {call.from_user.full_name}\n"
                f"ID: {call.from_user.id}\n"
                f"Vazifa: {task['title']}",
                reply_markup=kb
            )
        except TelegramAPIError:
            log.exception("Vazifa tekshiruvi adminga yuborilmadi")

    await call.answer("Tekshiruvga yuborildi.")
    await call.message.answer("⏳ Vazifangiz admin tekshiruviga yuborildi.")


@dp.callback_query(F.data.startswith("taskok:"))
async def task_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    _, task_id, user_id = call.data.split(":")
    task_id, user_id = int(task_id), int(user_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")

        cur = await db.execute("""
            SELECT status FROM task_completions
            WHERE task_id=? AND user_id=?
        """, (task_id, user_id))
        row = await cur.fetchone()

        if not row or row[0] != "pending":
            await db.rollback()
            await call.answer("Bu vazifa allaqachon ko‘rilgan.")
            return

        cur = await db.execute(
            "SELECT reward FROM tasks WHERE id=?",
            (task_id,)
        )
        task = await cur.fetchone()

        if not task:
            await db.rollback()
            return

        reward = task[0]

        await db.execute("""
            UPDATE task_completions SET status='approved'
            WHERE task_id=? AND user_id=?
        """, (task_id, user_id))

        await db.execute("""
            UPDATE users SET balance=balance+?,total_earned=total_earned+?
            WHERE user_id=?
        """, (reward, reward, user_id))

        await db.execute("""
            INSERT INTO transactions(user_id,amount,kind,description,created_at)
            VALUES(?,?,?,?,?)
        """, (user_id, reward, "task", f"Vazifa #{task_id}", now()))

        await db.commit()

    await bot.send_message(user_id, f"🎉 Vazifa tasdiqlandi! +{reward} Stars.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Tasdiqlandi.")


@dp.callback_query(F.data.startswith("taskno:"))
async def task_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    _, task_id, user_id = call.data.split(":")
    task_id, user_id = int(task_id), int(user_id)

    await db_execute("""
        UPDATE task_completions SET status='rejected'
        WHERE task_id=? AND user_id=? AND status='pending'
    """, (task_id, user_id))

    await bot.send_message(user_id, "❌ Vazifangiz rad etildi.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Rad etildi.")


# =========================================================
# 15. REYTING
# =========================================================

@dp.message(F.text == "🏆 Reyting")
async def ranking(message: Message):
    rows = await db_fetchall("""
        SELECT full_name,username,COUNT(*) AS refs
        FROM users
        WHERE referrer_id IS NOT NULL
        GROUP BY referrer_id
        ORDER BY refs DESC
        LIMIT 10
    """)

    text = "🏆 <b>Referal reytingi</b>\n\n"
    if not rows:
        text += "Hozircha reyting bo‘sh."
    else:
        for i, row in enumerate(rows, 1):
            text += f"{i}. {row['full_name']} — {row['refs']} ta\n"

    await message.answer(text)


# =========================================================
# 16. MUROJAAT
# =========================================================

@dp.message(F.text == "💬 Adminga murojaat")
async def support_start(message: Message, state: FSMContext):
    await state.set_state(SupportState.message)
    await message.answer(
        "💬 Xabaringizni yuboring. Matn, rasm yoki video yuborishingiz mumkin.",
        reply_markup=cancel_keyboard()
    )


@dp.message(SupportState.message)
async def support_receive(message: Message, state: FSMContext):
    text = message.text or message.caption or "[Media xabar]"

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO support_messages(user_id,text,status,created_at)
            VALUES(?,?,?,?)
        """, (message.from_user.id, text, "new", now()))
        support_id = cur.lastrowid
        await db.commit()

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💬 <b>Yangi murojaat #{support_id}</b>\n"
                f"👤 {message.from_user.full_name}\n"
                f"🆔 <code>{message.from_user.id}</code>\n"
                f"Xabar: {text}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="✍️ Javob berish",
                        callback_data=f"supportreply:{support_id}"
                    )
                ]])
            )
            if message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id)
            elif message.video:
                await bot.send_video(admin_id, message.video.file_id)
        except TelegramAPIError:
            log.exception("Murojaat adminlarga yuborilmadi")

    await state.clear()
    await message.answer("✅ Murojaatingiz yuborildi.")


@dp.callback_query(F.data.startswith("supportreply:"))
async def support_reply_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    support_id = int(call.data.split(":")[1])
    ticket = await db_fetchone(
        "SELECT user_id FROM support_messages WHERE id=?",
        (support_id,)
    )

    if not ticket:
        await call.answer("Murojaat topilmadi.", show_alert=True)
        return

    await state.set_state(SupportState.waiting_for_reply)
    await state.update_data(
        support_id=support_id,
        target_user=ticket["user_id"]
    )
    await call.message.answer(
        "Javob matnini yuboring:",
        reply_markup=cancel_keyboard()
    )
    await call.answer()


@dp.message(SupportState.waiting_for_reply)
async def support_reply_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    target = data["target_user"]
    support_id = data["support_id"]

    try:
        await bot.send_message(
            target,
            "💬 <b>Admin javobi:</b>\n\n" + (message.text or message.caption or "Admin sizga javob yubordi.")
        )
        await db_execute("""
            UPDATE support_messages
            SET status='answered',admin_id=?
            WHERE id=?
        """, (message.from_user.id, support_id))
        await message.answer("✅ Javob yuborildi.")
    except TelegramAPIError:
        await message.answer("❌ Foydalanuvchiga xabar yuborilmadi.")

    await state.clear()


# =========================================================
# 17. YANGILIKLAR
# =========================================================

@dp.message(F.text == "📰 Yangiliklar")
async def show_news(message: Message):
    rows = await db_fetchall(
        "SELECT * FROM news ORDER BY id DESC LIMIT 10"
    )

    if not rows:
        await message.answer("Hozircha yangiliklar yo‘q.")
        return

    for row in rows:
        await message.answer(row["text"])


@dp.message(F.text == "📖 Qo‘llanma")
async def guide(message: Message):
    await message.answer(
        "📖 <b>Qo‘llanma</b>\n\n"
        "1. Referal havolangiz orqali do‘stlaringizni taklif qiling.\n"
        "2. Bonus va vazifalar orqali Stars yig‘ing.\n"
        "3. Promokodlardan foydalaning.\n"
        "4. Balansingizdan 15 yoki 25 Stars yechish uchun buyurtma bering.\n"
        "5. Savollar bo‘lsa, adminga murojaat qiling.\n\n"
        "Eslatma: botdagi Stars ichki hisob birligi bo‘lib, avtomatik ravishda haqiqiy Telegram Starsga teng emas."
    )


@dp.message(F.text == "⚙️ Sozlamalar")
async def settings_user(message: Message):
    await message.answer(
        "⚙️ <b>Sozlamalar</b>\n\n"
        "Ism: " + message.from_user.full_name + "\n"
        f"Telegram ID: <code>{message.from_user.id}</code>"
    )


# =========================================================
# 18. ADMIN PANEL
# =========================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🛠 <b>Admin panel</b>",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(F.data.startswith("a:"))
async def admin_callbacks(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    action = call.data.split(":")[1]

    if action == "close":
        await call.message.delete()
        return

    if action == "stats":
        users = await db_fetchone("SELECT COUNT(*) AS n FROM users")
        orders = await db_fetchone("SELECT COUNT(*) AS n FROM orders")
        pending = await db_fetchone(
            "SELECT COUNT(*) AS n FROM orders WHERE status='pending'"
        )
        total = await db_fetchone(
            "SELECT COALESCE(SUM(balance),0) AS n FROM users"
        )

        await call.message.answer(
            "📊 <b>Statistika</b>\n\n"
            f"👥 Foydalanuvchilar: {users['n']}\n"
            f"📦 Buyurtmalar: {orders['n']}\n"
            f"⏳ Kutilayotgan buyurtmalar: {pending['n']}\n"
            f"⭐ Umumiy balans: {total['n']}"
        )

    elif action == "users":
        await state.set_state(AdminState.search_user)
        await call.message.answer(
            "Foydalanuvchi ID yoki username yuboring:",
            reply_markup=cancel_keyboard()
        )

    elif action == "orders":
        rows = await db_fetchall("""
            SELECT id,user_id,amount,status,created_at
            FROM orders ORDER BY id DESC LIMIT 15
        """)
        if not rows:
            await call.message.answer("Buyurtmalar yo‘q.")
        else:
            for row in rows:
                kb = None
                if row["status"] == "pending":
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="✅ Tasdiqlash",
                            callback_data=f"order:approve:{row['id']}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Rad etish",
                            callback_data=f"order:reject:{row['id']}"
                        )
                    ]])
                await call.message.answer(
                    f"📦 #{row['id']}\n"
                    f"User: <code>{row['user_id']}</code>\n"
                    f"Miqdor: {row['amount']} ⭐\n"
                    f"Holat: {row['status']}\n"
                    f"Vaqt: {row['created_at']}",
                    reply_markup=kb
                )

    elif action == "promos":
        await call.message.answer(
            "🎁 Promokod yaratish uchun /addpromo buyrug‘idan foydalaning."
        )

    elif action == "channels":
        await call.message.answer(
            "📢 Kanal qo‘shish: /addchannel\n"
            "Kanal o‘chirish: /delchannel ID"
        )
        channels = await db_fetchall("SELECT * FROM channels")
        for ch in channels:
            await call.message.answer(
                f"#{ch['id']} — {ch['title']}\n"
                f"ID: <code>{ch['chat_id']}</code>"
            )

    elif action == "broadcast":
        await state.set_state(AdminState.broadcast)
        await call.message.answer(
            "Tarqatiladigan xabarni yuboring. Matn, rasm yoki video bo‘lishi mumkin:",
            reply_markup=cancel_keyboard()
        )

    elif action == "tasks":
        await call.message.answer(
            "Vazifa yaratish: /addtask\n"
            "Vazifalar ro‘yxati: /tasks"
        )

    elif action == "support":
        rows = await db_fetchall("""
            SELECT id,user_id,text,status FROM support_messages
            WHERE status='new' ORDER BY id DESC LIMIT 15
        """)
        if not rows:
            await call.message.answer("Yangi murojaatlar yo‘q.")
        for row in rows:
            await call.message.answer(
                f"💬 #{row['id']}\n"
                f"User: <code>{row['user_id']}</code>\n"
                f"{row['text']}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="✍️ Javob berish",
                        callback_data=f"supportreply:{row['id']}"
                    )
                ]])
            )

    elif action == "news":
        await state.set_state(AdminState.add_news)
        await call.message.answer(
            "Yangilik matnini yuboring:",
            reply_markup=cancel_keyboard()
        )

    elif action == "rating":
        rows = await db_fetchall("""
            SELECT full_name,COUNT(*) AS refs
            FROM users WHERE referrer_id IS NOT NULL
            GROUP BY referrer_id ORDER BY refs DESC LIMIT 10
        """)
        text = "🏆 <b>Referal reytingi</b>\n"
        for i, row in enumerate(rows, 1):
            text += f"\n{i}. {row['full_name']} — {row['refs']}"
        await call.message.answer(text)

    elif action == "settings":
        if not main_admin(call.from_user.id):
            await call.answer(
                "Bu bo‘lim faqat asosiy admin uchun.",
                show_alert=True
            )
            return

        await call.message.answer(
            "⚙️ Sozlamalar:\n"
            f"Referal mukofoti: {await get_setting('referral_reward')}\n"
            f"Kunlik bonus: {await get_setting('daily_bonus')}\n\n"
            "O‘zgartirish buyruqlari:\n"
            "/setref soni\n"
            "/setdaily soni\n"
            "/setweekly soni"
        )

    await call.answer()


# =========================================================
# 19. ADMIN FOYDALANUVCHINI QIDIRISH
# =========================================================

@dp.message(AdminState.search_user)
async def admin_search_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    value = message.text.strip().replace("@", "")

    if value.isdigit():
        user = await db_fetchone(
            "SELECT * FROM users WHERE user_id=?",
            (int(value),)
        )
    else:
        user = await db_fetchone(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (value,)
        )

    await state.clear()

    if not user:
        await message.answer("Foydalanuvchi topilmadi.")
        return

    await message.answer(
        "👤 <b>Foydalanuvchi profili</b>\n\n"
        f"Ism: {user['full_name']}\n"
        f"Username: @{user['username'] or 'yo‘q'}\n"
        f"ID: <code>{user['user_id']}</code>\n"
        f"Balans: {user['balance']}\n"
        f"Jami daromad: {user['total_earned']}\n"
        f"Referer ID: {user['referrer_id']}\n"
        f"Blok: {'Ha' if user['is_banned'] else 'Yo‘q'}\n"
        f"Ro‘yxatdan o‘tgan: {user['created_at']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Balans qo‘shish",
                    callback_data=f"baladd:{user['user_id']}"
                ),
                InlineKeyboardButton(
                    text="⛔ Bloklash",
                    callback_data=f"ban:{user['user_id']}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔓 Blokdan chiqarish",
                    callback_data=f"unban:{user['user_id']}"
                )
            ]
        ])
    )


@dp.callback_query(F.data.startswith("ban:"))
async def ban_user(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    user_id = int(call.data.split(":")[1])
    await db_execute(
        "UPDATE users SET is_banned=1 WHERE user_id=?",
        (user_id,)
    )
    await call.answer("Foydalanuvchi bloklandi.")


@dp.callback_query(F.data.startswith("unban:"))
async def unban_user(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    user_id = int(call.data.split(":")[1])
    await db_execute(
        "UPDATE users SET is_banned=0 WHERE user_id=?",
        (user_id,)
    )
    await call.answer("Blokdan chiqarildi.")


@dp.callback_query(F.data.startswith("baladd:"))
async def balance_add_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    user_id = int(call.data.split(":")[1])
    await state.set_state(AdminState.balance_amount)
    await state.update_data(target_user=user_id)
    await call.message.answer("Qo‘shiladigan Stars miqdorini yuboring:")
    await call.answer()


@dp.message(AdminState.balance_amount)
async def balance_add_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Musbat butun son kiriting.")
        return

    data = await state.get_data()
    ok = await change_balance(
        data["target_user"],
        int(message.text),
        "admin_add",
        f"Admin {message.from_user.id} qo‘shdi"
    )

    await state.clear()
    await message.answer(
        "✅ Balans qo‘shildi." if ok else "❌ Amal bajarilmadi."
    )


# =========================================================
# 20. ADMIN BUYRUQLARI
# =========================================================

@dp.message(Command("addchannel"))
async def add_channel_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminState.add_channel)
    await message.answer(
        "Kanal ma’lumotini quyidagi ko‘rinishda yuboring:\n"
        "<code>@username | Kanal nomi | https://t.me/username</code>"
    )


@dp.message(AdminState.add_channel)
async def add_channel_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    parts = [x.strip() for x in message.text.split("|")]
    if len(parts) != 3:
        await message.answer("Format xato. Qayta yuboring.")
        return

    chat_id, title, link = parts

    try:
        chat = await bot.get_chat(chat_id)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)

        if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            await message.answer("Bot ushbu kanalda administrator bo‘lishi kerak.")
            return

        await db_execute("""
            INSERT INTO channels(chat_id,title,invite_link)
            VALUES(?,?,?)
        """, (str(chat.id), title, link))

        await message.answer("✅ Kanal qo‘shildi.")
        await state.clear()

    except aiosqlite.IntegrityError:
        await message.answer("Bu kanal oldin qo‘shilgan.")
    except TelegramAPIError:
        await message.answer("Kanalni tekshirib bo‘lmadi. Bot admin ekanini tekshiring.")


@dp.message(Command("delchannel"))
async def delete_channel(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /delchannel 1")
        return

    await db_execute("DELETE FROM channels WHERE id=?", (int(parts[1]),))
    await message.answer("✅ Kanal o‘chirildi.")


@dp.message(Command("addpromo"))
async def add_promo_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminState.add_promo_code)
    await message.answer("Promokod nomini yuboring:")


@dp.message(AdminState.add_promo_code)
async def add_promo_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    await state.update_data(code=message.text.strip().upper())
    await state.set_state(AdminState.add_promo_amount)
    await message.answer("Necha Stars beriladi?")


@dp.message(AdminState.add_promo_amount)
async def add_promo_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Musbat son kiriting.")
        return
    await state.update_data(amount=int(message.text))
    await state.set_state(AdminState.add_promo_limit)
    await message.answer("Foydalanish limiti. Cheksiz uchun 0 yuboring.")


@dp.message(AdminState.add_promo_limit)
async def add_promo_limit(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.isdigit():
        await message.answer("Butun son kiriting.")
        return

    data = await state.get_data()
    try:
        await db_execute("""
            INSERT INTO promo_codes(code,amount,usage_limit)
            VALUES(?,?,?)
        """, (data["code"], data["amount"], int(message.text)))
        await message.answer("✅ Promokod yaratildi.")
    except aiosqlite.IntegrityError:
        await message.answer("Bu promokod mavjud.")

    await state.clear()


@dp.message(Command("addtask"))
async def add_task_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminState.add_task_title)
    await message.answer("Vazifa nomini yuboring:")


@dp.message(AdminState.add_task_title)
async def add_task_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AdminState.add_task_link)
    await message.answer("Vazifa havolasini yuboring:")


@dp.message(AdminState.add_task_link)
async def add_task_link(message: Message, state: FSMContext):
    await state.update_data(link=message.text.strip())
    await state.set_state(AdminState.add_task_reward)
    await message.answer("Mukofot miqdorini Starsda kiriting:")


@dp.message(AdminState.add_task_reward)
async def add_task_reward(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Musbat son kiriting.")
        return

    data = await state.get_data()
    await db_execute("""
        INSERT INTO tasks(title,link,reward)
        VALUES(?,?,?)
    """, (data["title"], data["link"], int(message.text)))

    await state.clear()
    await message.answer("✅ Vazifa yaratildi.")


@dp.message(Command("tasks"))
async def admin_tasks(message: Message):
    if not is_admin(message.from_user.id):
        return
    rows = await db_fetchall("SELECT * FROM tasks ORDER BY id DESC")
    if not rows:
        await message.answer("Vazifalar yo‘q.")
        return
    for row in rows:
        await message.answer(
            f"#{row['id']} — {row['title']}\n"
            f"Mukofot: {row['reward']}\n"
            f"Faol: {row['active']}"
        )


@dp.message(Command("setref"))
async def set_referral_reward(message: Message):
    if not main_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /setref 2")
        return
    await set_setting("referral_reward", parts[1])
    await message.answer("Referal mukofoti yangilandi.")


@dp.message(Command("setdaily"))
async def set_daily_reward(message: Message):
    if not main_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /setdaily 1")
        return
    await set_setting("daily_bonus", parts[1])
    await message.answer("Kunlik bonus yangilandi.")


@dp.message(Command("setweekly"))
async def set_weekly_reward(message: Message):
    if not main_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /setweekly 5")
        return
    await set_setting("weekly_bonus", parts[1])
    await message.answer("Haftalik bonus sozlandi.")


# =========================================================
# 21. REKLAMA TARQATISH
# =========================================================

@dp.message(AdminState.broadcast)
async def broadcast_preview(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    await state.update_data(
        source_chat=message.chat.id,
        source_message=message.message_id
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="👥 Foydalanuvchilarga",
                callback_data="bc:users"
            ),
            InlineKeyboardButton(
                text="📢 Kanallarga",
                callback_data="bc:channels"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data="cancel"
            )
        ]
    ])

    await message.answer(
        "📣 Reklama tayyor. Qayerga yuborilsin?",
        reply_markup=kb
    )


@dp.callback_query(F.data.startswith("bc:"))
async def broadcast_send(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    target = call.data.split(":")[1]
    data = await state.get_data()

    if not data.get("source_message"):
        await call.answer("Reklama xabari topilmadi.", show_alert=True)
        return

    if target == "users":
        recipients = await db_fetchall(
            "SELECT user_id FROM users WHERE is_banned=0"
        )
        ids = [x["user_id"] for x in recipients]
    else:
        channels = await db_fetchall(
            "SELECT chat_id FROM channels WHERE active=1"
        )
        ids = [x["chat_id"] for x in channels]

    success = 0
    failed = 0

    status = await call.message.answer("⏳ Reklama tarqatilmoqda...")

    for target_id in ids:
        try:
            await bot.copy_message(
                chat_id=target_id,
                from_chat_id=data["source_chat"],
                message_id=data["source_message"]
            )
            success += 1
        except TelegramAPIError:
            failed += 1

        await asyncio.sleep(0.05)

    await db_execute("""
        INSERT INTO broadcasts(admin_id,target,success,failed,created_at)
        VALUES(?,?,?,?,?)
    """, (call.from_user.id, target, success, failed, now()))

    await status.edit_text(
        "✅ <b>Reklama yakunlandi</b>\n\n"
        f"Yuborildi: {success}\n"
        f"Xatolik: {failed}"
    )

    await state.clear()
    await call.answer()


# =========================================================
# 22. BEKOR QILISH
# =========================================================

@dp.callback_query(F.data == "cancel")
async def cancel_callback(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer(
        "❌ Jarayon bekor qilindi.",
        reply_markup=user_keyboard() if not is_admin(call.from_user.id) else None
    )
    await call.answer()


@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Jarayon bekor qilindi.",
        reply_markup=user_keyboard()
    )


# =========================================================
# 23. BLOKLANGAN FOYDALANUVCHILARNI CHEKLASH
# =========================================================

@dp.message()
async def fallback_handler(message: Message):
    if is_admin(message.from_user.id):
        return

    user = await db_fetchone(
        "SELECT is_banned FROM users WHERE user_id=?",
        (message.from_user.id,)
    )

    if user and user["is_banned"]:
        await message.answer("⛔ Siz bloklangansiz.")
        return

    await message.answer(
        "Menyudagi tugmalardan foydalaning.",
        reply_markup=user_keyboard()
    )


# =========================================================
# 24. HEALTH CHECK — RENDER
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
    return runner


# =========================================================
# 25. ISHGA TUSHIRISH
# =========================================================

async def main():
    await init_db()

    # Admin ID larni bazada ro'yxatga olish
    await db_execute(
        "INSERT OR IGNORE INTO admins(user_id,role) VALUES(?,?)",
        (ADMIN_ID_1, "main")
    )
    await db_execute(
        "INSERT OR IGNORE INTO admins(user_id,role) VALUES(?,?)",
        (ADMIN_ID_2, "secondary")
    )

    runner = await start_web_server()

    try:
        log.info("Bot ishga tushmoqda...")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
