
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
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


# =====================================================
# SOZLAMALAR
# =====================================================

TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "5200398952"))
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN kiritilmagan!")

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())


# =====================================================
# HOLATLAR
# =====================================================

class UserState(StatesGroup):
    support = State()


class AdminState(StatesGroup):
    add_channel = State()
    broadcast = State()


# =====================================================
# DATABASE
# =====================================================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            referrer_id INTEGER,
            banned INTEGER NOT NULL DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            charge_id TEXT UNIQUE,
            amount INTEGER NOT NULL,
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
        INSERT OR IGNORE INTO settings(name, value)
        VALUES('referral_reward', '2')
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings(name, value)
        VALUES('required_channels', '')
    """)

    conn.commit()
    conn.close()


def get_setting(name, default=""):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE name=?", (name,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(name, value):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO settings(name, value)
        VALUES(?, ?)
        ON CONFLICT(name)
        DO UPDATE SET value=excluded.value
    """, (name, str(value)))

    conn.commit()
    conn.close()


def get_channels():
    value = get_setting("required_channels", "")
    return [x.strip() for x in value.split(",") if x.strip()]


def save_channels(channels):
    channels = list(dict.fromkeys(channels))
    set_setting("required_channels", ",".join(channels))


def register_user(user_id, referrer_id=None):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user_id,)
    )

    if not cur.fetchone():
        if referrer_id == user_id:
            referrer_id = None

        cur.execute("""
            INSERT INTO users(user_id, balance, referrer_id)
            VALUES(?, 0, ?)
        """, (user_id, referrer_id))

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()
    conn.close()
    return row


def is_banned(user_id):
    user = get_user(user_id)
    return bool(user and user["banned"])


def change_balance(user_id, amount, description):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET balance=balance+?
        WHERE user_id=?
    """, (amount, user_id))

    success = cur.rowcount == 1

    if success:
        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?, ?, ?)
        """, (user_id, amount, description))

    conn.commit()
    conn.close()
    return success


def award_referral(user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT referrer_id FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()

    if not row or not row["referrer_id"]:
        conn.close()
        return None

    referrer_id = row["referrer_id"]

    if referrer_id == user_id:
        conn.close()
        return None

    cur.execute("""
        INSERT OR IGNORE INTO referrals(user_id, referrer_id)
        VALUES(?, ?)
    """, (user_id, referrer_id))

    awarded = cur.rowcount == 1

    if awarded:
        try:
            reward = max(0, int(get_setting("referral_reward", "2")))
        except ValueError:
            reward = 2

        cur.execute("""
            UPDATE users
            SET balance=balance+?
            WHERE user_id=?
        """, (reward, referrer_id))

        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?, ?, ?)
        """, (referrer_id, reward, "Referal mukofoti"))

    conn.commit()
    conn.close()

    return referrer_id if awarded else None


# =====================================================
# KLAVIATURALAR
# =====================================================

def user_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👥 Referal", callback_data="user:ref"),
            InlineKeyboardButton(text="👤 Hisobim", callback_data="user:profile")
        ],
        [
            InlineKeyboardButton(text="⭐ Stars sotib olish", callback_data="user:buy"),
            InlineKeyboardButton(text="🎁 Stars yechish", callback_data="user:gift")
        ],
        [
            InlineKeyboardButton(text="📦 Buyurtmalarim", callback_data="user:orders"),
            InlineKeyboardButton(text="📜 Tarix", callback_data="user:history")
        ],
        [
            InlineKeyboardButton(text="📖 Qo'llanma", callback_data="user:guide"),
            InlineKeyboardButton(text="💬 Adminga murojaat", callback_data="user:support")
        ]
    ])


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="admin:stats"),
            InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin:users")
        ],
        [
            InlineKeyboardButton(text="➕ Stars qo'shish", callback_data="admin:add"),
            InlineKeyboardButton(text="➖ Stars ayirish", callback_data="admin:sub")
        ],
        [
            InlineKeyboardButton(text="📦 Buyurtmalar", callback_data="admin:orders"),
            InlineKeyboardButton(text="📢 Kanallar", callback_data="admin:channels")
        ],
        [
            InlineKeyboardButton(text="📣 Xabar yuborish", callback_data="admin:broadcast"),
            InlineKeyboardButton(text="🎁 Referal mukofoti", callback_data="admin:reward")
        ]
    ])


def back_user_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="user:home")]
    ])


def back_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Admin panel", callback_data="admin:open")]
    ])


def subscription_keyboard():
    buttons = []

    for channel in get_channels():
        clean = channel.lstrip("@")
        buttons.append([
            InlineKeyboardButton(
                text=f"📢 {channel}",
                url=f"https://t.me/{clean}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check:sub"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def channels_keyboard():
    buttons = []

    for index, channel in enumerate(get_channels()):
        clean = channel.lstrip("@")

        buttons.append([
            InlineKeyboardButton(
                text=f"📢 {channel}",
                url=f"https://t.me/{clean}"
            ),
            InlineKeyboardButton(
                text="❌ O'chirish",
                callback_data=f"admin:remove:{index}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="➕ Kanal qo'shish",
            callback_data="admin:addchannel"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Admin panel",
            callback_data="admin:open"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =====================================================
# OBUNANI TEKSHIRISH
# =====================================================

async def check_subscription(user_id):
    if user_id == ADMIN_ID:
        return True

    for channel in get_channels():
        try:
            member = await bot.get_chat_member(
                chat_id=channel,
                user_id=user_id
            )

            if member.status in ("left", "kicked"):
                return False

            if member.status == "restricted" and not member.is_member:
                return False

        except Exception:
            logging.exception("Kanal obunasini tekshirishda xato")
            return False

    return True


async def referral_notice(referrer_id):
    reward = get_setting("referral_reward", "2")

    try:
        await bot.send_message(
            referrer_id,
            f"🎉 Yangi referalingiz qo'shildi!\n"
            f"Hisobingizga {reward} Stars qo'shildi."
        )
    except Exception:
        pass


# =====================================================
# START
# =====================================================

async def show_user_home(message: Message):
    user_id = message.from_user.id

    if is_banned(user_id):
        await message.answer("🚫 Siz botdan foydalanish huquqidan mahrum qilingansiz.")
        return

    if not await check_subscription(user_id):
        await message.answer(
            "📢 Botdan foydalanish uchun kanallarga obuna bo'ling:",
            reply_markup=subscription_keyboard()
        )
        return

    referrer = award_referral(user_id)

    if referrer:
        await referral_notice(referrer)

    await message.answer(
        "👋 Xush kelibsiz!\n\nKerakli bo'limni tanlang:",
        reply_markup=user_keyboard()
    )


async def show_admin_home(message: Message):
    await message.answer(
        "🛠 <b>ADMIN PANEL</b>\n\n"
        "Botni boshqarish uchun bo'limni tanlang:",
        reply_markup=admin_keyboard()
    )


@dp.message(CommandStart())
async def start_handler(message: Message, command: CommandObject):
    user_id = message.from_user.id

    referrer_id = None

    if command.args:
        try:
            referrer_id = int(command.args.strip())
        except ValueError:
            pass

    register_user(user_id, referrer_id)

    # ADMIN UCHUN FAQAT ADMIN PANEL
    if user_id == ADMIN_ID:
        await show_admin_home(message)
        return

    await show_user_home(message)


# =====================================================
# OBUNANI TEKSHIRISH TUGMASI
# =====================================================

@dp.callback_query(F.data == "check:sub")
async def check_sub(call: CallbackQuery):
    await call.answer()

    if call.from_user.id == ADMIN_ID:
        await call.message.answer(
            "🛠 ADMIN PANEL",
            reply_markup=admin_keyboard()
        )
        return

    if not await check_subscription(call.from_user.id):
        await call.message.answer(
            "❌ Hali barcha kanallarga obuna bo'lmagansiz.",
            reply_markup=subscription_keyboard()
        )
        return

    referrer = award_referral(call.from_user.id)

    if referrer:
        await referral_notice(referrer)

    await call.message.answer(
        "✅ Obuna tasdiqlandi!",
        reply_markup=user_keyboard()
    )


# =====================================================
# ADMIN PANEL CALLBACKLARI
# =====================================================

@dp.callback_query(F.data.startswith("admin:"))
async def admin_callbacks(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Bu bo'lim faqat admin uchun!", show_alert=True)
        return

    await call.answer()

    parts = call.data.split(":")
    action = parts[1]

    if action == "open":
        await state.clear()
        await call.message.answer(
            "🛠 <b>ADMIN PANEL</b>",
            reply_markup=admin_keyboard()
        )

    elif action == "stats":
        conn = db()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) AS n FROM users")
        users = cur.fetchone()["n"]

        cur.execute("SELECT COUNT(*) AS n FROM orders")
        orders = cur.fetchone()["n"]

        cur.execute("""
            SELECT COALESCE(SUM(balance), 0) AS n FROM users
        """)
        balance = cur.fetchone()["n"]

        cur.execute("""
            SELECT COUNT(*) AS n FROM users WHERE banned=1
        """)
        banned = cur.fetchone()["n"]

        conn.close()

        await call.message.answer(
            "📊 <b>BOT STATISTIKASI</b>\n\n"
            f"👥 Foydalanuvchilar: {users}\n"
            f"📦 Buyurtmalar: {orders}\n"
            f"🚫 Bloklanganlar: {banned}\n"
            f"⭐ Umumiy balans: {balance}",
            reply_markup=back_admin_keyboard()
        )

    elif action == "users":
        conn = db()
        cur = conn.cursor()

        cur.execute("""
            SELECT user_id, balance, banned
            FROM users
            ORDER BY joined_at DESC
            LIMIT 30
        """)

        rows = cur.fetchall()
        conn.close()

        text = "👥 <b>FOYDALANUVCHILAR</b>\n\n"

        for row in rows:
            status = "🚫" if row["banned"] else "✅"
            text += (
                f"{status} <code>{row['user_id']}</code>\n"
                f"Balans: {row['balance']} ⭐\n\n"
            )

        await call.message.answer(
            text if rows else "Foydalanuvchilar yo'q.",
            reply_markup=back_admin_keyboard()
        )

    elif action == "add":
        await call.message.answer(
            "➕ Stars qo'shish:\n"
            "<code>/add USER_ID AMOUNT</code>",
            reply_markup=back_admin_keyboard()
        )

    elif action == "sub":
        await call.message.answer(
            "➖ Stars ayirish:\n"
            "<code>/sub USER_ID AMOUNT</code>",
            reply_markup=back_admin_keyboard()
        )

    elif action == "orders":
        conn = db()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, user_id, amount, status
            FROM orders
            ORDER BY id DESC
            LIMIT 20
        """)

        rows = cur.fetchall()
        conn.close()

        text = "📦 <b>BUYURTMALAR</b>\n\n"

        for row in rows:
            text += (
                f"#{row['id']} | ID: {row['user_id']}\n"
                f"{row['amount']} ⭐ | {row['status']}\n\n"
            )

        await call.message.answer(
            text if rows else "Buyurtmalar yo'q.",
            reply_markup=back_admin_keyboard()
        )

    elif action == "channels":
        await call.message.answer(
            "📢 <b>MAJBURIY KANALLAR</b>\n\n"
            "Quyidagi tugmalar orqali kanallarni boshqaring.",
            reply_markup=channels_keyboard()
        )

    elif action == "addchannel":
        await state.set_state(AdminState.add_channel)

        await call.message.answer(
            "➕ Kanal username'ini yuboring.\n"
            "Masalan: <code>@kanal_nomi</code>\n\n"
            "Bekor qilish: /cancel"
        )

    elif action == "remove":
        if len(parts) != 3:
            return

        try:
            index = int(parts[2])
        except ValueError:
            return

        channels = get_channels()

        if index < 0 or index >= len(channels):
            await call.message.answer("Kanal topilmadi.")
            return

        removed = channels.pop(index)
        save_channels(channels)

        await call.message.answer(
            f"✅ {html.escape(removed)} o'chirildi.",
            reply_markup=channels_keyboard()
        )

    elif action == "broadcast":
        await state.set_state(AdminState.broadcast)

        await call.message.answer(
            "📣 Barcha foydalanuvchilarga yuboriladigan xabarni yozing.\n\n"
            "Bekor qilish: /cancel"
        )

    elif action == "reward":
        reward = get_setting("referral_reward", "2")

        await call.message.answer(
            f"🎁 Hozirgi referal mukofoti: {reward} Stars\n\n"
            "O'zgartirish:\n"
            "<code>/reward MIQDOR</code>",
            reply_markup=back_admin_keyboard()
        )


# =====================================================
# FOYDALANUVCHI MENYUSI
# ADMIN BU MENYUGA KIRMAYDI
# =====================================================

@dp.callback_query(F.data.startswith("user:"))
async def user_callbacks(call: CallbackQuery, state: FSMContext):
    if call.from_user.id == ADMIN_ID:
        await call.answer("Sizga faqat admin panel ochiladi.", show_alert=True)
        await call.message.answer(
            "🛠 <b>ADMIN PANEL</b>",
            reply_markup=admin_keyboard()
        )
        return

    if is_banned(call.from_user.id):
        await call.answer("Siz bloklangansiz.", show_alert=True)
        return

    await call.answer()

    if not await check_subscription(call.from_user.id):
        await call.message.answer(
            "Avval majburiy kanallarga obuna bo'ling.",
            reply_markup=subscription_keyboard()
        )
        return

    action = call.data.split(":")[1]

    if action == "home":
        await call.message.answer(
            "🏠 Bosh menyu:",
            reply_markup=user_keyboard()
        )

    elif action == "profile":
        user = get_user(call.from_user.id)
        balance = user["balance"] if user else 0

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=?",
            (call.from_user.id,)
        )

        referrals = cur.fetchone()["n"]
        conn.close()

        await call.message.answer(
            "👤 <b>MENING HISOBIM</b>\n\n"
            f"🆔 ID: <code>{call.from_user.id}</code>\n"
            f"⭐ Balans: {balance}\n"
            f"👥 Referallar: {referrals}",
            reply_markup=back_user_keyboard()
        )

    elif action == "ref":
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start={call.from_user.id}"
        reward = get_setting("referral_reward", "2")

        await call.message.answer(
            "👥 <b>REFERAL TIZIMI</b>\n\n"
            f"Har bir yangi referal uchun {reward} Stars.\n\n"
            "🔗 Havolangiz:\n"
            f"<code>{link}</code>",
            reply_markup=back_user_keyboard()
        )

    elif action == "buy":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="10 ⭐", callback_data="buy:10"),
                InlineKeyboardButton(text="25 ⭐", callback_data="buy:25")
            ],
            [
                InlineKeyboardButton(text="50 ⭐", callback_data="buy:50"),
                InlineKeyboardButton(text="100 ⭐", callback_data="buy:100")
            ],
            [
                InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="user:home")
            ]
        ])

        await call.message.answer(
            "⭐ Qancha Stars sotib olmoqchisiz?",
            reply_markup=keyboard
        )

    elif action == "gift":
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
                InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="user:home")
            ]
        ])

        await call.message.answer(
            "🎁 Stars yechish uchun miqdorni tanlang:",
            reply_markup=keyboard
        )

    elif action == "orders":
        conn = db()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, amount, status
            FROM orders
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 20
        """, (call.from_user.id,))

        rows = cur.fetchall()
        conn.close()

        text = "📦 <b>BUYURTMALARIM</b>\n\n"

        for row in rows:
            text += (
                f"#{row['id']} — {row['amount']} ⭐\n"
                f"Holati: {html.escape(row['status'])}\n\n"
            )

        await call.message.answer(
            text if rows else "Buyurtmalar yo'q.",
            reply_markup=back_user_keyboard()
        )

    elif action == "history":
        conn = db()
        cur = conn.cursor()

        cur.execute("""
            SELECT amount, description, created_at
            FROM transactions
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 15
        """, (call.from_user.id,))

        rows = cur.fetchall()
        conn.close()

        text = "📜 <b>OPERATSIYALAR TARIXI</b>\n\n"

        for row in rows:
            sign = "+" if row["amount"] > 0 else ""
            text += (
                f"{sign}{row['amount']} ⭐\n"
                f"{html.escape(row['description'] or '')}\n"
                f"{row['created_at']}\n\n"
            )

        await call.message.answer(
            text if rows else "Tarix bo'sh.",
            reply_markup=back_user_keyboard()
        )

    elif action == "guide":
        await call.message.answer(
            "📖 <b>QO'LLANMA</b>\n\n"
            "1. Referal havolangizni do'stlaringizga yuboring.\n"
            "2. Yangi referal uchun mukofot oling.\n"
            "3. Stars sotib olib balansingizni to'ldiring.\n"
            "4. Stars yechish bo'limidan buyurtma yuboring.\n"
            "5. Buyurtmalar holatini kuzating.",
            reply_markup=back_user_keyboard()
        )

    elif action == "support":
        await state.set_state(UserState.support)

        await call.message.answer(
            "💬 Adminga yuboriladigan xabarni yozing.\n"
            "Bekor qilish: /cancel"
        )


# =====================================================
# STARS TO'LOVI
# =====================================================

@dp.callback_query(F.data.startswith("buy:"))
async def buy_stars(call: CallbackQuery):
    if call.from_user.id == ADMIN_ID:
        await call.answer("Admin paneldan foydalaning.", show_alert=True)
        return

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
        description=f"Bot balansiga {amount} Stars qo'shish",
        payload=f"stars_{call.from_user.id}_{amount}",
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(label=f"{amount} Stars", amount=amount)
        ]
    )


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    try:
        parts = query.invoice_payload.split("_")

        valid = (
            len(parts) == 3
            and parts[0] == "stars"
            and int(parts[1]) == query.from_user.id
            and int(parts[2]) in (10, 25, 50, 100)
            and query.currency == "XTR"
            and query.total_amount == int(parts[2])
        )

    except (ValueError, IndexError):
        valid = False

    if valid:
        await query.answer(ok=True)
    else:
        await query.answer(
            ok=False,
            error_message="To'lov ma'lumotlari noto'g'ri."
        )


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment

    if payment.currency != "XTR":
        return

    try:
        parts = payment.invoice_payload.split("_")

        if len(parts) != 3 or parts[0] != "stars":
            return

        uid = int(parts[1])
        amount = int(parts[2])

        if uid != message.from_user.id:
            return

        if amount not in (10, 25, 50, 100):
            return

        if payment.total_amount != amount:
            return

    except (ValueError, IndexError):
        return

    conn = db()
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
            f"⭐ Hisobingizga {amount} Stars qo'shildi.",
            reply_markup=user_keyboard()
        )


# =====================================================
# GIFT BUYURTMALARI
# =====================================================

@dp.callback_query(F.data.startswith("gift:"))
async def gift_request(call: CallbackQuery):
    if call.from_user.id == ADMIN_ID:
        await call.answer("Admin paneldan foydalaning.", show_alert=True)
        return

    await call.answer()

    try:
        amount = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        return

    if amount not in (15, 25, 50, 100):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET balance=balance-?
        WHERE user_id=? AND balance>=?
    """, (amount, call.from_user.id, amount))

    success = cur.rowcount == 1

    if success:
        cur.execute("""
            INSERT INTO orders(user_id, amount, status)
            VALUES(?, ?, 'pending')
        """, (call.from_user.id, amount))

        order_id = cur.lastrowid

        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?, ?, ?)
        """, (
            call.from_user.id,
            -amount,
            f"Buyurtma #{order_id} uchun band qilindi"
        ))

    conn.commit()
    conn.close()

    if not success:
        await call.message.answer(
            "❌ Balansingiz yetarli emas.",
            reply_markup=back_user_keyboard()
        )
        return

    buttons = InlineKeyboardMarkup(inline_keyboard=[
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
        f"✅ Buyurtma #{order_id} yuborildi.\n"
        f"⭐ Miqdor: {amount}",
        reply_markup=back_user_keyboard()
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            "📦 <b>YANGI BUYURTMA</b>\n\n"
            f"Buyurtma: #{order_id}\n"
            f"Foydalanuvchi: <code>{call.from_user.id}</code>\n"
            f"Miqdor: {amount} ⭐",
            reply_markup=buttons
        )
    except Exception:
        logging.exception("Buyurtmani adminga yuborib bo'lmadi")


@dp.callback_query(F.data.startswith("order:"))
async def order_action(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Faqat admin uchun!", show_alert=True)
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

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    )
    order = cur.fetchone()

    if not order or order["status"] != "pending":
        conn.close()
        await call.message.answer("Buyurtma avval ko'rib chiqilgan.")
        return

    user_id = order["user_id"]
    amount = order["amount"]

    if action == "approve":
        cur.execute("""
            UPDATE orders SET status='approved'
            WHERE id=? AND status='pending'
        """, (order_id,))

        user_text = "✅ Buyurtmangiz tasdiqlandi."

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
            """, (
                user_id,
                amount,
                f"Rad etilgan buyurtma #{order_id} qaytarildi"
            ))

        user_text = "❌ Buyurtmangiz rad etildi. Stars balansingizga qaytarildi."

    else:
        conn.close()
        return

    conn.commit()
    conn.close()

    await call.message.answer(f"Buyurtma #{order_id} yangilandi.")

    try:
        await bot.send_message(user_id, user_text)
    except Exception:
        pass


# =====================================================
# SUPPORT
# =====================================================

@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()

    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "Bekor qilindi.",
            reply_markup=admin_keyboard()
        )
    else:
        await message.answer(
            "Bekor qilindi.",
            reply_markup=user_keyboard()
        )


@dp.message(StateFilter(UserState.support))
async def support_message(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await state.clear()
        await message.answer("Admin panel:", reply_markup=admin_keyboard())
        return

    await state.clear()

    try:
        await bot.send_message(
            ADMIN_ID,
            "💬 <b>YANGI MUROJAAT</b>\n"
            f"Foydalanuvchi: <code>{message.from_user.id}</code>\n"
            f"Username: @{html.escape(message.from_user.username or 'yoq')}"
        )

        await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

        await message.answer(
            "✅ Xabaringiz adminga yuborildi.",
            reply_markup=user_keyboard()
        )

    except Exception:
        logging.exception("Support xatosi")
        await message.answer("Xabarni yuborib bo'lmadi.")


# =====================================================
# ADMIN: KANAL QO'SHISH HOLATI
# =====================================================

@dp.message(StateFilter(AdminState.add_channel))
async def admin_channel_input(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    channel = (message.text or "").strip()

    if not channel.startswith("@") or len(channel) < 2:
        await message.answer("Kanalni @username ko'rinishida yuboring.")
        return

    channels = get_channels()

    if channel in channels:
        await message.answer("Bu kanal avval qo'shilgan.")
        return

    channels.append(channel)
    save_channels(channels)

    await state.clear()

    await message.answer(
        f"✅ {html.escape(channel)} qo'shildi.\n"
        "Botni kanalga admin qilib qo'ying.",
        reply_markup=admin_keyboard()
    )


# =====================================================
# ADMIN: XABAR TARQATISH HOLATI
# =====================================================

@dp.message(StateFilter(AdminState.broadcast))
async def admin_broadcast_input(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    text = message.text

    if not text:
        await message.answer("Iltimos, matnli xabar yuboring.")
        return

    await state.clear()

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM users WHERE banned=0")
    users = cur.fetchall()

    conn.close()

    status = await message.answer("📣 Xabar yuborilmoqda...")

    sent = 0
    failed = 0

    for row in users:
        try:
            await bot.send_message(row["user_id"], text)
            sent += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    await status.edit_text(
        "✅ <b>YUBORISH YAKUNLANDI</b>\n\n"
        f"Yuborildi: {sent}\n"
        f"Yuborilmadi: {failed}",
        reply_markup=admin_keyboard()
    )


# =====================================================
# ADMIN BUYRUQLARI
# =====================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "🛠 <b>ADMIN PANEL</b>",
        reply_markup=admin_keyboard()
    )


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

    if not get_user(user_id):
        await message.answer("Foydalanuvchi topilmadi.")
        return

    change_balance(user_id, amount, "Admin tomonidan qo'shildi")

    await message.answer("✅ Stars qo'shildi.")

    try:
        await bot.send_message(
            user_id,
            f"🎉 Hisobingizga {amount} Stars qo'shildi."
        )
    except Exception:
        pass


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

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users SET balance=balance-?
        WHERE user_id=? AND balance>=?
    """, (amount, user_id, amount))

    success = cur.rowcount == 1

    if success:
        cur.execute("""
            INSERT INTO transactions(user_id, amount, description)
            VALUES(?, ?, ?)
        """, (user_id, -amount, "Admin tomonidan ayirildi"))

    conn.commit()
    conn.close()

    await message.answer(
        "✅ Stars ayirildi." if success
        else "Foydalanuvchi topilmadi yoki balans yetarli emas."
    )


@dp.message(Command("ban"))
async def ban_command(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        user_id = int(command.args.strip())
    except Exception:
        await message.answer("Foydalanish: /ban USER_ID")
        return

    if user_id == ADMIN_ID:
        await message.answer("Adminni bloklab bo'lmaydi.")
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE users SET banned=1 WHERE user_id=?",
        (user_id,)
    )

    updated = cur.rowcount == 1
    conn.commit()
    conn.close()

    await message.answer(
        "🚫 Foydalanuvchi bloklandi."
        if updated else "Foydalanuvchi topilmadi."
    )


@dp.message(Command("unban"))
async def unban_command(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        user_id = int(command.args.strip())
    except Exception:
        await message.answer("Foydalanish: /unban USER_ID")
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE users SET banned=0 WHERE user_id=?",
        (user_id,)
    )

    updated = cur.rowcount == 1
    conn.commit()
    conn.close()

    await message.answer(
        "✅ Blokdan chiqarildi."
        if updated else "Foydalanuvchi topilmadi."
    )


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

    set_setting("referral_reward", amount)

    await message.answer(
        f"✅ Referal mukofoti {amount} Stars qilib o'zgartirildi."
    )


@dp.message(Command("channel"))
async def channel_command(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    channel = (command.args or "").strip()

    if not channel.startswith("@") or len(channel) < 2:
        await message.answer("Foydalanish: /channel @kanal")
        return

    channels = get_channels()

    if channel in channels:
        await message.answer("Bu kanal allaqachon qo'shilgan.")
        return

    channels.append(channel)
    save_channels(channels)

    await message.answer(f"✅ {html.escape(channel)} qo'shildi.")


@dp.message(Command("removechannel"))
async def remove_channel_command(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    channel = (command.args or "").strip()
    channels = get_channels()

    if channel not in channels:
        await message.answer("Kanal ro'yxatda topilmadi.")
        return

    channels.remove(channel)
    save_channels(channels)

    await message.answer(f"✅ {html.escape(channel)} o'chirildi.")


@dp.message(Command("channels"))
async def channels_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    channels = get_channels()

    await message.answer(
        "📢 <b>MAJBURIY KANALLAR</b>\n\n" +
        ("\n".join(html.escape(x) for x in channels) if channels else "Kanallar yo'q.")
    )


@dp.message(Command("broadcast"))
async def broadcast_command(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args:
        await message.answer("Foydalanish: /broadcast XABAR")
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM users WHERE banned=0")
    users = cur.fetchall()

    conn.close()

    sent = 0
    failed = 0

    for row in users:
        try:
            await bot.send_message(row["user_id"], command.args)
            sent += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    await message.answer(
        f"📣 Yuborish yakunlandi.\n"
        f"Yuborildi: {sent}\n"
        f"Xato: {failed}"
    )


# =====================================================
# RENDER HEALTH SERVER
# =====================================================

async def health(request):
    return web.Response(text="Bot ishlayapti!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    logging.info("Health server ishga tushdi: %s", PORT)
    return runner


# =====================================================
# MAIN
# =====================================================

async def main():
    init_db()
    runner = await start_web_server()

    try:
        logging.info("Bot ishga tushdi.")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
