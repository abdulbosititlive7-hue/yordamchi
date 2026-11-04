import asyncio
import html
import logging
import os
import random
import re
import sqlite3
from datetime import datetime

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
MIN_WITHDRAW = 10
STARS_PACKAGE = 10

# 3 TA STIKER TOPLAMI HAVOLASINI SHU YERGA YOZING
STICKER_SETS = [
    "t.me/addemoji/gifts_emoji_by_gifts_changes_bot",
    "t.me/addemoji/Temur_Founder_by_TgEmodziBot",
    "t.me/addemoji/SystemicDuck",
]

logging.basicConfig(level=logging.INFO)

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())


# =====================================================
# 2. MA'LUMOTLAR BAZASI
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
    banned INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS channels (
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
            asyncio.create_task(bot.send_message(
                referrer,
                f"🎉 Siz yangi foydalanuvchini taklif qildingiz!\n"
                f"💰 Bonus: {bonus} Stars"
            ))
        except RuntimeError:
            pass

    return True


# =====================================================
# 3. FSM HOLATLARI
# =====================================================

class UserState(StatesGroup):
    withdraw = State()
    support = State()
    order = State()


class AdminState(StatesGroup):
    broadcast = State()
    channel_target = State()
    channel_content = State()
    add_channel = State()
    remove_channel = State()
    balance = State()
    ban = State()
    reply = State()
    referral_bonus = State()


# =====================================================
# 4. TUGMALAR
# =====================================================

def user_keyboard(user_id):
    rows = [
        [
            KeyboardButton(text="👤 Mening hisobim"),
            KeyboardButton(text="👥 Referal")
        ],
        [
            KeyboardButton(text="⭐ Stars sotib olish"),
            KeyboardButton(text="🎁 Premium stikerlar")
        ],
        [
            KeyboardButton(text="💳 Pul yechish"),
            KeyboardButton(text="📦 Buyurtmalarim")
        ],
        [
            KeyboardButton(text="🛒 Buyurtma berish"),
            KeyboardButton(text="📖 Qo‘llanma")
        ],
        [
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
                KeyboardButton(text="📣 Kanalga reklama")
            ],
            [
                KeyboardButton(text="➕ Kanal qo‘shish"),
                KeyboardButton(text="➖ Kanal o‘chirish")
            ],
            [
                KeyboardButton(text="🚫 Bloklash"),
                KeyboardButton(text="📦 Buyurtmalar")
            ],
            [
                KeyboardButton(text="💳 Pul yechish so‘rovlari"),
                KeyboardButton(text="🎁 Referal bonusini sozlash")
            ],
            [
                KeyboardButton(text="🔙 Foydalanuvchi menyusi")
            ]
        ],
        resize_keyboard=True
    )


def is_admin(user_id):
    return user_id == ADMIN_ID


# =====================================================
# 5. OBUNANI TEKSHIRISH
# =====================================================

async def subscription_ok(user_id):
    channels = db.execute(
        "SELECT channel FROM channels"
    ).fetchall()

    for item in channels:
        try:
            member = await bot.get_chat_member(
                item["channel"], user_id
            )

            if member.status in ("left", "kicked"):
                return False

        except Exception:
            return False

    return True


async def show_subscription(message):
    channels = db.execute(
        "SELECT channel FROM channels"
    ).fetchall()

    buttons = []

    for item in channels:
        channel = item["channel"]
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
            callback_data="check_subscription"
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
        await message.answer("🚫 Siz botdan foydalanish huquqiga ega emassiz.")
        return

    if not await subscription_ok(message.from_user.id):
        await show_subscription(message)
        return

    if is_admin(message.from_user.id):
        await message.answer(
            "👑 Xush kelibsiz, admin!",
            reply_markup=admin_keyboard()
        )
    else:
        await message.answer(
            "👋 Botimizga xush kelibsiz!",
            reply_markup=user_keyboard(message.from_user.id)
        )


@dp.callback_query(F.data == "check_subscription")
async def check_subscription_callback(call: CallbackQuery):
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
# 7. FOYDALANUVCHI HISOBI
# =====================================================

@dp.message(F.text == "👤 Mening hisobim")
async def my_account(message: Message):
    user = user_get(message.from_user.id)

    if not user:
        return

    referrals = db.execute(
        "SELECT COUNT(*) AS total FROM users WHERE referrer_id=?",
        (message.from_user.id,)
    ).fetchone()["total"]

    await message.answer(
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Username: @{html.escape(user['username'] or 'yo‘q')}\n"
        f"💰 Balans: <b>{user['balance']} Stars</b>\n"
        f"👥 Referallar: {referrals}\n"
        f"📅 Ro‘yxatdan o‘tgan: {user['joined']}"
    )


# =====================================================
# 8. REFERAL TIZIMI
# =====================================================

@dp.message(F.text == "👥 Referal")
async def referral_menu(message: Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"

    count = db.execute(
        "SELECT COUNT(*) AS total FROM users WHERE referrer_id=?",
        (message.from_user.id,)
    ).fetchone()["total"]

    bonus = int(setting_get("referral_bonus", REFERRAL_BONUS))

    await message.answer(
        "👥 <b>REFERAL TIZIMI</b>\n\n"
        f"🔗 Havolangiz:\n<code>{link}</code>\n\n"
        f"👤 Taklif qilganlar: {count}\n"
        f"🎁 Har bir referal uchun: {bonus} Stars"
    )


# =====================================================
# 9. PREMIUM STIKERLAR
# =====================================================

def get_sticker_set_name(link):
    link = link.strip()

    if "addstickers/" in link:
        return link.split("addstickers/", 1)[1].split("?")[0].strip("/")

    return link


@dp.message(F.text == "🎁 Premium stikerlar")
async def sticker_menu(message: Message):
    buttons = []

    for i in range(3):
        buttons.append([
            InlineKeyboardButton(
                text=f"🎁 Stikerlar to‘plami {i + 1}",
                callback_data=f"sticker:{i}"
            )
        ])

    await message.answer(
        "Qaysi stikerlar to‘plamini yuboray?",
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

    name = get_sticker_set_name(STICKER_SETS[index])

    if not name or "TOPLAM_" in name:
        await call.answer(
            "Avval koddagi stiker havolasini almashtiring.",
            show_alert=True
        )
        return

    await call.answer("Stikerlar yuklanmoqda...")

    try:
        sticker_set = await bot.get_sticker_set(name=name)
        stickers = list(sticker_set.stickers)

        if not stickers:
            await call.message.answer("Bu to‘plamda stiker topilmadi.")
            return

        chosen = random.sample(stickers, min(5, len(stickers)))

        await call.message.answer(
            f"🎁 <b>{html.escape(sticker_set.title)}</b>\n"
            f"Jami stikerlar: {len(stickers)}\n"
            f"Quyida 5 tagacha stiker yuboriladi."
        )

        for sticker in chosen:
            await bot.send_sticker(
                call.from_user.id,
                sticker.file_id
            )
            await asyncio.sleep(0.3)

    except TelegramBadRequest as error:
        logging.warning("Sticker set error: %s", error)
        await call.message.answer(
            "❌ To‘plamni olish imkoni bo‘lmadi. "
            "Havolani tekshiring yoki to‘plam bot API uchun ochiq emas."
        )
    except Exception:
        logging.exception("Sticker yuborish xatosi")
        await call.message.answer("Stiker yuborishda xatolik yuz berdi.")


# =====================================================
# 10. TELEGRAM STARS TO‘LOVI
# =====================================================

@dp.message(F.text == "⭐ Stars sotib olish")
async def buy_stars(message: Message):
    await bot.send_invoice(
        chat_id=message.chat.id,
        title=f"{STARS_PACKAGE} Stars",
        description="Bot hisobingizni to‘ldirish",
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
async def checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def payment_success(message: Message):
    payment = message.successful_payment

    if payment.currency != "XTR":
        return

    try:
        prefix, user_id, amount = payment.invoice_payload.split(":")
        user_id = int(user_id)
        amount = int(amount)
    except (ValueError, AttributeError):
        return

    if prefix != "account" or user_id != message.from_user.id:
        return

    try:
        db.execute("""
            INSERT INTO payments(user_id,charge_id,amount,created)
            VALUES(?,?,?,?)
        """, (
            user_id,
            payment.telegram_payment_charge_id,
            amount,
            now()
        ))
        db.commit()
    except sqlite3.IntegrityError:
        await message.answer("Bu to‘lov avval hisobga qo‘shilgan.")
        return

    balance_change(user_id, amount)

    await message.answer(
        f"✅ To‘lov muvaffaqiyatli!\n"
        f"💰 Hisobingizga {amount} Stars qo‘shildi.\n"
        f"Yangi balans: {balance_get(user_id)} Stars"
    )

    await bot.send_message(
        ADMIN_ID,
        f"💳 Yangi to‘lov!\n"
        f"Foydalanuvchi: {user_id}\n"
        f"Miqdor: {amount} Stars"
    )


# =====================================================
# 11. PUL YECHISH
# =====================================================

@dp.message(F.text == "💳 Pul yechish")
async def withdraw_start(message: Message, state: FSMContext):
    await state.set_state(UserState.withdraw)
    await message.answer(
        f"Yechmoqchi bo‘lgan miqdorni Stars hisobida yuboring.\n"
        f"Minimal miqdor: {MIN_WITHDRAW} Stars"
    )


@dp.message(UserState.withdraw)
async def withdraw_submit(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Faqat raqam yuboring.")
        return

    amount = int(message.text)

    if amount < MIN_WITHDRAW:
        await message.answer(
            f"Minimal yechish miqdori {MIN_WITHDRAW} Stars."
        )
        return

    if balance_get(message.from_user.id) < amount:
        await message.answer("❌ Balansingiz yetarli emas.")
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

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"withdraw_yes:{request_id}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"withdraw_no:{request_id}"
            )
        ]
    ])

    await bot.send_message(
        ADMIN_ID,
        f"💳 <b>PUL YECHISH SO‘ROVI</b>\n\n"
        f"🆔 So‘rov: {request_id}\n"
        f"👤 Foydalanuvchi: {message.from_user.id}\n"
        f"💰 Miqdor: {amount} Stars",
        reply_markup=keyboard
    )

    await message.answer("✅ So‘rovingiz adminga yuborildi.")
    await state.clear()


@dp.callback_query(F.data.startswith("withdraw_yes:"))
async def withdraw_yes(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    request_id = int(call.data.split(":")[1])

    row = db.execute(
        "SELECT * FROM withdrawals WHERE id=?",
        (request_id,)
    ).fetchone()

    if not row or row["status"] != "pending":
        await call.answer("So‘rov oldin ko‘rib chiqilgan.")
        return

    db.execute(
        "UPDATE withdrawals SET status='approved' WHERE id=?",
        (request_id,)
    )
    db.commit()

    await bot.send_message(
        row["user_id"],
        f"✅ {row['amount']} Stars miqdoridagi so‘rovingiz tasdiqlandi."
    )

    await call.message.edit_text("✅ So‘rov tasdiqlandi.")
    await call.answer()


@dp.callback_query(F.data.startswith("withdraw_no:"))
async def withdraw_no(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return

    request_id = int(call.data.split(":")[1])

    row = db.execute(
        "SELECT * FROM withdrawals WHERE id=?",
        (request_id,)
    ).fetchone()

    if not row or row["status"] != "pending":
        await call.answer("So‘rov oldin ko‘rib chiqilgan.")
        return

    db.execute(
        "UPDATE withdrawals SET status='rejected' WHERE id=?",
        (request_id,)
    )
    db.commit()

    balance_change(row["user_id"], row["amount"])

    await bot.send_message(
        row["user_id"],
        f"❌ So‘rovingiz rad etildi.\n"
        f"{row['amount']} Stars balansingizga qaytarildi."
    )

    await call.message.edit_text("❌ So‘rov rad etildi.")
    await call.answer()


# =====================================================
# 12. BUYURTMALAR
# =====================================================

@dp.message(F.text == "🛒 Buyurtma berish")
async def order_start(message: Message, state: FSMContext):
    await state.set_state(UserState.order)
    await message.answer(
        "🛒 Qanday xizmat yoki mahsulotga buyurtma bermoqchisiz?\n"
        "Buyurtma tavsifini yozing."
    )


@dp.message(UserState.order)
async def order_submit(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Buyurtma tavsifini matn ko‘rinishida yuboring.")
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

    await message.answer(
        f"✅ Buyurtmangiz qabul qilindi!\n"
        f"🆔 Buyurtma raqami: {order_id}"
    )

    await bot.send_message(
        ADMIN_ID,
        f"🛒 <b>YANGI BUYURTMA</b>\n"
        f"ID: {order_id}\n"
        f"Foydalanuvchi: {message.from_user.id}\n"
        f"Tavsif: {html.escape(description)}"
    )

    await state.clear()


@dp.message(F.text == "📦 Buyurtmalarim")
async def orders_user(message: Message):
    rows = db.execute("""
        SELECT * FROM orders
        WHERE user_id=?
        ORDER BY id DESC LIMIT 20
    """, (message.from_user.id,)).fetchall()

    if not rows:
        await message.answer("Sizda hozircha buyurtmalar yo‘q.")
        return

    text = "📦 <b>BUYURTMALARIM</b>\n\n"

    for row in rows:
        text += (
            f"🆔 #{row['id']}\n"
            f"📝 {html.escape(row['description'])}\n"
            f"📌 Holat: {row['status']}\n"
            f"📅 {row['created']}\n\n"
        )

    await message.answer(text)


# =====================================================
# 13. QO‘LLANMA
# =====================================================

@dp.message(F.text == "📖 Qo‘llanma")
async def guide(message: Message):
    await message.answer(
        "📖 <b>BOT QO‘LLANMASI</b>\n\n"
        "👤 Mening hisobim — balans va profilingiz.\n"
        "👥 Referal — do‘stlaringizni taklif qilish.\n"
        "⭐ Stars sotib olish — hisobni to‘ldirish.\n"
        "🎁 Premium stikerlar — stikerlar to‘plami.\n"
        "💳 Pul yechish — admin ko‘rib chiqadigan so‘rov.\n"
        "🛒 Buyurtma berish — yangi buyurtma yuborish.\n"
        "📦 Buyurtmalarim — buyurtmalar tarixi.\n"
        "✉️ Adminga murojaat — yordam olish."
    )


# =====================================================
# 14. ADMIN BILAN ALOQA
# =====================================================

@dp.message(F.text == "✉️ Adminga murojaat")
async def support_start(message: Message, state: FSMContext):
    await state.set_state(UserState.support)
    await message.answer("Xabaringizni yuboring. Admin ko‘rib chiqadi.")


@dp.message(UserState.support)
async def support_send(message: Message, state: FSMContext):
    await bot.send_message(
        ADMIN_ID,
        f"✉️ <b>YANGI MUROJAAT</b>\n"
        f"Foydalanuvchi: {message.from_user.id}\n"
        f"Username: @{html.escape(message.from_user.username or 'yo‘q')}\n\n"
        f"Javob berish: <code>/reply {message.from_user.id}</code>"
    )

    await bot.copy_message(
        ADMIN_ID,
        message.chat.id,
        message.message_id
    )

    await message.answer("✅ Xabaringiz adminga yuborildi.")
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
    await message.answer("Foydalanuvchiga yuboriladigan javobni yozing.")


@dp.message(AdminState.reply)
async def reply_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    user_id = data.get("reply_user")

    try:
        await bot.copy_message(
            user_id,
            message.chat.id,
            message.message_id
        )
        await message.answer("✅ Javob foydalanuvchiga yuborildi.")
    except Exception:
        await message.answer("❌ Xabar yuborilmadi.")

    await state.clear()


# =====================================================
# 15. ADMIN PANEL
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
# 16. STATISTIKA
# =====================================================

@dp.message(F.text == "📊 Statistika")
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    users = db.execute(
        "SELECT COUNT(*) AS n FROM users"
    ).fetchone()["n"]

    banned = db.execute(
        "SELECT COUNT(*) AS n FROM users WHERE banned=1"
    ).fetchone()["n"]

    balance = db.execute(
        "SELECT COALESCE(SUM(balance),0) AS n FROM users"
    ).fetchone()["n"]

    orders = db.execute(
        "SELECT COUNT(*) AS n FROM orders"
    ).fetchone()["n"]

    payments = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS n FROM payments"
    ).fetchone()["n"]

    pending = db.execute(
        "SELECT COUNT(*) AS n FROM withdrawals WHERE status='pending'"
    ).fetchone()["n"]

    await message.answer(
        "📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Jami foydalanuvchilar: {users}\n"
        f"🚫 Bloklanganlar: {banned}\n"
        f"💰 Umumiy balans: {balance} Stars\n"
        f"💳 To‘lovlar: {payments} Stars\n"
        f"📦 Buyurtmalar: {orders}\n"
        f"⏳ Kutilayotgan pul yechish: {pending}"
    )


# =====================================================
# 17. FOYDALANUVCHILAR RO‘YXATI
# =====================================================

@dp.message(F.text == "👥 Foydalanuvchilar")
async def admin_users(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute(
        "SELECT * FROM users ORDER BY joined DESC LIMIT 30"
    ).fetchall()

    if not rows:
        await message.answer("Foydalanuvchilar yo‘q.")
        return

    text = "👥 <b>OXIRGI FOYDALANUVCHILAR</b>\n\n"

    for user in rows:
        text += (
            f"🆔 <code>{user['user_id']}</code>\n"
            f"👤 @{html.escape(user['username'] or 'yo‘q')}\n"
            f"💰 {user['balance']} Stars\n"
            f"🚫 Blok: {'Ha' if user['banned'] else 'Yo‘q'}\n\n"
        )

    await message.answer(text)


# =====================================================
# 18. FOYDALANUVCHINI QIDIRISH
# =====================================================

@dp.message(F.text == "🔎 Foydalanuvchini qidirish")
async def search_user_start(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "Foydalanuvchi ID sini yuboring.\n"
        "Yoki /user ID buyrug‘idan foydalaning."
    )


@dp.message(Command("user"))
async def user_info_command(message: Message):
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
        "👤 <b>FOYDALANUVCHI MA’LUMOTI</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"Username: @{html.escape(user['username'] or 'yo‘q')}\n"
        f"💰 Balans: {user['balance']} Stars\n"
        f"📅 Ro‘yxatdan o‘tgan: {user['joined']}\n"
        f"🚫 Bloklangan: {'Ha' if user['banned'] else 'Yo‘q'}\n"
        f"👥 Referallar: {len(referrals)}\n\n"
        "<b>Taklif qilgan foydalanuvchilari:</b>\n"
    )

    for item in referrals[:30]:
        text += (
            f"• <code>{item['user_id']}</code> "
            f"@{html.escape(item['username'] or 'yo‘q')}\n"
        )

    await message.answer(text)


# =====================================================
# 19. REKLAMA TARQATISH
# =====================================================

@dp.message(F.text == "📢 Reklama tarqatish")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.broadcast)
    await message.answer(
        "Barcha foydalanuvchilarga yuboriladigan xabarni yuboring.\n"
        "Matn, rasm, video yoki boshqa Telegram xabari bo‘lishi mumkin.\n"
        "Bekor qilish: /cancel"
    )


@dp.message(AdminState.broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    users = db.execute(
        "SELECT user_id FROM users WHERE banned=0"
    ).fetchall()

    sent = 0
    failed = 0

    status = await message.answer("📢 Reklama tarqatilmoqda...")

    for user in users:
        try:
            await bot.copy_message(
                chat_id=user["user_id"],
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.04)

    await status.edit_text(
        f"✅ <b>Reklama yakunlandi</b>\n\n"
        f"Yuborildi: {sent}\n"
        f"Yuborilmadi: {failed}"
    )

    await state.clear()


# =====================================================
# 20. KANALGA REKLAMA
# =====================================================

@dp.message(F.text == "📣 Kanalga reklama")
async def channel_ad_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.channel_target)
    await message.answer(
        "Reklama yuboriladigan kanal username yoki ID sini yuboring.\n"
        "Masalan: @kanal_nomi"
    )


@dp.message(AdminState.channel_target)
async def channel_ad_target(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    target = (message.text or "").strip()

    if not target:
        await message.answer("Kanal username yoki ID yuboring.")
        return

    await state.update_data(target=target)
    await state.set_state(AdminState.channel_content)

    await message.answer(
        "Endi kanalga yuboriladigan reklama matni yoki rasmini yuboring."
    )


@dp.message(AdminState.channel_content)
async def channel_ad_content(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    target = data.get("target")

    try:
        await bot.copy_message(
            chat_id=target,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        await message.answer("✅ Reklama kanalga yuborildi.")
    except Exception as error:
        logging.warning("Channel advertisement failed: %s", error)
        await message.answer(
            "❌ Reklama yuborilmadi. Bot kanal administratori ekanini tekshiring."
        )

    await state.clear()


# =====================================================
# 21. MAJBURIY KANAL QO‘SHISH
# =====================================================

@dp.message(F.text == "➕ Kanal qo‘shish")
async def add_channel_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.add_channel)
    await message.answer(
        "Kanal username yuboring.\n"
        "Masalan: @kanal_nomi"
    )


@dp.message(AdminState.add_channel)
async def add_channel_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channel = (message.text or "").strip()

    try:
        chat = await bot.get_chat(channel)
        member = await bot.get_chat_member(chat.id, (await bot.get_me()).id)

        if member.status not in ("administrator", "creator"):
            await message.answer(
                "Botni avval kanalga administrator qilib qo‘shing."
            )
            await state.clear()
            return

        db.execute(
            "INSERT OR IGNORE INTO channels(channel) VALUES(?)",
            (channel,)
        )
        db.commit()

        await message.answer(f"✅ {channel} majburiy kanalga qo‘shildi.")

    except Exception:
        await message.answer(
            "❌ Kanal topilmadi yoki bot administrator emas."
        )

    await state.clear()


# =====================================================
# 22. MAJBURIY KANAL O‘CHIRISH
# =====================================================

@dp.message(F.text == "➖ Kanal o‘chirish")
async def remove_channel_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute(
        "SELECT channel FROM channels"
    ).fetchall()

    if not rows:
        await message.answer("Majburiy kanallar ro‘yxati bo‘sh.")
        return

    text = "📢 <b>Majburiy kanallar:</b>\n\n"

    for row in rows:
        text += f"• {html.escape(row['channel'])}\n"

    await state.set_state(AdminState.remove_channel)
    await message.answer(
        text + "\nO‘chiriladigan kanal username sini yuboring."
    )


@dp.message(AdminState.remove_channel)
async def remove_channel_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channel = (message.text or "").strip()

    cursor = db.execute(
        "DELETE FROM channels WHERE channel=?",
        (channel,)
    )
    db.commit()

    if cursor.rowcount:
        await message.answer("✅ Kanal o‘chirildi.")
    else:
        await message.answer("Bunday kanal ro‘yxatda topilmadi.")

    await state.clear()


# =====================================================
# 23. BALANS BOSHQARISH
# =====================================================

@dp.message(F.text == "💰 Balans boshqarish")
async def balance_admin_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.balance)
    await message.answer(
        "Quyidagi formatda yuboring:\n\n"
        "<code>USER_ID MIQDOR</code>\n\n"
        "Misol:\n"
        "<code>123456789 50</code> — 50 qo‘shadi\n"
        "<code>123456789 -20</code> — 20 ayiradi"
    )


@dp.message(AdminState.balance)
async def balance_admin_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:
        await message.answer("Format noto‘g‘ri. Masalan: 123456789 50")
        return

    try:
        user_id = int(parts[0])
        amount = int(parts[1])
    except ValueError:
        await message.answer("ID va miqdor son bo‘lishi kerak.")
        return

    user = user_get(user_id)

    if not user:
        await message.answer("Foydalanuvchi topilmadi.")
        return

    if balance_get(user_id) + amount < 0:
        await message.answer("Balans manfiy bo‘lib qolmasligi kerak.")
        return

    balance_change(user_id, amount)

    await message.answer(
        f"✅ Balans yangilandi.\n"
        f"Yangi balans: {balance_get(user_id)} Stars"
    )

    try:
        await bot.send_message(
            user_id,
            f"💰 Balansingiz o‘zgartirildi.\n"
            f"Amal: {amount:+} Stars\n"
            f"Yangi balans: {balance_get(user_id)} Stars"
        )
    except Exception:
        pass

    await state.clear()


# =====================================================
# 24. BLOKLASH / BLOKDAN CHIQARISH
# =====================================================

@dp.message(F.text == "🚫 Bloklash")
async def ban_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.ban)
    await message.answer(
        "Format:\n"
        "<code>USER_ID ban</code> — bloklash\n"
        "<code>USER_ID unban</code> — blokdan chiqarish"
    )


@dp.message(AdminState.ban)
async def ban_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:
        await message.answer("Format: USER_ID ban yoki USER_ID unban")
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

    if action == "ban":
        value = 1
    elif action == "unban":
        value = 0
    else:
        await message.answer("ban yoki unban deb yozing.")
        return

    db.execute(
        "UPDATE users SET banned=? WHERE user_id=?",
        (value, user_id)
    )
    db.commit()

    await message.answer("✅ Amal bajarildi.")
    await state.clear()


# =====================================================
# 25. BUYURTMALARNI ADMIN KO‘RISHI
# =====================================================

@dp.message(F.text == "📦 Buyurtmalar")
async def admin_orders(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute(
        "SELECT * FROM orders ORDER BY id DESC LIMIT 20"
    ).fetchall()

    if not rows:
        await message.answer("Buyurtmalar mavjud emas.")
        return

    text = "📦 <b>OXIRGI BUYURTMALAR</b>\n\n"

    for row in rows:
        text += (
            f"🆔 #{row['id']}\n"
            f"👤 User: {row['user_id']}\n"
            f"📝 {html.escape(row['description'])}\n"
            f"📌 Holat: {row['status']}\n\n"
        )

    await message.answer(text)


# =====================================================
# 26. PUL YECHISH SO‘ROVLARI
# =====================================================

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
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash",
                    callback_data=f"withdraw_yes:{row['id']}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=f"withdraw_no:{row['id']}"
                )
            ]
        ])

        await message.answer(
            f"💳 So‘rov #{row['id']}\n"
            f"User: {row['user_id']}\n"
            f"Miqdor: {row['amount']} Stars\n"
            f"Sana: {row['created']}",
            reply_markup=keyboard
        )


# =====================================================
# 27. REFERAL BONUSINI SOZLASH
# =====================================================

@dp.message(F.text == "🎁 Referal bonusini sozlash")
async def bonus_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.referral_bonus)
    current = setting_get("referral_bonus", REFERRAL_BONUS)

    await message.answer(
        f"Hozirgi referal bonusi: {current} Stars.\n"
        "Yangi bonus miqdorini yuboring."
    )


@dp.message(AdminState.referral_bonus)
async def bonus_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.isdigit():
        await message.answer("Faqat musbat son yuboring.")
        return

    amount = int(message.text)

    if amount > 100000:
        await message.answer("Juda katta miqdor. Boshqa son kiriting.")
        return

    setting_set("referral_bonus", amount)

    await message.answer(
        f"✅ Referal bonusi {amount} Stars qilib belgilandi."
    )
    await state.clear()


# =====================================================
# 28. BEKOR QILISH
# =====================================================

@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()

    if is_admin(message.from_user.id):
        keyboard = admin_keyboard()
    else:
        keyboard = user_keyboard(message.from_user.id)

    await message.answer(
        "❌ Amal bekor qilindi.",
        reply_markup=keyboard
    )


# =====================================================
# 29. UMUMIY XABARLAR
# =====================================================

@dp.message()
async def other_messages(message: Message):
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
# 30. RENDER HEALTH SERVER
# =====================================================

async def health(request):
    return web.Response(text="Bot is running!")


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
# 31. BOTNI ISHGA TUSHIRISH
# =====================================================

async def main():
    if BOT_TOKEN == "TOKENINGIZNI_BU_YERGA":
        raise RuntimeError("BOT_TOKEN ni kiriting!")

    if ADMIN_ID == 123456789:
        logging.warning("ADMIN_ID ni o‘zingiznikiga almashtiring!")

    await run_web()

    logging.info("Bot ishga tushdi!")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
