import asyncio
import html
import logging
import os
import sqlite3

from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    LabeledPrice,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    PreCheckoutQuery,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


# ==================================================
# SOZLAMALAR
# ==================================================

TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "5200398952"))
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN Render Environment Variables ichida kiritilmagan!")

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())


# ==================================================
# HOLATLAR
# ==================================================

class Support(StatesGroup):
    waiting = State()


# ==================================================
# DATABASE
# ==================================================

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            referrer_id INTEGER,
            banned INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            kind TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contest_id INTEGER,
            voter_id INTEGER,
            target_id INTEGER,
            UNIQUE(contest_id, voter_id)
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
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            charge_id TEXT UNIQUE,
            amount INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            name TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def get_setting(name, default=""):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE name=?", (name,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(name, value):
    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO settings(name, value)
        VALUES(?, ?)
        ON CONFLICT(name) DO UPDATE SET value=excluded.value
    """, (name, value))
    conn.commit()
    conn.close()


def get_channels():
    saved = get_setting("required_channels", None)

    if saved is not None:
        return [x.strip() for x in saved.split(",") if x.strip()]

    initial = os.getenv("REQUIRED_CHANNELS", "")
    channels = [x.strip() for x in initial.split(",") if x.strip()]

    set_setting("required_channels", ",".join(channels))
    return channels


def save_channels(channels):
    set_setting("required_channels", ",".join(channels))


def get_user(user_id):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()
    conn.close()
    return user


def register_user(user_id, referrer_id=None):
    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    exists = cur.fetchone()

    if not exists:
        if referrer_id == user_id:
            referrer_id = None

        cur.execute("""
            INSERT INTO users(user_id, balance, referrer_id)
            VALUES(?, 0, ?)
        """, (user_id, referrer_id))

    conn.commit()
    conn.close()


def is_banned(user_id):
    user = get_user(user_id)
    return bool(user and user["banned"])


def add_transaction(user_id, amount, description):
    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO transactions(user_id, amount, description)
        VALUES(?, ?, ?)
    """, (user_id, amount, description))
    conn.commit()
    conn.close()


def change_balance(user_id, amount, description):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users SET balance=balance+?
        WHERE user_id=?
    """, (amount, user_id))

    cur.execute("""
        INSERT INTO transactions(user_id, amount, description)
        VALUES(?, ?, ?)
    """, (user_id, amount, description))

    conn.commit()
    conn.close()


def award_referral(user_id):
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        "SELECT referrer_id FROM users WHERE user_id=?",
        (user_id,)
    )
    row = cur.fetchone()

    if not row or not row["referrer_id"]:
        conn.close()
        return

    referrer_id = row["referrer_id"]

    cur.execute("""
        INSERT OR IGNORE INTO referrals(user_id, referrer_id)
        VALUES(?, ?)
    """, (user_id, referrer_id))

    awarded = cur.rowcount == 1

    if awarded:
        cur.execute("""
            UPDATE users SET balance=balance+2
            WHERE user_id=?
        """, (referrer_id,))

        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?, 2, 'Referal mukofoti')
        """, (referrer_id,))

    conn.commit()
    conn.close()

    if awarded:
        return referrer_id

    return None


# ==================================================
# KLAVIATURALAR
# ==================================================

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎁 Sovg'a olish",
                callback_data="menu:gift"
            ),
            InlineKeyboardButton(
                text="⭐ Stars sotib olish",
                callback_data="menu:buy"
            )
        ],
        [
            InlineKeyboardButton(
                text="👥 Referal",
                callback_data="menu:ref"
            ),
            InlineKeyboardButton(
                text="👤 Mening hisobim",
                callback_data="menu:profile"
            )
        ],
        [
            InlineKeyboardButton(
                text="🏆 Konkurs",
                callback_data="menu:contest"
            ),
            InlineKeyboardButton(
                text="⚔️ Battle",
                callback_data="menu:battle"
            )
        ],
        [
            InlineKeyboardButton(
                text="📦 Buyurtmalarim",
                callback_data="menu:orders"
            ),
            InlineKeyboardButton(
                text="📜 Tarix",
                callback_data="menu:history"
            )
        ],
        [
            InlineKeyboardButton(
                text="📊 Reyting",
                callback_data="menu:rating"
            ),
            InlineKeyboardButton(
                text="📖 Qo'llanma",
                callback_data="menu:guide"
            )
        ],
        [
            InlineKeyboardButton(
                text="💬 Adminga murojaat",
                callback_data="menu:support"
            )
        ]
    ])


def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⬅️ Bosh menyu",
                callback_data="menu:home"
            )
        ]
    ])


def subscription_keyboard():
    channels = get_channels()
    buttons = []

    for channel in channels:
        clean = channel.replace("@", "")
        buttons.append([
            InlineKeyboardButton(
                text=f"📢 {channel}",
                url=f"https://t.me/{clean}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📊 Statistika",
                callback_data="admin:stats"
            ),
            InlineKeyboardButton(
                text="👥 Foydalanuvchilar",
                callback_data="admin:users"
            )
        ],
        [
            InlineKeyboardButton(
                text="➕ Stars qo'shish",
                callback_data="admin:add"
            ),
            InlineKeyboardButton(
                text="➖ Stars ayirish",
                callback_data="admin:sub"
            )
        ],
        [
            InlineKeyboardButton(
                text="📦 Buyurtmalar",
                callback_data="admin:orders"
            ),
            InlineKeyboardButton(
                text="📢 Kanallar",
                callback_data="admin:channels"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎁 Referal mukofoti",
                callback_data="admin:reward"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Bosh menyu",
                callback_data="menu:home"
            )
        ]
    ])


# ==================================================
# OBUNANI TEKSHIRISH
# ==================================================

async def check_subscription(user_id):
    channels = get_channels()

    for channel in channels:
        try:
            member = await bot.get_chat_member(
                chat_id=channel,
                user_id=user_id
            )

            if member.status in ("left", "kicked"):
                return False

        except Exception as error:
            logging.warning(
                "Obunani tekshirish xatosi %s: %s",
                channel,
                error
            )
            return False

    return True


async def welcome(message):
    user_id = message.from_user.id

    if is_banned(user_id):
        await message.answer("🚫 Siz botdan foydalanish huquqidan mahrum qilingansiz.")
        return

    if not await check_subscription(user_id):
        await message.answer(
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
            reply_markup=subscription_keyboard()
        )
        return

    referrer = award_referral(user_id)

    if referrer:
        try:
            await bot.send_message(
                referrer,
                "🎉 Sizning referalingiz botga qo'shildi!\n"
                "Hisobingizga 2 Stars qo'shildi."
            )
        except Exception:
            pass

    await message.answer(
        "👋 Xush kelibsiz!\n\nKerakli bo'limni tanlang:",
        reply_markup=main_keyboard()
    )


# ==================================================
# START
# ==================================================

@dp.message(CommandStart())
async def start_handler(message: Message, command: CommandObject):
    user_id = message.from_user.id

    referrer_id = None

    if command.args:
        try:
            referrer_id = int(command.args)
        except ValueError:
            referrer_id = None

    register_user(user_id, referrer_id)
    await welcome(message)


# ==================================================
# OBUNANI QAYTA TEKSHIRISH
# ==================================================

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):
    await call.answer()

    if not await check_subscription(call.from_user.id):
        await call.message.answer(
            "❌ Siz hali barcha kanallarga obuna bo'lmagansiz.",
            reply_markup=subscription_keyboard()
        )
        return

    referrer = award_referral(call.from_user.id)

    if referrer:
        try:
            await bot.send_message(
                referrer,
                "🎉 Referalingiz uchun 2 Stars berildi!"
            )
        except Exception:
            pass

    await call.message.answer(
        "✅ Obuna tasdiqlandi!",
        reply_markup=main_keyboard()
    )


# ==================================================
# BOSH MENYU
# ==================================================

@dp.callback_query(F.data == "menu:home")
async def home_callback(call: CallbackQuery):
    await call.answer()
    await call.message.answer(
        "🏠 Bosh menyu:",
        reply_markup=main_keyboard()
    )


# ==================================================
# FOYDALANUVCHI BO'LIMLARI
# ==================================================

@dp.callback_query(F.data == "menu:profile")
async def profile_callback(call: CallbackQuery):
    await call.answer()

    user = get_user(call.from_user.id)

    balance = user["balance"] if user else 0

    conn = connect()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) AS total FROM referrals WHERE referrer_id=?",
        (call.from_user.id,)
    )
    referrals = cur.fetchone()["total"]

    conn.close()

    await call.message.answer(
        f"👤 <b>Mening hisobim</b>\n\n"
        f"🆔 ID: <code>{call.from_user.id}</code>\n"
        f"⭐ Balans: {balance}\n"
        f"👥 Referallar: {referrals}",
        reply_markup=back_keyboard()
    )


@dp.callback_query(F.data == "menu:ref")
async def referral_callback(call: CallbackQuery):
    await call.answer()

    link = f"https://t.me/{(await bot.get_me()).username}?start={call.from_user.id}"

    await call.message.answer(
        "👥 <b>Referal tizimi</b>\n\n"
        "Do'stlaringizni taklif qiling.\n"
        "Har bir yangi referal uchun 2 Stars beriladi.\n\n"
        f"🔗 Sizning havolangiz:\n<code>{link}</code>",
        reply_markup=back_keyboard()
    )


@dp.callback_query(F.data == "menu:gift")
async def gift_callback(call: CallbackQuery):
    await call.answer()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="15 ⭐", callback_data="gift:15"),
            InlineKeyboardButton(text="25 ⭐", callback_data="gift:25")
        ],
        [
            InlineKeyboardButton(text="50 ⭐", callback_data="gift:50"),
            InlineKeyboardButton(text="100 ⭐", callback_data="gift:100")
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Bosh menyu",
                callback_data="menu:home"
            )
        ]
    ])

    await call.message.answer(
        "🎁 Qancha Stars yechmoqchisiz?",
        reply_markup=keyboard
    )


# ==================================================
# GIFT BUYURTMASI
# ==================================================

@dp.callback_query(F.data.startswith("gift:"))
async def gift_request(call: CallbackQuery):
    await call.answer()

    try:
        amount = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        return

    if amount not in (15, 25, 50, 100):
        return

    user_id = call.from_user.id

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET balance=balance-?
        WHERE user_id=? AND balance>=?
    """, (amount, user_id, amount))

    success = cur.rowcount == 1

    if success:
        cur.execute("""
            INSERT INTO orders(user_id, amount, status)
            VALUES(?, ?, 'pending')
        """, (user_id, amount))

        order_id = cur.lastrowid

        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?, ?, ?)
        """, (user_id, -amount, f"Buyurtma #{order_id} uchun band qilindi"))

    conn.commit()
    conn.close()

    if not success:
        await call.message.answer(
            "❌ Balansingizda yetarli Stars yo'q.",
            reply_markup=back_keyboard()
        )
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
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

    await call.message.answer(
        f"✅ Buyurtma #{order_id} qabul qilindi.\n"
        f"⭐ Miqdor: {amount}\n"
        "Balansdagi Stars buyurtma uchun vaqtincha band qilindi.",
        reply_markup=back_keyboard()
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            f"📦 <b>Yangi buyurtma</b>\n\n"
            f"🆔 Buyurtma: {order_id}\n"
            f"👤 Foydalanuvchi: <code>{user_id}</code>\n"
            f"⭐ Miqdor: {amount}",
            reply_markup=keyboard
        )
    except Exception:
        logging.exception("Adminga buyurtma yuborilmadi")


# ==================================================
# ADMIN BUYURTMANI TASDIQLASH / RAD ETISH
# ==================================================

@dp.callback_query(F.data.startswith("order:"))
async def order_action(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    await call.answer()

    parts = call.data.split(":")

    if len(parts) != 3:
        return

    action = parts[1]

    try:
        order_id = int(parts[2])
    except ValueError:
        return

    conn = connect()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    )
    order = cur.fetchone()

    if not order or order["status"] != "pending":
        conn.close()
        await call.message.answer("Bu buyurtma allaqachon ko'rib chiqilgan.")
        return

    user_id = order["user_id"]
    amount = order["amount"]

    if action == "approve":
        cur.execute("""
            UPDATE orders SET status='approved'
            WHERE id=? AND status='pending'
        """, (order_id,))

        text = "✅ Buyurtmangiz admin tomonidan tasdiqlandi."

    elif action == "reject":
        cur.execute("""
            UPDATE orders SET status='rejected'
            WHERE id=? AND status='pending'
        """, (order_id,))

        if cur.rowcount == 1:
            cur.execute("""
                UPDATE users SET balance=balance+?
                WHERE user_id=?
            """, (amount, user_id))

            cur.execute("""
                INSERT INTO transactions(user_id, amount, description)
                VALUES(?, ?, ?)
            """, (user_id, amount, f"Rad etilgan buyurtma #{order_id} qaytarildi"))

        text = "❌ Buyurtmangiz rad etildi. Stars balansingizga qaytarildi."

    else:
        conn.close()
        return

    conn.commit()
    conn.close()

    await call.message.answer(f"Buyurtma #{order_id} yangilandi.")

    try:
        await bot.send_message(user_id, text)
    except Exception:
        pass


# ==================================================
# STARS SOTIB OLISH
# ==================================================

@dp.callback_query(F.data == "menu:buy")
async def buy_menu(call: CallbackQuery):
    await call.answer()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="10 ⭐",
                callback_data="buy:10"
            ),
            InlineKeyboardButton(
                text="25 ⭐",
                callback_data="buy:25"
            )
        ],
        [
            InlineKeyboardButton(
                text="50 ⭐",
                callback_data="buy:50"
            ),
            InlineKeyboardButton(
                text="100 ⭐",
                callback_data="buy:100"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Bosh menyu",
                callback_data="menu:home"
            )
        ]
    ])

    await call.message.answer(
        "⭐ Qancha Stars sotib olmoqchisiz?",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("buy:"))
async def buy_stars(call: CallbackQuery):
    await call.answer()

    try:
        amount = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        return

    if amount not in (10, 25, 50, 100):
        return

    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"{amount} Stars",
        description=f"{amount} Stars uchun to'lov",
        payload=f"stars_{call.from_user.id}_{amount}",
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label=f"{amount} Stars",
                amount=amount
            )
        ]
    )


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment

    if payment.currency != "XTR":
        return

    payload = payment.invoice_payload

    try:
        _, uid, amount = payload.split("_")
        uid = int(uid)
        amount = int(amount)
    except (ValueError, TypeError):
        return

    if uid != message.from_user.id:
        return

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO payments(user_id, charge_id, amount)
        VALUES(?, ?, ?)
    """, (
        uid,
        payment.telegram_payment_charge_id,
        amount
    ))

    is_new = cur.rowcount == 1

    if is_new:
        cur.execute("""
            UPDATE users SET balance=balance+?
            WHERE user_id=?
        """, (amount, uid))

        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?, ?, ?)
        """, (uid, amount, "Telegram Stars to'lovi"))

    conn.commit()
    conn.close()

    if is_new:
        await message.answer(
            f"✅ To'lov muvaffaqiyatli!\n"
            f"Hisobingizga {amount} Stars qo'shildi.",
            reply_markup=main_keyboard()
        )


# ==================================================
# KONKURS VA BATTLE
# ==================================================

def active_contest(kind=None):
    conn = connect()
    cur = conn.cursor()

    if kind:
        cur.execute("""
            SELECT * FROM contests
            WHERE active=1 AND kind=?
            ORDER BY id DESC LIMIT 1
        """, (kind,))
    else:
        cur.execute("""
            SELECT * FROM contests
            WHERE active=1
            ORDER BY id DESC LIMIT 1
        """)

    result = cur.fetchone()
    conn.close()
    return result


@dp.callback_query(F.data == "menu:contest")
async def contest_menu(call: CallbackQuery):
    await call.answer()

    event = active_contest("contest")

    if not event:
        await call.message.answer(
            "Hozircha faol konkurs yo'q.",
            reply_markup=back_keyboard()
        )
        return

    await call.message.answer(
        f"🏆 <b>{html.escape(event['title'])}</b>\n\n"
        f"{html.escape(event['description'] or '')}\n\n"
        f"Ishtirokchi ID sini yuborish uchun:\n"
        f"<code>/vote USER_ID</code>",
        reply_markup=back_keyboard()
    )


@dp.callback_query(F.data == "menu:battle")
async def battle_menu(call: CallbackQuery):
    await call.answer()

    event = active_contest("battle")

    if not event:
        await call.message.answer(
            "Hozircha faol battle yo'q.",
            reply_markup=back_keyboard()
        )
        return

    await call.message.answer(
        f"⚔️ <b>{html.escape(event['title'])}</b>\n\n"
        f"{html.escape(event['description'] or '')}\n\n"
        f"Ovoz berish: <code>/vote USER_ID</code>",
        reply_markup=back_keyboard()
    )


@dp.message(Command("vote"))
async def vote_handler(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Foydalanish: /vote USER_ID")
        return

    try:
        target_id = int(command.args.strip())
    except ValueError:
        await message.answer("ID noto'g'ri.")
        return

    event = active_contest()

    if not event:
        await message.answer("Faol konkurs yoki battle yo'q.")
        return

    if target_id == message.from_user.id:
        await message.answer("O'zingizga ovoz bera olmaysiz.")
        return

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO votes(contest_id, voter_id, target_id)
        VALUES(?, ?, ?)
    """, (event["id"], message.from_user.id, target_id))

    success = cur.rowcount == 1

    conn.commit()
    conn.close()

    if success:
        await message.answer("✅ Ovoz qabul qilindi.")
    else:
        await message.answer("Siz bu tadbirda avval ovoz bergansiz.")


# ==================================================
# BUYURTMALARIM
# ==================================================

@dp.callback_query(F.data == "menu:orders")
async def my_orders(call: CallbackQuery):
    await call.answer()

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, amount, status, created_at
        FROM orders
        WHERE user_id=?
        ORDER BY id DESC LIMIT 20
    """, (call.from_user.id,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await call.message.answer(
            "Sizda buyurtmalar yo'q.",
            reply_markup=back_keyboard()
        )
        return

    text = "📦 <b>Mening buyurtmalarim</b>\n\n"

    for row in rows:
        text += (
            f"#{row['id']} — {row['amount']} ⭐\n"
            f"Holati: {html.escape(row['status'])}\n\n"
        )

    await call.message.answer(text, reply_markup=back_keyboard())


# ==================================================
# TARIX
# ==================================================

@dp.callback_query(F.data == "menu:history")
async def history_callback(call: CallbackQuery):
    await call.answer()

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT amount, description, created_at
        FROM transactions
        WHERE user_id=?
        ORDER BY id DESC LIMIT 15
    """, (call.from_user.id,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await call.message.answer(
            "Tarix bo'sh.",
            reply_markup=back_keyboard()
        )
        return

    text = "📜 <b>Operatsiyalar tarixi</b>\n\n"

    for row in rows:
        sign = "+" if row["amount"] > 0 else ""
        text += (
            f"{sign}{row['amount']} ⭐ — "
            f"{html.escape(row['description'])}\n"
        )

    await call.message.answer(text, reply_markup=back_keyboard())


# ==================================================
# REYTING
# ==================================================

@dp.callback_query(F.data == "menu:rating")
async def rating_menu(call: CallbackQuery):
    await call.answer()

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, COUNT(*) AS votes
        FROM votes
        GROUP BY target_id
        ORDER BY votes DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await call.message.answer(
            "Hozircha reyting mavjud emas.",
            reply_markup=back_keyboard()
        )
        return

    text = "📊 <b>Ovozlar reytingi</b>\n\n"

    for index, row in enumerate(rows, 1):
        text += f"{index}. ID: {row['user_id']} — {row['votes']} ovoz\n"

    await call.message.answer(text, reply_markup=back_keyboard())


# ==================================================
# QO'LLANMA
# ==================================================

@dp.callback_query(F.data == "menu:guide")
async def guide_callback(call: CallbackQuery):
    await call.answer()

    await call.message.answer(
        "📖 <b>Qo'llanma</b>\n\n"
        "1. Referal havolangizni do'stlaringizga yuboring.\n"
        "2. Referal uchun 2 Stars olasiz.\n"
        "3. Hisobingizni Stars orqali to'ldirishingiz mumkin.\n"
        "4. Sovg'a bo'limidan buyurtma yuborishingiz mumkin.\n"
        "5. Buyurtmalar holatini kuzatib boring.",
        reply_markup=back_keyboard()
    )


# ==================================================
# ADМINGA MUROJAAT
# ==================================================

@dp.callback_query(F.data == "menu:support")
async def support_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(Support.waiting)

    await call.message.answer(
        "💬 Xabaringizni yuboring. U adminga yetkaziladi.\n"
        "Bekor qilish: /cancel"
    )


@dp.message(Command("cancel"))
async def cancel_support(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Bekor qilindi.",
        reply_markup=main_keyboard()
    )


@dp.message(StateFilter(Support.waiting))
async def support_message(message: Message, state: FSMContext):
    if not message.text and not message.photo and not message.document:
        await message.answer("Matn yoki rasm yuboring.")
        return

    await state.clear()

    try:
        await bot.send_message(
            ADMIN_ID,
            f"💬 <b>Yangi murojaat</b>\n"
            f"Foydalanuvchi ID: <code>{message.from_user.id}</code>\n"
            f"Username: @{html.escape(message.from_user.username or 'yoq')}"
        )

        await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

        await message.answer(
            "✅ Xabaringiz adminga yuborildi.",
            reply_markup=main_keyboard()
        )

    except Exception:
        logging.exception("Support xabarini yuborishda xato")
        await message.answer("Xabarni yuborib bo'lmadi. Keyinroq urinib ko'ring.")


# ==================================================
# ADMIN PANEL
# ==================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "🛠 <b>Admin panel</b>",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(F.data.startswith("admin:"))
async def admin_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    await call.answer()
    action = call.data.split(":")[1]

    if action == "stats":
        conn = connect()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) AS total FROM users")
        users = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM orders")
        orders = cur.fetchone()["total"]

        cur.execute("SELECT COALESCE(SUM(balance), 0) AS total FROM users")
        balance = cur.fetchone()["total"]

        conn.close()

        await call.message.answer(
            f"📊 <b>Statistika</b>\n\n"
            f"👥 Foydalanuvchilar: {users}\n"
            f"📦 Buyurtmalar: {orders}\n"
            f"⭐ Jami balans: {balance}"
        )

    elif action == "users":
        conn = connect()
        cur = conn.cursor()
        cur.execute("SELECT user_id, balance FROM users ORDER BY user_id DESC LIMIT 30")
        rows = cur.fetchall()
        conn.close()

        text = "👥 <b>Oxirgi foydalanuvchilar</b>\n\n"

        for row in rows:
            text += f"{row['user_id']} — {row['balance']} ⭐\n"

        await call.message.answer(text)

    elif action == "add":
        await call.message.answer(
            "Stars qo'shish:\n<code>/add USER_ID AMOUNT</code>"
        )

    elif action == "sub":
        await call.message.answer(
            "Stars ayirish:\n<code>/sub USER_ID AMOUNT</code>"
        )

    elif action == "orders":
        conn = connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, amount, status
            FROM orders ORDER BY id DESC LIMIT 20
        """)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await call.message.answer("Buyurtmalar yo'q.")
            return

        text = "📦 <b>Buyurtmalar</b>\n\n"

        for row in rows:
            text += (
                f"#{row['id']} | {row['user_id']} | "
                f"{row['amount']} ⭐ | {row['status']}\n"
            )

        await call.message.answer(text)

    elif action == "channels":
        channels = get_channels()

        text = "📢 <b>Majburiy kanallar</b>\n\n"

        if channels:
            text += "\n".join(channels)
        else:
            text += "Hozircha kanal qo'shilmagan."

        text += (
            "\n\nKanal qo'shish: <code>/channel @kanal</code>"
            "\nKanal o'chirish: <code>/removechannel @kanal</code>"
        )

        await call.message.answer(text)

    elif action == "reward":
        await call.message.answer(
            "Referal mukofotini o'zgartirish uchun:\n"
            "<code>/reward MIQDOR</code>"
        )


# ==================================================
# ADMIN STARS QO'SHISH
# ==================================================

@dp.message(Command("add"))
async def admin_add(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        user_id, amount = map(int, command.args.split())
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.answer("Foydalanish: /add USER_ID AMOUNT")
        return

    register_user(user_id)
    change_balance(user_id, amount, "Admin tomonidan qo'shildi")

    await message.answer("✅ Stars qo'shildi.")

    try:
        await bot.send_message(
            user_id,
            f"🎉 Hisobingizga {amount} Stars qo'shildi."
        )
    except Exception:
        pass


# ==================================================
# ADMIN STARS AYIRISH
# ==================================================

@dp.message(Command("sub"))
async def admin_sub(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        user_id, amount = map(int, command.args.split())
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.answer("Foydalanish: /sub USER_ID AMOUNT")
        return

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users SET balance=balance-?
        WHERE user_id=? AND balance>=?
    """, (amount, user_id, amount))

    success = cur.rowcount == 1

    if success:
        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?, ?, 'Admin tomonidan ayirildi')
        """, (user_id, -amount))

    conn.commit()
    conn.close()

    if success:
        await message.answer("✅ Stars ayirildi.")
        try:
            await bot.send_message(
                user_id,
                f"Hisobingizdan {amount} Stars ayirildi."
            )
        except Exception:
            pass
    else:
        await message.answer("Foydalanuvchi topilmadi yoki balansi yetarli emas.")


# ==================================================
# ADMIN BAN / UNBAN
# ==================================================

@dp.message(Command("ban"))
async def ban_user(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        user_id = int(command.args.strip())
    except Exception:
        await message.answer("Foydalanish: /ban USER_ID")
        return

    register_user(user_id)

    conn = connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

    await message.answer("🚫 Foydalanuvchi bloklandi.")


@dp.message(Command("unban"))
async def unban_user(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        user_id = int(command.args.strip())
    except Exception:
        await message.answer("Foydalanish: /unban USER_ID")
        return

    conn = connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

    await message.answer("✅ Blokdan chiqarildi.")


# ==================================================
# REFERAL MUKOFOTI
# ==================================================

@dp.message(Command("reward"))
async def reward_command(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        amount = int(command.args.strip())
        if amount < 0:
            raise ValueError
    except Exception:
        await message.answer("Foydalanish: /reward MIQDOR")
        return

    set_setting("referral_reward", str(amount))
    await message.answer(f"✅ Referal mukofoti {amount} ga o'zgartirildi.")


# ==================================================
# KONKURS YARATISH
# ==================================================

async def create_event(message: Message, command: CommandObject, kind):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args:
        await message.answer(
            "Foydalanish: /newcontest Nomi | Tavsifi"
        )
        return

    parts = command.args.split("|", 1)
    title = parts[0].strip()
    description = parts[1].strip() if len(parts) > 1 else ""

    if not title:
        await message.answer("Nomi kiritilmagan.")
        return

    conn = connect()
    cur = conn.cursor()

    cur.execute(
        "UPDATE contests SET active=0 WHERE kind=?",
        (kind,)
    )

    cur.execute("""
        INSERT INTO contests(title, description, kind, active)
        VALUES(?, ?, ?, 1)
    """, (title, description, kind))

    event_id = cur.lastrowid

    conn.commit()
    conn.close()

    await message.answer(
        f"✅ Tadbir yaratildi.\nID: {event_id}\nNomi: {html.escape(title)}"
    )


@dp.message(Command("newcontest"))
async def new_contest(message: Message, command: CommandObject):
    await create_event(message, command, "contest")


@dp.message(Command("newbattle"))
async def new_battle(message: Message, command: CommandObject):
    await create_event(message, command, "battle")


# ==================================================
# KONKURSNI YOPISH
# ==================================================

@dp.message(Command("close"))
async def close_contest(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    event = active_contest()

    if not event:
        await message.answer("Faol tadbir yo'q.")
        return

    conn = connect()
    cur = conn.cursor()

    cur.execute(
        "UPDATE contests SET active=0 WHERE id=?",
        (event["id"],)
    )

    cur.execute("""
        SELECT target_id, COUNT(*) AS votes
        FROM votes
        WHERE contest_id=?
        GROUP BY target_id
        ORDER BY votes DESC
        LIMIT 1
    """, (event["id"],))

    winner = cur.fetchone()

    conn.commit()
    conn.close()

    if winner:
        await message.answer(
            f"🏆 Tadbir yopildi.\n"
            f"G'olib ID: {winner['target_id']}\n"
            f"Ovozlar: {winner['votes']}"
        )
    else:
        await message.answer("Tadbir yopildi. Ovozlar bo'lmagan.")


# ==================================================
# KANALLARNI BOSHQARISH
# ==================================================

@dp.message(Command("channel"))
async def add_channel(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args:
        await message.answer("Foydalanish: /channel @kanal")
        return

    channel = command.args.strip()

    if not channel.startswith("@"):
        await message.answer("Kanal @ bilan boshlanishi kerak.")
        return

    channels = get_channels()

    if channel not in channels:
        channels.append(channel)
        save_channels(channels)

    await message.answer(f"✅ {html.escape(channel)} qo'shildi.")


@dp.message(Command("removechannel"))
async def remove_channel(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args:
        await message.answer("Foydalanish: /removechannel @kanal")
        return

    channel = command.args.strip()
    channels = get_channels()

    if channel in channels:
        channels.remove(channel)
        save_channels(channels)
        await message.answer("✅ Kanal o'chirildi.")
    else:
        await message.answer("Kanal ro'yxatda topilmadi.")


@dp.message(Command("channels"))
async def list_channels(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    channels = get_channels()

    if not channels:
        await message.answer("Majburiy kanallar yo'q.")
        return

    await message.answer(
        "📢 Kanallar:\n" + "\n".join(channels)
    )


# ==================================================
# ADMIN BROADCAST
# ==================================================

@dp.message(Command("broadcast"))
async def broadcast(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args:
        await message.answer("Foydalanish: /broadcast XABAR")
        return

    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE banned=0")
    users = cur.fetchall()
    conn.close()

    sent = 0
    failed = 0

    for user in users:
        try:
            await bot.send_message(
                user["user_id"],
                command.args
            )
            sent += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    await message.answer(
        f"📢 Xabar yuborish yakunlandi.\n"
        f"✅ Yuborildi: {sent}\n"
        f"❌ Yuborilmadi: {failed}"
    )


# ==================================================
# HEALTH SERVER (RENDER)
# ==================================================

async def health(request):
    return web.Response(text="Bot ishlayapti!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    logging.info("Health server %s portda ishga tushdi", PORT)

    return runner


# ==================================================
# MAIN
# ==================================================

async def main():
    init_db()

    runner = await start_web_server()

    try:
        logging.info("Telegram bot ishga tushmoqda...")
        await dp.start_polling(bot)

    finally:
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
