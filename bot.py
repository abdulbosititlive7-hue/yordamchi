import asyncio
import html
import logging
import os
import random
import re
import sqlite3
from datetime import datetime, date

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, PreCheckoutQuery, LabeledPrice,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# =====================================================
# 1. SOZLAMALAR
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5200398952"))
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")
PORT = int(os.getenv("PORT", "10000"))

REFERRAL_BONUS = 2
DAILY_BONUS = 1
MIN_WITHDRAW = 10
STARS_PACKAGE = 10

# 3 TA STIKER TOPLAMI
STICKER_SETS = [
    "t.me/addemoji/gifts_emoji_by_gifts_changes_bot",
    "t.me/addemoji/NewsEmoji",
    "t.me/addemoji/premium_sticker_by_tolib_by_TgEmodziBot",
]

logging.basicConfig(level=logging.INFO)

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())


# =====================================================
# 2. BAZA
# =====================================================

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")

db.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    balance INTEGER DEFAULT 0,
    referrer_id INTEGER DEFAULT 0,
    joined TEXT,
    banned INTEGER DEFAULT 0,
    last_daily TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS channels (
    channel TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS ad_channels (
    channel TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    status TEXT DEFAULT 'pending',
    created TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    description TEXT,
    status TEXT DEFAULT 'new',
    created TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    charge_id TEXT UNIQUE,
    amount INTEGER,
    created TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY COLLATE NOCASE,
    reward INTEGER NOT NULL,
    active INTEGER DEFAULT 1,
    created TEXT
);

CREATE TABLE IF NOT EXISTS promo_uses (
    code TEXT COLLATE NOCASE,
    user_id INTEGER,
    used_at TEXT,
    PRIMARY KEY(code, user_id)
);
""")
db.commit()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def user_get(user_id):
    return db.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()


def balance_get(user_id):
    user = user_get(user_id)
    return user["balance"] if user else 0


def balance_change(user_id, amount):
    db.execute(
        "UPDATE users SET balance=balance+? WHERE user_id=?",
        (amount, user_id)
    )
    db.commit()


def setting_get(key, default):
    row = db.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    return row["value"] if row else str(default)


def setting_set(key, value):
    db.execute(
        "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
        (key, str(value))
    )
    db.commit()


def register_user(user_id, username, referrer=0):
    old = user_get(user_id)

    if old:
        db.execute(
            "UPDATE users SET username=? WHERE user_id=?",
            (username or "", user_id)
        )
        db.commit()
        return False

    if referrer == user_id or not user_get(referrer):
        referrer = 0

    db.execute("""
        INSERT INTO users(user_id,username,balance,referrer_id,joined)
        VALUES(?,?,0,?,?)
    """, (user_id, username or "", referrer, now()))
    db.commit()

    if referrer:
        bonus = int(setting_get("referral_bonus", REFERRAL_BONUS))
        balance_change(referrer, bonus)

        try:
            asyncio.create_task(
                bot.send_message(
                    referrer,
                    f"🎉 Yangi referal!\n🎁 Bonus: {bonus} Stars"
                )
            )
        except RuntimeError:
            pass

    return True


# =====================================================
# 3. HOLATLAR
# =====================================================

class UserState(StatesGroup):
    withdraw = State()
    support = State()
    order = State()
    promo = State()


class AdminState(StatesGroup):
    broadcast = State()
    ad_text = State()
    add_ad_channel = State()
    remove_ad_channel = State()
    add_sub_channel = State()
    remove_sub_channel = State()
    balance = State()
    ban = State()
    reply = State()
    promo_create = State()
    promo_delete = State()
    referral_bonus = State()


# =====================================================
# 4. MENYULAR
# =====================================================

def user_keyboard(user_id):
    rows = [
        [
            KeyboardButton(text="👤 Mening hisobim"),
            KeyboardButton(text="👥 Referal")
        ],
        [
            KeyboardButton(text="⭐ Stars sotib olish"),
            KeyboardButton(text="🎟 Promo-kod")
        ],
        [
            KeyboardButton(text="🎁 Premium stikerlar"),
            KeyboardButton(text="🎁 Kunlik bonus")
        ],
        [
            KeyboardButton(text="💳 Pul yechish"),
            KeyboardButton(text="📦 Buyurtmalarim")
        ],
        [
            KeyboardButton(text="🛒 Buyurtma berish"),
            KeyboardButton(text="🏆 Referal reytingi")
        ],
        [
            KeyboardButton(text="📖 Qo‘llanma"),
            KeyboardButton(text="✉️ Adminga murojaat")
        ]
    ]

    if user_id == ADMIN_ID:
        rows.append([KeyboardButton(text="⚙️ Admin panel")])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True
    )


def admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Statistika"),
                KeyboardButton(text="👥 Foydalanuvchilar")
            ],
            [
                KeyboardButton(text="🔎 Foydalanuvchini qidirish"),
                KeyboardButton(text="💰 Balans boshqarish")
            ],
            [
                KeyboardButton(text="📢 Reklama tarqatish"),
                KeyboardButton(text="📣 Kanallarga reklama")
            ],
            [
                KeyboardButton(text="➕ Reklama kanali qo‘shish"),
                KeyboardButton(text="➖ Reklama kanali o‘chirish")
            ],
            [
                KeyboardButton(text="➕ Obuna kanali qo‘shish"),
                KeyboardButton(text="➖ Obuna kanali o‘chirish")
            ],
            [
                KeyboardButton(text="🎟 Promo-kod yaratish"),
                KeyboardButton(text="🗑 Promo-kod o‘chirish")
            ],
            [
                KeyboardButton(text="📈 Promo-kod statistikasi"),
                KeyboardButton(text="🎁 Referal bonusini sozlash")
            ],
            [
                KeyboardButton(text="🚫 Bloklash"),
                KeyboardButton(text="📦 Buyurtmalar")
            ],
            [
                KeyboardButton(text="💳 Pul yechish so‘rovlari"),
                KeyboardButton(text="🔙 Foydalanuvchi menyusi")
            ]
        ],
        resize_keyboard=True
    )


def is_admin(user_id):
    return user_id == ADMIN_ID


# =====================================================
# 5. OBUNA
# =====================================================

async def subscription_ok(user_id):
    rows = db.execute(
        "SELECT channel FROM channels"
    ).fetchall()

    for row in rows:
        try:
            member = await bot.get_chat_member(
                row["channel"], user_id
            )
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False

    return True


async def show_subscription(message):
    rows = db.execute(
        "SELECT channel FROM channels"
    ).fetchall()

    buttons = []

    for row in rows:
        channel = row["channel"]
        username = channel.replace("@", "")

        buttons.append([
            InlineKeyboardButton(
                text=f"📢 {channel}",
                url=f"https://t.me/{username}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    await message.answer(
        "Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# =====================================================
# 6. START
# =====================================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    referrer = 0
    parts = message.text.split(maxsplit=1)

    if len(parts) > 1 and parts[1].isdigit():
        referrer = int(parts[1])

    register_user(
        message.from_user.id,
        message.from_user.username,
        referrer
    )

    user = user_get(message.from_user.id)

    if user["banned"]:
        await message.answer("🚫 Siz botdan bloklangansiz.")
        return

    if not await subscription_ok(message.from_user.id):
        await show_subscription(message)
        return

    if is_admin(message.from_user.id):
        await message.answer(
            "👑 Admin panelga xush kelibsiz!",
            reply_markup=admin_keyboard()
        )
    else:
        await message.answer(
            "👋 Xush kelibsiz! Menyudan kerakli bo‘limni tanlang.",
            reply_markup=user_keyboard(message.from_user.id)
        )


@dp.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery):
    if await subscription_ok(call.from_user.id):
        await call.message.answer(
            "✅ Obuna tasdiqlandi!",
            reply_markup=user_keyboard(call.from_user.id)
        )
        await call.answer("Tasdiqlandi!")
    else:
        await call.answer(
            "Barcha kanallarga obuna bo‘ling!",
            show_alert=True
        )


# =====================================================
# 7. HISOB
# =====================================================

@dp.message(F.text == "👤 Mening hisobim")
async def account(message: Message):
    user = user_get(message.from_user.id)

    if not user:
        return

    referrals = db.execute(
        "SELECT COUNT(*) AS n FROM users WHERE referrer_id=?",
        (message.from_user.id,)
    ).fetchone()["n"]

    await message.answer(
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Username: @{html.escape(user['username'] or 'yo‘q')}\n"
        f"💰 Balans: <b>{user['balance']} Stars</b>\n"
        f"👥 Referallar: {referrals}\n"
        f"📅 Sana: {user['joined']}"
    )


# =====================================================
# 8. REFERAL
# =====================================================

@dp.message(F.text == "👥 Referal")
async def referral(message: Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"

    count = db.execute(
        "SELECT COUNT(*) AS n FROM users WHERE referrer_id=?",
        (message.from_user.id,)
    ).fetchone()["n"]

    bonus = int(setting_get("referral_bonus", REFERRAL_BONUS))

    await message.answer(
        "👥 <b>REFERAL TIZIMI</b>\n\n"
        f"🔗 Havolangiz:\n<code>{link}</code>\n\n"
        f"👤 Taklif qilganlar: {count}\n"
        f"🎁 Har bir referal: {bonus} Stars"
    )


@dp.message(F.text == "🏆 Referal reytingi")
async def referral_rating(message: Message):
    rows = db.execute("""
        SELECT u.user_id,u.username,COUNT(r.user_id) AS total
        FROM users u
        LEFT JOIN users r ON r.referrer_id=u.user_id
        GROUP BY u.user_id
        ORDER BY total DESC
        LIMIT 10
    """).fetchall()

    text = "🏆 <b>TOP 10 REFERAL</b>\n\n"

    for index, row in enumerate(rows, 1):
        text += (
            f"{index}. @{html.escape(row['username'] or 'user')}"
            f" — {row['total']} ta\n"
        )

    await message.answer(text)


# =====================================================
# 9. PROMO-KODNI ISHLATISH
# =====================================================

@dp.message(F.text == "🎟 Promo-kod")
async def promo_start(message: Message, state: FSMContext):
    await state.set_state(UserState.promo)
    await message.answer("🎟 Promo-kodni yuboring:")


@dp.message(UserState.promo)
async def promo_redeem(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()

    if not re.fullmatch(r"[A-Z0-9_-]{3,40}", code):
        await message.answer("Promo-kod formati noto‘g‘ri.")
        return

    promo = db.execute(
        "SELECT * FROM promo_codes WHERE code=? COLLATE NOCASE",
        (code,)
    ).fetchone()

    if not promo or not promo["active"]:
        await message.answer("❌ Promo-kod noto‘g‘ri yoki faol emas.")
        await state.clear()
        return

    try:
        db.execute(
            "INSERT INTO promo_uses(code,user_id,used_at) VALUES(?,?,?)",
            (promo["code"], message.from_user.id, now())
        )
        db.commit()
    except sqlite3.IntegrityError:
        await message.answer("❌ Siz bu promo-kodni avval ishlatgansiz.")
        await state.clear()
        return

    balance_change(message.from_user.id, promo["reward"])

    await message.answer(
        f"🎉 Promo-kod qabul qilindi!\n"
        f"🎁 Mukofot: {promo['reward']} Stars\n"
        f"💰 Yangi balans: {balance_get(message.from_user.id)} Stars"
    )

    await state.clear()


# =====================================================
# 10. KUNLIK BONUS
# =====================================================

@dp.message(F.text == "🎁 Kunlik bonus")
async def daily_bonus(message: Message):
    user = user_get(message.from_user.id)
    today = date.today().isoformat()

    if user["last_daily"] == today:
        await message.answer("⏳ Bugungi bonusni olib bo‘lgansiz. Ertaga qayting!")
        return

    reward = DAILY_BONUS

    db.execute(
        "UPDATE users SET balance=balance+?,last_daily=? WHERE user_id=?",
        (reward, today, message.from_user.id)
    )
    db.commit()

    await message.answer(
        f"🎉 Kunlik bonus olindi!\n"
        f"🎁 +{reward} Stars\n"
        f"💰 Balans: {balance_get(message.from_user.id)} Stars"
    )


# =====================================================
# 11. STIKERLAR
# =====================================================

def sticker_set_name(link):
    link = link.strip()

    if "addstickers/" in link:
        return link.split("addstickers/", 1)[1].split("?")[0].strip("/")

    return link


@dp.message(F.text == "🎁 Premium stikerlar")
async def sticker_menu(message: Message):
    buttons = [
        [InlineKeyboardButton(
            text=f"🎁 Stikerlar to‘plami {i + 1}",
            callback_data=f"sticker:{i}"
        )]
        for i in range(3)
    ]

    await message.answer(
        "Stikerlar to‘plamini tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("sticker:"))
async def sticker_send(call: CallbackQuery):
    try:
        index = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        await call.answer("Noto‘g‘ri so‘rov.", show_alert=True)
        return

    if index not in range(3):
        await call.answer("To‘plam topilmadi.", show_alert=True)
        return

    name = sticker_set_name(STICKER_SETS[index])

    if not name or "TOPLAM_" in name:
        await call.answer("Stiker havolasini kodda to‘ldiring.", show_alert=True)
        return

    await call.answer("Stikerlar olinmoqda...")

    try:
        sticker_set = await bot.get_sticker_set(name=name)
        stickers = list(sticker_set.stickers)

        if not stickers:
            await call.message.answer("To‘plamda stiker yo‘q.")
            return

        selected = random.sample(stickers, min(5, len(stickers)))

        await call.message.answer(
            f"🎁 <b>{html.escape(sticker_set.title)}</b>\n"
            f"Jami: {len(stickers)} ta stiker"
        )

        for sticker in selected:
            await bot.send_sticker(
                call.from_user.id,
                sticker.file_id
            )
            await asyncio.sleep(0.3)

    except TelegramBadRequest:
        await call.message.answer(
            "❌ To‘plam olinmadi. Havolani tekshiring. "
            "Ba’zi Premium to‘plamlar bot uchun ochiq emas."
        )
    except Exception:
        logging.exception("Sticker error")
        await call.message.answer("Stiker yuborishda xatolik.")


# =====================================================
# 12. STARS TO‘LOVI
# =====================================================

@dp.message(F.text == "⭐ Stars sotib olish")
async def buy_stars(message: Message):
    await bot.send_invoice(
        chat_id=message.chat.id,
        title=f"{STARS_PACKAGE} Stars",
        description="Bot ichidagi hisobni to‘ldirish",
        payload=f"account:{message.from_user.id}:{STARS_PACKAGE}",
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label=f"{STARS_PACKAGE} Stars",
                amount=STARS_PACKAGE
            )
        ]
    )


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def payment_success(message: Message):
    payment = message.successful_payment

    if payment.currency != "XTR":
        return

    try:
        prefix, uid, amount = payment.invoice_payload.split(":")
        uid = int(uid)
        amount = int(amount)
    except (ValueError, AttributeError):
        return

    if prefix != "account" or uid != message.from_user.id:
        return

    try:
        db.execute("""
            INSERT INTO payments(user_id,charge_id,amount,created)
            VALUES(?,?,?,?)
        """, (
            uid,
            payment.telegram_payment_charge_id,
            amount,
            now()
        ))
        db.commit()
    except sqlite3.IntegrityError:
        await message.answer("Bu to‘lov oldin hisobga qo‘shilgan.")
        return

    balance_change(uid, amount)

    await message.answer(
        f"✅ To‘lov muvaffaqiyatli!\n"
        f"💰 +{amount} Stars\n"
        f"Yangi balans: {balance_get(uid)} Stars"
    )

    await bot.send_message(
        ADMIN_ID,
        f"💳 To‘lov: {uid} — {amount} Stars"
    )


# =====================================================
# 13. PUL YECHISH
# =====================================================

@dp.message(F.text == "💳 Pul yechish")
async def withdraw_start(message: Message, state: FSMContext):
    await state.set_state(UserState.withdraw)
    await message.answer(
        f"Yechish miqdorini yuboring. Minimal: {MIN_WITHDRAW} Stars."
    )


@dp.message(UserState.withdraw)
async def withdraw_submit(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Faqat raqam yuboring.")
        return

    amount = int(message.text)

    if amount < MIN_WITHDRAW:
        await message.answer(f"Minimal miqdor {MIN_WITHDRAW} Stars.")
        return

    if balance_get(message.from_user.id) < amount:
        await message.answer("Balansingiz yetarli emas.")
        return

    db.execute("""
        INSERT INTO withdrawals(user_id,amount,created)
        VALUES(?,?,?)
    """, (message.from_user.id, amount, now()))
    db.commit()

    request_id = db.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    balance_change(message.from_user.id, -amount)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Tasdiqlash",
            callback_data=f"wd_yes:{request_id}"
        ),
        InlineKeyboardButton(
            text="❌ Rad etish",
            callback_data=f"wd_no:{request_id}"
        )
    ]])

    await bot.send_message(
        ADMIN_ID,
        f"💳 <b>PUL YECHISH SO‘ROVI</b>\n"
        f"ID: {request_id}\n"
        f"User: {message.from_user.id}\n"
        f"Miqdor: {amount} Stars",
        reply_markup=keyboard
    )

    await message.answer("✅ So‘rov adminga yuborildi.")
    await state.clear()


@dp.callback_query(F.data.startswith("wd_yes:"))
async def withdraw_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    request_id = int(call.data.split(":")[1])

    cursor = db.execute("""
        UPDATE withdrawals SET status='approved'
        WHERE id=? AND status='pending'
    """, (request_id,))
    db.commit()

    if cursor.rowcount == 0:
        await call.answer("So‘rov oldin ko‘rib chiqilgan.")
        return

    row = db.execute(
        "SELECT * FROM withdrawals WHERE id=?",
        (request_id,)
    ).fetchone()

    await bot.send_message(
        row["user_id"],
        f"✅ {row['amount']} Stars so‘rovingiz tasdiqlandi."
    )

    await call.message.edit_text("✅ So‘rov tasdiqlandi.")
    await call.answer()


@dp.callback_query(F.data.startswith("wd_no:"))
async def withdraw_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    request_id = int(call.data.split(":")[1])

    cursor = db.execute("""
        UPDATE withdrawals SET status='rejected'
        WHERE id=? AND status='pending'
    """, (request_id,))
    db.commit()

    if cursor.rowcount == 0:
        await call.answer("So‘rov oldin ko‘rib chiqilgan.")
        return

    row = db.execute(
        "SELECT * FROM withdrawals WHERE id=?",
        (request_id,)
    ).fetchone()

    balance_change(row["user_id"], row["amount"])

    await bot.send_message(
        row["user_id"],
        f"❌ So‘rov rad etildi. {row['amount']} Stars qaytarildi."
    )

    await call.message.edit_text("❌ So‘rov rad etildi.")
    await call.answer()


# =====================================================
# 14. BUYURTMALAR
# =====================================================

@dp.message(F.text == "🛒 Buyurtma berish")
async def order_start(message: Message, state: FSMContext):
    await state.set_state(UserState.order)
    await message.answer("Buyurtmangiz tavsifini yuboring:")


@dp.message(UserState.order)
async def order_submit(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Buyurtma matnini yuboring.")
        return

    description = message.text[:1000]

    db.execute("""
        INSERT INTO orders(user_id,description,created)
        VALUES(?,?,?)
    """, (message.from_user.id, description, now()))
    db.commit()

    order_id = db.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    await message.answer(f"✅ Buyurtma qabul qilindi. ID: {order_id}")

    await bot.send_message(
        ADMIN_ID,
        f"🛒 Yangi buyurtma #{order_id}\n"
        f"User: {message.from_user.id}\n"
        f"Tavsif: {html.escape(description)}"
    )

    await state.clear()


@dp.message(F.text == "📦 Buyurtmalarim")
async def user_orders(message: Message):
    rows = db.execute("""
        SELECT * FROM orders
        WHERE user_id=?
        ORDER BY id DESC LIMIT 20
    """, (message.from_user.id,)).fetchall()

    if not rows:
        await message.answer("Buyurtmalar mavjud emas.")
        return

    text = "📦 <b>BUYURTMALARIM</b>\n\n"

    for row in rows:
        text += (
            f"#{row['id']} — {html.escape(row['description'])}\n"
            f"Holat: {row['status']}\n"
            f"Sana: {row['created']}\n\n"
        )

    await message.answer(text)


# =====================================================
# 15. QO‘LLANMA VA SUPPORT
# =====================================================

@dp.message(F.text == "📖 Qo‘llanma")
async def guide(message: Message):
    await message.answer(
        "📖 <b>QO‘LLANMA</b>\n\n"
        "👤 Hisob — balansingiz.\n"
        "👥 Referal — taklif havolangiz.\n"
        "⭐ Stars — hisobni to‘ldirish.\n"
        "🎟 Promo-kod — kod orqali bonus olish.\n"
        "🎁 Kunlik bonus — har kuni mukofot.\n"
        "🎁 Stikerlar — 3 ta stiker to‘plami.\n"
        "💳 Pul yechish — admin ko‘rib chiqadigan so‘rov.\n"
        "🛒 Buyurtma — xizmat so‘rovi."
    )


@dp.message(F.text == "✉️ Adminga murojaat")
async def support_start(message: Message, state: FSMContext):
    await state.set_state(UserState.support)
    await message.answer("Xabaringizni yuboring:")


@dp.message(UserState.support)
async def support_send(message: Message, state: FSMContext):
    await bot.send_message(
        ADMIN_ID,
        f"✉️ Murojaat\n"
        f"User: {message.from_user.id}\n"
        f"Username: @{html.escape(message.from_user.username or 'yo‘q')}\n"
        f"Javob: /reply {message.from_user.id}"
    )

    await bot.copy_message(
        ADMIN_ID,
        message.chat.id,
        message.message_id
    )

    await message.answer("✅ Xabar adminga yuborildi.")
    await state.clear()


@dp.message(Command("reply"))
async def reply_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /reply USER_ID")
        return

    await state.set_state(AdminState.reply)
    await state.update_data(reply_user=int(parts[1]))
    await message.answer("Javob matnini yoki rasmini yuboring:")


@dp.message(AdminState.reply)
async def reply_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()

    try:
        await bot.copy_message(
            data["reply_user"],
            message.chat.id,
            message.message_id
        )
        await message.answer("✅ Javob yuborildi.")
    except Exception:
        await message.answer("❌ Xabar yuborilmadi.")

    await state.clear()


# =====================================================
# 16. ADMIN PANEL
# =====================================================

@dp.message(F.text == "⚙️ Admin panel")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "👑 <b>ADMIN PANEL</b>",
        reply_markup=admin_keyboard()
    )


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "👑 Admin panel",
        reply_markup=admin_keyboard()
    )


@dp.message(F.text == "🔙 Foydalanuvchi menyusi")
async def back_user_menu(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "Foydalanuvchi menyusi:",
        reply_markup=user_keyboard(message.from_user.id)
    )


# =====================================================
# 17. PROMO-KOD YARATISH
# =====================================================

@dp.message(F.text == "🎟 Promo-kod yaratish")
async def promo_create_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.promo_create)

    await message.answer(
        "Yangi promo-kodni quyidagi formatda yuboring:\n\n"
        "<code>KOD STARS</code>\n\n"
        "Misol: <code>WELCOME50 50</code>\n"
        "Bu kodni ishlatgan har bir yangi foydalanuvchiga 50 Stars beriladi."
    )


@dp.message(AdminState.promo_create)
async def promo_create_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").strip().split()

    if len(parts) != 2:
        await message.answer("Format: KOD STARS")
        return

    code = parts[0].upper()

    if not re.fullmatch(r"[A-Z0-9_-]{3,40}", code):
        await message.answer(
            "Kod 3–40 belgidan iborat bo‘lsin. "
            "Faqat lotin harflari, raqam, _ va - ishlating."
        )
        return

    try:
        reward = int(parts[1])
    except ValueError:
        await message.answer("Stars miqdori son bo‘lishi kerak.")
        return

    if reward < 1 or reward > 100000:
        await message.answer("Mukofot 1 dan 100000 gacha bo‘lishi kerak.")
        return

    try:
        db.execute("""
            INSERT INTO promo_codes(code,reward,active,created)
            VALUES(?,?,1,?)
        """, (code, reward, now()))
        db.commit()
    except sqlite3.IntegrityError:
        await message.answer("❌ Bu promo-kod oldin yaratilgan.")
        return

    await message.answer(
        f"✅ Promo-kod yaratildi!\n\n"
        f"🎟 Kod: <code>{code}</code>\n"
        f"🎁 Mukofot: {reward} Stars\n"
        f"♾ Har bir foydalanuvchi bir marta ishlata oladi."
    )

    await state.clear()


# =====================================================
# 18. PROMO-KOD O‘CHIRISH
# =====================================================

@dp.message(F.text == "🗑 Promo-kod o‘chirish")
async def promo_delete_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.promo_delete)
    await message.answer("O‘chiriladigan promo-kod nomini yuboring:")


@dp.message(AdminState.promo_delete)
async def promo_delete_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    code = (message.text or "").strip().upper()

    cursor = db.execute(
        "UPDATE promo_codes SET active=0 WHERE code=? COLLATE NOCASE",
        (code,)
    )
    db.commit()

    if cursor.rowcount:
        await message.answer("✅ Promo-kod o‘chirildi (faolsizlantirildi).")
    else:
        await message.answer("Bunday promo-kod topilmadi.")

    await state.clear()


# =====================================================
# 19. PROMO-KOD STATISTIKASI
# =====================================================

@dp.message(F.text == "📈 Promo-kod statistikasi")
async def promo_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute("""
        SELECT p.code,p.reward,p.active,COUNT(u.user_id) AS used
        FROM promo_codes p
        LEFT JOIN promo_uses u ON u.code=p.code
        GROUP BY p.code
        ORDER BY p.created DESC
    """).fetchall()

    if not rows:
        await message.answer("Promo-kodlar hali yaratilmagan.")
        return

    text = "📈 <b>PROMO-KOD STATISTIKASI</b>\n\n"

    for row in rows:
        text += (
            f"🎟 <code>{html.escape(row['code'])}</code>\n"
            f"🎁 Mukofot: {row['reward']} Stars\n"
            f"👥 Ishlatilgan: {row['used']} marta\n"
            f"Holat: {'Faol' if row['active'] else 'O‘chirilgan'}\n\n"
        )

    await message.answer(text)


# =====================================================
# 20. KANALLARGA REKLAMA
# =====================================================

@dp.message(F.text == "📣 Kanallarga reklama")
async def channel_ad_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channels = db.execute(
        "SELECT channel FROM ad_channels"
    ).fetchall()

    if not channels:
        await message.answer(
            "Reklama kanallari ro‘yxati bo‘sh.\n"
            "Avval «➕ Reklama kanali qo‘shish» tugmasidan kanal qo‘shing."
        )
        return

    await state.set_state(AdminState.ad_text)

    await message.answer(
        f"📣 Reklama yuboriladigan kanallar: {len(channels)} ta.\n\n"
        "Endi faqat reklama MATNINI yuboring.\n"
        "Bot shu matnni barcha saqlangan reklama kanallariga yuboradi.\n"
        "Bekor qilish: /cancel"
    )


@dp.message(AdminState.ad_text)
async def channel_ad_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.strip():
        await message.answer("Iltimos, reklama matnini yuboring.")
        return

    ad_text = message.text.strip()

    if len(ad_text) > 4096:
        await message.answer("Reklama matni 4096 belgidan oshmasligi kerak.")
        return

    channels = db.execute(
        "SELECT channel FROM ad_channels"
    ).fetchall()

    sent = 0
    failed = []

    status = await message.answer("📣 Reklama kanallarga yuborilmoqda...")

    for row in channels:
        channel = row["channel"]

        try:
            await bot.send_message(
                chat_id=channel,
                text=html.escape(ad_text),
                parse_mode=ParseMode.HTML
            )
            sent += 1
        except Exception as error:
            logging.warning("Reklama %s ga yuborilmadi: %s", channel, error)
            failed.append(channel)

        await asyncio.sleep(0.1)

    result = (
        f"✅ <b>KANAL REKLAMASI YAKUNLANDI</b>\n\n"
        f"📨 Muvaffaqiyatli: {sent}\n"
        f"❌ Xatolik: {len(failed)}"
    )

    if failed:
        result += "\n\nYuborilmagan kanallar:\n"
        result += "\n".join(html.escape(x) for x in failed[:20])

    await status.edit_text(result)
    await state.clear()


# =====================================================
# 21. REKLAMA KANALI QO‘SHISH
# =====================================================

@dp.message(F.text == "➕ Reklama kanali qo‘shish")
async def ad_channel_add_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.add_ad_channel)
    await message.answer(
        "Reklama kanali username yoki ID sini yuboring.\n"
        "Masalan: @kanal_nomi"
    )


@dp.message(AdminState.add_ad_channel)
async def ad_channel_add_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channel = (message.text or "").strip()

    if not channel:
        await message.answer("Kanal username yoki ID yuboring.")
        return

    try:
        chat = await bot.get_chat(channel)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)

        if member.status not in ("administrator", "creator"):
            await message.answer(
                "Bot bu kanalda administrator emas. "
                "Avval botni kanalga administrator qilib qo‘shing."
            )
            await state.clear()
            return

        db.execute(
            "INSERT OR IGNORE INTO ad_channels(channel) VALUES(?)",
            (str(chat.id),)
        )
        db.commit()

        await message.answer(
            f"✅ Reklama kanali qo‘shildi:\n"
            f"{html.escape(chat.title or str(chat.id))}\n"
            f"ID: <code>{chat.id}</code>"
        )

    except Exception as error:
        logging.warning("Ad channel add error: %s", error)
        await message.answer(
            "❌ Kanalni tekshirib bo‘lmadi. "
            "Bot kanalga administrator qilib qo‘shilganini tekshiring."
        )

    await state.clear()


# =====================================================
# 22. REKLAMA KANALINI O‘CHIRISH
# =====================================================

@dp.message(F.text == "➖ Reklama kanali o‘chirish")
async def ad_channel_remove_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute(
        "SELECT channel FROM ad_channels"
    ).fetchall()

    if not rows:
        await message.answer("Reklama kanallari yo‘q.")
        return

    text = "📣 <b>REKLAMA KANALLARI</b>\n\n"

    for row in rows:
        text += f"<code>{html.escape(row['channel'])}</code>\n"

    await state.set_state(AdminState.remove_ad_channel)
    await message.answer(
        text + "\nO‘chiriladigan kanal ID sini yuboring."
    )


@dp.message(AdminState.remove_ad_channel)
async def ad_channel_remove_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channel = (message.text or "").strip()

    cursor = db.execute(
        "DELETE FROM ad_channels WHERE channel=?",
        (channel,)
    )
    db.commit()

    await message.answer(
        "✅ Kanal o‘chirildi." if cursor.rowcount
        else "Kanal topilmadi."
    )
    await state.clear()


# =====================================================
# 23. MAJBURIY OBUNA KANALLARI
# =====================================================

@dp.message(F.text == "➕ Obuna kanali qo‘shish")
async def sub_add_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.add_sub_channel)
    await message.answer("Majburiy obuna kanali username sini yuboring:")


@dp.message(AdminState.add_sub_channel)
async def sub_add_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channel = (message.text or "").strip()

    try:
        chat = await bot.get_chat(channel)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)

        if member.status not in ("administrator", "creator"):
            await message.answer("Bot avval kanalga administrator bo‘lsin.")
            await state.clear()
            return

        db.execute(
            "INSERT OR IGNORE INTO channels(channel) VALUES(?)",
            (channel,)
        )
        db.commit()

        await message.answer(f"✅ {html.escape(channel)} qo‘shildi.")

    except Exception:
        await message.answer("Kanalni tekshirib bo‘lmadi.")

    await state.clear()


@dp.message(F.text == "➖ Obuna kanali o‘chirish")
async def sub_remove_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute("SELECT channel FROM channels").fetchall()

    if not rows:
        await message.answer("Majburiy obuna kanallari yo‘q.")
        return

    text = "Majburiy kanallar:\n\n"
    for row in rows:
        text += row["channel"] + "\n"

    await state.set_state(AdminState.remove_sub_channel)
    await message.answer(text + "\nO‘chiriladigan kanal username sini yuboring.")


@dp.message(AdminState.remove_sub_channel)
async def sub_remove_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channel = (message.text or "").strip()

    cursor = db.execute(
        "DELETE FROM channels WHERE channel=?",
        (channel,)
    )
    db.commit()

    await message.answer(
        "✅ Kanal o‘chirildi." if cursor.rowcount
        else "Kanal topilmadi."
    )
    await state.clear()


# =====================================================
# 24. FOYDALANUVCHILARGA REKLAMA
# =====================================================

@dp.message(F.text == "📢 Reklama tarqatish")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.broadcast)
    await message.answer(
        "Foydalanuvchilarga yuboriladigan xabarni yuboring.\n"
        "Matn, rasm yoki video bo‘lishi mumkin.\n"
        "Bekor qilish: /cancel"
    )


@dp.message(AdminState.broadcast)
async def broadcast_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    users = db.execute(
        "SELECT user_id FROM users WHERE banned=0"
    ).fetchall()

    sent = 0
    failed = 0

    status = await message.answer("📢 Tarqatish boshlandi...")

    for user in users:
        try:
            await bot.copy_message(
                user["user_id"],
                message.chat.id,
                message.message_id
            )
            sent += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.04)

    await status.edit_text(
        f"✅ Tarqatish yakunlandi.\n"
        f"Yuborildi: {sent}\n"
        f"Xatolik: {failed}"
    )

    await state.clear()


# =====================================================
# 25. BALANS BOSHQARISH
# =====================================================

@dp.message(F.text == "💰 Balans boshqarish")
async def balance_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.balance)
    await message.answer(
        "Format:\n"
        "<code>USER_ID MIQDOR</code>\n"
        "Masalan: <code>123456789 50</code>\n"
        "Ayirish: <code>123456789 -20</code>"
    )


@dp.message(AdminState.balance)
async def balance_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:
        await message.answer("Format: USER_ID MIQDOR")
        return

    try:
        user_id = int(parts[0])
        amount = int(parts[1])
    except ValueError:
        await message.answer("Faqat son kiriting.")
        return

    if not user_get(user_id):
        await message.answer("Foydalanuvchi topilmadi.")
        return

    if balance_get(user_id) + amount < 0:
        await message.answer("Balans manfiy bo‘la olmaydi.")
        return

    balance_change(user_id, amount)

    await message.answer(
        f"✅ Balans yangilandi: {balance_get(user_id)} Stars"
    )

    try:
        await bot.send_message(
            user_id,
            f"💰 Balansingiz o‘zgartirildi: {amount:+} Stars\n"
            f"Yangi balans: {balance_get(user_id)} Stars"
        )
    except Exception:
        pass

    await state.clear()


# =====================================================
# 26. BLOKLASH
# =====================================================

@dp.message(F.text == "🚫 Bloklash")
async def ban_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.ban)
    await message.answer(
        "<code>USER_ID ban</code> — bloklash\n"
        "<code>USER_ID unban</code> — blokdan chiqarish"
    )


@dp.message(AdminState.ban)
async def ban_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:
        await message.answer("Format noto‘g‘ri.")
        return

    try:
        user_id = int(parts[0])
    except ValueError:
        await message.answer("ID noto‘g‘ri.")
        return

    if not user_get(user_id):
        await message.answer("Foydalanuvchi topilmadi.")
        return

    action = parts[1].lower()

    if action not in ("ban", "unban"):
        await message.answer("ban yoki unban yozing.")
        return

    db.execute(
        "UPDATE users SET banned=? WHERE user_id=?",
        (1 if action == "ban" else 0, user_id)
    )
    db.commit()

    await message.answer("✅ Amal bajarildi.")
    await state.clear()


# =====================================================
# 27. STATISTIKA
# =====================================================

@dp.message(F.text == "📊 Statistika")
async def statistics(message: Message):
    if not is_admin(message.from_user.id):
        return

    users = db.execute(
        "SELECT COUNT(*) n FROM users"
    ).fetchone()["n"]

    banned = db.execute(
        "SELECT COUNT(*) n FROM users WHERE banned=1"
    ).fetchone()["n"]

    total_balance = db.execute(
        "SELECT COALESCE(SUM(balance),0) n FROM users"
    ).fetchone()["n"]

    payments = db.execute(
        "SELECT COALESCE(SUM(amount),0) n FROM payments"
    ).fetchone()["n"]

    orders = db.execute(
        "SELECT COUNT(*) n FROM orders"
    ).fetchone()["n"]

    promo_count = db.execute(
        "SELECT COUNT(*) n FROM promo_codes WHERE active=1"
    ).fetchone()["n"]

    await message.answer(
        "📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"🚫 Bloklanganlar: {banned}\n"
        f"💰 Umumiy balans: {total_balance} Stars\n"
        f"💳 To‘lovlar: {payments} Stars\n"
        f"📦 Buyurtmalar: {orders}\n"
        f"🎟 Faol promo-kodlar: {promo_count}"
    )


# =====================================================
# 28. FOYDALANUVCHILAR RO‘YXATI VA QIDIRISH
# =====================================================

@dp.message(F.text == "👥 Foydalanuvchilar")
async def users_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute(
        "SELECT * FROM users ORDER BY joined DESC LIMIT 30"
    ).fetchall()

    if not rows:
        await message.answer("Foydalanuvchilar yo‘q.")
        return

    text = "👥 <b>FOYDALANUVCHILAR</b>\n\n"

    for user in rows:
        text += (
            f"🆔 <code>{user['user_id']}</code>\n"
            f"👤 @{html.escape(user['username'] or 'yo‘q')}\n"
            f"💰 {user['balance']} Stars\n\n"
        )

    await message.answer(text)


@dp.message(F.text == "🔎 Foydalanuvchini qidirish")
async def search_help(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer("Qidirish uchun: /user USER_ID")


@dp.message(Command("user"))
async def search_user(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /user USER_ID")
        return

    user_id = int(parts[1])
    user = user_get(user_id)

    if not user:
        await message.answer("Foydalanuvchi topilmadi.")
        return

    referrals = db.execute(
        "SELECT user_id,username FROM users WHERE referrer_id=?",
        (user_id,)
    ).fetchall()

    text = (
        "👤 <b>FOYDALANUVCHI</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Username: @{html.escape(user['username'] or 'yo‘q')}\n"
        f"Balans: {user['balance']} Stars\n"
        f"Ro‘yxat sanasi: {user['joined']}\n"
        f"Bloklangan: {'Ha' if user['banned'] else 'Yo‘q'}\n"
        f"Referallar: {len(referrals)}\n\n"
        "<b>Taklif qilganlar:</b>\n"
    )

    for ref in referrals[:30]:
        text += (
            f"• <code>{ref['user_id']}</code> "
            f"@{html.escape(ref['username'] or 'yo‘q')}\n"
        )

    await message.answer(text)


# =====================================================
# 29. BUYURTMALAR VA PUL YECHISH RO‘YXATI
# =====================================================

@dp.message(F.text == "📦 Buyurtmalar")
async def admin_orders(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute(
        "SELECT * FROM orders ORDER BY id DESC LIMIT 20"
    ).fetchall()

    if not rows:
        await message.answer("Buyurtmalar yo‘q.")
        return

    text = "📦 <b>OXIRGI BUYURTMALAR</b>\n\n"

    for row in rows:
        text += (
            f"#{row['id']} | User: {row['user_id']}\n"
            f"{html.escape(row['description'])}\n"
            f"Holat: {row['status']}\n\n"
        )

    await message.answer(text)


@dp.message(F.text == "💳 Pul yechish so‘rovlari")
async def admin_withdrawals(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute("""
        SELECT * FROM withdrawals
        WHERE status='pending'
        ORDER BY id DESC LIMIT 20
    """).fetchall()

    if not rows:
        await message.answer("Kutilayotgan so‘rovlar yo‘q.")
        return

    for row in rows:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"wd_yes:{row['id']}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"wd_no:{row['id']}"
            )
        ]])

        await message.answer(
            f"💳 So‘rov #{row['id']}\n"
            f"User: {row['user_id']}\n"
            f"Miqdor: {row['amount']} Stars\n"
            f"Sana: {row['created']}",
            reply_markup=keyboard
        )


# =====================================================
# 30. REFERAL BONUSINI SOZLASH
# =====================================================

@dp.message(F.text == "🎁 Referal bonusini sozlash")
async def referral_bonus_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.referral_bonus)

    await message.answer(
        f"Hozirgi bonus: {setting_get('referral_bonus', REFERRAL_BONUS)} Stars.\n"
        "Yangi miqdorni yuboring:"
    )


@dp.message(AdminState.referral_bonus)
async def referral_bonus_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.isdigit():
        await message.answer("Faqat musbat son yuboring.")
        return

    amount = int(message.text)

    if not 0 <= amount <= 100000:
        await message.answer("Miqdor 0 dan 100000 gacha bo‘lishi kerak.")
        return

    setting_set("referral_bonus", amount)

    await message.answer(f"✅ Referal bonusi {amount} Stars bo‘ldi.")
    await state.clear()


# =====================================================
# 31. BEKOR QILISH
# =====================================================

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()

    keyboard = (
        admin_keyboard()
        if is_admin(message.from_user.id)
        else user_keyboard(message.from_user.id)
    )

    await message.answer(
        "❌ Amal bekor qilindi.",
        reply_markup=keyboard
    )


# =====================================================
# 32. UMUMIY XABAR
# =====================================================

@dp.message()
async def fallback(message: Message):
    user = user_get(message.from_user.id)

    if not user:
        register_user(
            message.from_user.id,
            message.from_user.username
        )
        user = user_get(message.from_user.id)

    if user and user["banned"]:
        await message.answer("🚫 Siz bloklangansiz.")
        return

    if not await subscription_ok(message.from_user.id):
        await show_subscription(message)
        return

    await message.answer(
        "Kerakli bo‘limni menyudan tanlang.",
        reply_markup=user_keyboard(message.from_user.id)
    )


# =====================================================
# 33. RENDER HEALTH SERVER
# =====================================================

async def health(request):
    return web.Response(text="Bot ishlayapti!")


async def run_web():
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


# =====================================================
# 34. ISHGA TUSHIRISH
# =====================================================

async def main():
    if BOT_TOKEN == "TOKENINGIZNI_BU_YERGA":
        raise RuntimeError("BOT_TOKEN ni kiriting!")

    await run_web()

    logging.info("Bot ishga tushdi!")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
