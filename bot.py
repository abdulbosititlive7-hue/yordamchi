
import asyncio
import logging
import os
import sqlite3
from datetime import datetime, date

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup,
    KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


# ==================================================
# SOZLAMALAR
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5200398952"))

DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")
PORT = int(os.getenv("PORT", "10000"))

DAILY_BONUS = 1
DEFAULT_REFERRAL_BONUS = 2

logging.basicConfig(level=logging.INFO)


# ==================================================
# DATABASE
# ==================================================

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        username TEXT,
        balance INTEGER DEFAULT 0,
        earned INTEGER DEFAULT 0,
        referrer INTEGER,
        ref_paid INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0,
        joined TEXT,
        last_bonus TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        channel_id TEXT PRIMARY KEY,
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
        created TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY,
        amount INTEGER,
        created TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS promo_uses (
        code TEXT,
        user_id INTEGER,
        created TEXT,
        PRIMARY KEY(code, user_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cur.execute("""
    INSERT OR IGNORE INTO settings(key,value)
    VALUES('referral_bonus',?)
    """, (str(DEFAULT_REFERRAL_BONUS),))

    # Eski bazalardan yetishmayotgan ustunlarni qo'shish.
    existing = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(users)").fetchall()
    }

    migrations = {
        "ref_paid": "INTEGER DEFAULT 0",
        "last_bonus": "TEXT"
    }

    for column, definition in migrations.items():
        if column not in existing:
            cur.execute(
                f"ALTER TABLE users ADD COLUMN {column} {definition}"
            )

    con.commit()
    con.close()


def setting(key, default="0"):
    con = db()
    row = con.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    con.close()
    return row["value"] if row else default


def set_setting(key, value):
    con = db()
    con.execute("""
        INSERT OR REPLACE INTO settings(key,value)
        VALUES(?,?)
    """, (key, str(value)))
    con.commit()
    con.close()


def get_user(user_id):
    con = db()
    row = con.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    con.close()
    return row


def register_user(user, referrer=None):
    con = db()
    old = con.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    ).fetchone()

    if not old:
        if referrer == user.id:
            referrer = None

        con.execute("""
            INSERT INTO users(
                user_id,full_name,username,balance,earned,
                referrer,ref_paid,banned,joined
            )
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            user.id,
            user.full_name,
            user.username or "",
            0, 0,
            referrer,
            0, 0,
            datetime.now().isoformat()
        ))
    else:
        con.execute("""
            UPDATE users
            SET full_name=?,username=?
            WHERE user_id=?
        """, (user.full_name, user.username or "", user.id))

    con.commit()
    con.close()


def add_balance(user_id, amount, earned=True):
    con = db()

    if earned and amount > 0:
        con.execute("""
            UPDATE users
            SET balance=balance+?, earned=earned+?
            WHERE user_id=?
        """, (amount, amount, user_id))
    else:
        con.execute("""
            UPDATE users
            SET balance=balance+?
            WHERE user_id=?
        """, (amount, user_id))

    con.commit()
    con.close()


def is_admin(user_id):
    return user_id == ADMIN_ID


def is_banned(user_id):
    user = get_user(user_id)
    return bool(user and user["banned"])


# ==================================================
# FSM
# ==================================================

class PromoCreate(StatesGroup):
    name = State()
    amount = State()


class ChannelAdd(StatesGroup):
    waiting = State()


class Broadcast(StatesGroup):
    waiting = State()


class ChannelBroadcast(StatesGroup):
    waiting = State()


class BalanceEdit(StatesGroup):
    user_id = State()
    amount = State()


class UserSearch(StatesGroup):
    waiting = State()


class BanUser(StatesGroup):
    waiting = State()


class ReferralEdit(StatesGroup):
    waiting = State()


class Support(StatesGroup):
    waiting = State()


# ==================================================
# BOT
# ==================================================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


# ==================================================
# KEYBOARDS
# ==================================================

def user_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="💰 Mening hisobim"),
                KeyboardButton(text="👥 Referal")
            ],
            [
                KeyboardButton(text="🎁 Gift yechish"),
                KeyboardButton(text="📦 Buyurtmalarim")
            ],
            [
                KeyboardButton(text="🎟 Promokod"),
                KeyboardButton(text="🎁 Kunlik bonus")
            ],
            [
                KeyboardButton(text="📖 Qo‘llanma"),
                KeyboardButton(text="📩 Adminga murojaat")
            ]
        ],
        resize_keyboard=True
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Statistika"),
                KeyboardButton(text="👥 Foydalanuvchilar")
            ],
            [
                KeyboardButton(text="🔎 Foydalanuvchi qidirish"),
                KeyboardButton(text="💰 Balans boshqarish")
            ],
            [
                KeyboardButton(text="🎟 Promokod yaratish"),
                KeyboardButton(text="🗑 Promokodlar")
            ],
            [
                KeyboardButton(text="📢 Reklama tarqatish"),
                KeyboardButton(text="📣 Kanallarga reklama")
            ],
            [
                KeyboardButton(text="📡 Kanallar"),
                KeyboardButton(text="📦 Buyurtmalar")
            ],
            [
                KeyboardButton(text="🚫 Ban qilish"),
                KeyboardButton(text="✅ Bandan chiqarish")
            ],
            [
                KeyboardButton(text="⚙️ Referal bonus")
            ]
        ],
        resize_keyboard=True
    )


def gift_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="15 ⭐", callback_data="gift_15"),
            InlineKeyboardButton(text="25 ⭐", callback_data="gift_25")
        ]
    ])


def order_buttons(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
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


# ==================================================
# CHANNELS
# ==================================================

def get_channels():
    con = db()
    rows = con.execute(
        "SELECT * FROM channels"
    ).fetchall()
    con.close()
    return rows


def subscription_buttons(channels):
    rows = []

    for channel in channels:
        link = channel["invite_link"]

        if not link:
            channel_id = channel["channel_id"]
            link = (
                "https://t.me/" + channel_id[1:]
                if channel_id.startswith("@")
                else None
            )

        if link:
            rows.append([
                InlineKeyboardButton(
                    text="📢 " + channel["title"],
                    url=link
                )
            ])

    rows.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_subscription"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def check_subscription(user_id):
    for channel in get_channels():
        try:
            member = await bot.get_chat_member(
                channel["channel_id"],
                user_id
            )

            if member.status in ("left", "kicked"):
                return False

        except Exception:
            logging.exception("Obunani tekshirishda xato")
            return False

    return True


async def show_menu(message):
    if is_admin(message.from_user.id):
        await message.answer(
            "🛠 <b>ADMIN PANEL</b>",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "🏠 <b>Asosiy menyu</b>",
            reply_markup=user_menu()
        )


# ==================================================
# START / REFERRAL
# ==================================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    referrer = None
    parts = message.text.split()

    if len(parts) > 1 and parts[1].isdigit():
        referrer = int(parts[1])

    register_user(message.from_user, referrer)

    if is_banned(message.from_user.id):
        await message.answer("🚫 Siz botdan foydalanish huquqidan mahrum qilingansiz.")
        return

    if not is_admin(message.from_user.id):
        channels = get_channels()

        if channels and not await check_subscription(message.from_user.id):
            await message.answer(
                "❗ Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
                reply_markup=subscription_buttons(channels)
            )
            return

        # Referal bonusi faqat obuna tekshiruvidan keyin,
        # faqat bir marta beriladi.
        user = get_user(message.from_user.id)

        if user and user["referrer"] and not user["ref_paid"]:
            bonus = int(setting("referral_bonus", DEFAULT_REFERRAL_BONUS))
            ref_user = get_user(user["referrer"])

            if ref_user:
                add_balance(user["referrer"], bonus)
                con = db()
                con.execute(
                    "UPDATE users SET ref_paid=1 WHERE user_id=?",
                    (message.from_user.id,)
                )
                con.commit()
                con.close()

                try:
                    await bot.send_message(
                        user["referrer"],
                        f"🎉 Yangi referalingiz uchun {bonus} ⭐ berildi!"
                    )
                except Exception:
                    pass

    await show_menu(message)


@dp.callback_query(F.data == "check_subscription")
async def check_subscription_callback(call: CallbackQuery):
    if is_banned(call.from_user.id):
        await call.answer("Siz bloklangansiz.", show_alert=True)
        return

    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await show_menu(call.message)
        await call.answer("Obuna tasdiqlandi!")
    else:
        await call.answer(
            "Hali barcha kanallarga obuna bo‘lmagansiz!",
            show_alert=True
        )


# ==================================================
# USER ACCOUNT
# ==================================================

@dp.message(F.text == "💰 Mening hisobim")
async def account(message: Message):
    user = get_user(message.from_user.id)

    con = db()
    refs = con.execute(
        "SELECT COUNT(*) AS n FROM users WHERE referrer=?",
        (message.from_user.id,)
    ).fetchone()["n"]
    con.close()

    await message.answer(
        f"👤 <b>Hisobingiz</b>\n\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"💰 Balans: <b>{user['balance']} ⭐</b>\n"
        f"📈 Jami ishlab topgan: {user['earned']} ⭐\n"
        f"👥 Referallar: {refs} ta"
    )


@dp.message(F.text == "👥 Referal")
async def referral(message: Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"
    bonus = setting("referral_bonus", DEFAULT_REFERRAL_BONUS)

    await message.answer(
        f"👥 <b>Referal tizimi</b>\n\n"
        f"Har bir yangi foydalanuvchi uchun: {bonus} ⭐\n\n"
        f"🔗 Havolangiz:\n<code>{link}</code>"
    )


# ==================================================
# DAILY BONUS
# ==================================================

@dp.message(F.text == "🎁 Kunlik bonus")
async def daily_bonus(message: Message):
    today = date.today().isoformat()

    con = db()
    user = con.execute(
        "SELECT last_bonus FROM users WHERE user_id=?",
        (message.from_user.id,)
    ).fetchone()

    if user["last_bonus"] == today:
        con.close()
        await message.answer("⏳ Bugungi bonusni olib bo‘lgansiz.")
        return

    con.execute("""
        UPDATE users
        SET balance=balance+?, earned=earned+?, last_bonus=?
        WHERE user_id=?
    """, (
        DAILY_BONUS,
        DAILY_BONUS,
        today,
        message.from_user.id
    ))

    con.commit()
    con.close()

    await message.answer(f"🎉 Sizga {DAILY_BONUS} ⭐ bonus berildi!")


# ==================================================
# GIFT WITHDRAWAL
# ==================================================

@dp.message(F.text == "🎁 Gift yechish")
async def gift_start(message: Message):
    user = get_user(message.from_user.id)

    await message.answer(
        f"🎁 <b>Gift yechish</b>\n\n"
        f"Hisobingiz: {user['balance']} ⭐\n\n"
        "Yechish uchun miqdorni tanlang:",
        reply_markup=gift_buttons()
    )


@dp.callback_query(F.data.in_(["gift_15", "gift_25"]))
async def gift_create(call: CallbackQuery):
    user_id = call.from_user.id
    amount = 15 if call.data == "gift_15" else 25

    if is_banned(user_id):
        await call.answer("Siz bloklangansiz.", show_alert=True)
        return

    con = db()
    user = con.execute(
        "SELECT balance FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not user or user["balance"] < amount:
        con.close()
        await call.answer(
            "❌ Mablag‘ yetarli emas!",
            show_alert=True
        )
        return

    # Balansdan pul yechish va buyurtma yaratish
    # bitta tranzaksiyada amalga oshadi.
    con.execute(
        "UPDATE users SET balance=balance-? WHERE user_id=?",
        (amount, user_id)
    )

    cursor = con.execute("""
        INSERT INTO orders(user_id,amount,status,created)
        VALUES(?,?,?,?)
    """, (
        user_id,
        amount,
        "pending",
        datetime.now().isoformat()
    ))

    order_id = cursor.lastrowid
    con.commit()
    con.close()

    await call.message.edit_text(
        f"✅ <b>Buyurtmangiz yuborildi!</b>\n\n"
        f"📦 Buyurtma: #{order_id}\n"
        f"⭐ Miqdor: {amount} Stars\n"
        f"📌 Holat: Kutilmoqda"
    )

    admin_text = (
        f"📥 <b>YANGI GIFT BUYURTMASI</b>\n\n"
        f"📦 Buyurtma: #{order_id}\n"
        f"👤 Ism: {call.from_user.full_name}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"Username: @{call.from_user.username or 'yo‘q'}\n"
        f"⭐ Miqdor: {amount} Stars\n"
        f"📌 Holat: Kutilmoqda"
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            admin_text,
            reply_markup=order_buttons(order_id)
        )
    except Exception:
        # Admin xabarini yuborib bo'lmasa, balans qaytariladi
        con = db()
        con.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (amount, user_id)
        )
        con.execute(
            "UPDATE orders SET status='rejected' WHERE id=?",
            (order_id,)
        )
        con.commit()
        con.close()

        await bot.send_message(
            user_id,
            "❌ Buyurtmani adminga yuborib bo‘lmadi. Mablag‘ingiz qaytarildi."
        )

    await call.answer()


@dp.callback_query(F.data.startswith("approve_"))
async def approve_order(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    order_id = int(call.data.split("_")[1])

    con = db()
    order = con.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

    if not order or order["status"] != "pending":
        con.close()
        await call.answer("Buyurtma oldin ko‘rib chiqilgan.")
        return

    con.execute(
        "UPDATE orders SET status='approved' WHERE id=?",
        (order_id,)
    )
    con.commit()
    con.close()

    await bot.send_message(
        order["user_id"],
        f"✅ #{order_id} buyurtmangiz tasdiqlandi."
    )

    await call.message.edit_text(
        call.message.text + "\n\n✅ <b>TASDIQLANDI</b>"
    )
    await call.answer("Tasdiqlandi!")


@dp.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    order_id = int(call.data.split("_")[1])

    con = db()
    order = con.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

    if not order or order["status"] != "pending":
        con.close()
        await call.answer("Buyurtma oldin ko‘rib chiqilgan.")
        return

    con.execute(
        "UPDATE orders SET status='rejected' WHERE id=?",
        (order_id,)
    )
    con.execute(
        "UPDATE users SET balance=balance+? WHERE user_id=?",
        (order["amount"], order["user_id"])
    )

    con.commit()
    con.close()

    await bot.send_message(
        order["user_id"],
        f"❌ #{order_id} buyurtmangiz rad etildi.\n"
        f"{order['amount']} ⭐ balansingizga qaytarildi."
    )

    await call.message.edit_text(
        call.message.text + "\n\n❌ <b>RAD ETILDI — BALANS QAYTARILDI</b>"
    )
    await call.answer("Mablag‘ qaytarildi!")


# ==================================================
# USER ORDERS
# ==================================================

@dp.message(F.text == "📦 Buyurtmalarim")
async def my_orders(message: Message):
    con = db()
    rows = con.execute("""
        SELECT * FROM orders
        WHERE user_id=?
        ORDER BY id DESC LIMIT 20
    """, (message.from_user.id,)).fetchall()
    con.close()

    if not rows:
        await message.answer("Sizda hali buyurtmalar yo‘q.")
        return

    text = "📦 <b>Buyurtmalaringiz</b>\n\n"

    for order in rows:
        text += (
            f"🆔 #{order['id']}\n"
            f"⭐ {order['amount']} Stars\n"
            f"📌 {order['status']}\n\n"
        )

    await message.answer(text)


# ==================================================
# PROMO CODE - USER
# ==================================================

@dp.message(F.text == "🎟 Promokod")
async def promo_start(message: Message):
    await message.answer("🎟 Promokod nomini yuboring:")


# ==================================================
# PROMO CODE - ADMIN CREATION
# ==================================================

@dp.message(F.text == "🎟 Promokod yaratish")
async def promo_admin_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(PromoCreate.name)
    await message.answer(
        "🎟 <b>Yangi promokod nomini kiriting.</b>\n\n"
        "Masalan: WELCOME"
    )


@dp.message(PromoCreate.name)
async def promo_admin_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text:
        await message.answer("Promokod nomini matn shaklida kiriting.")
        return

    code = message.text.strip().upper()

    if not code.replace("_", "").isalnum() or not 3 <= len(code) <= 30:
        await message.answer("Kod 3–30 belgidan iborat bo‘lsin. Harf, raqam va _ ishlating.")
        return

    con = db()
    exists = con.execute(
        "SELECT code FROM promo_codes WHERE code=?",
        (code,)
    ).fetchone()
    con.close()

    if exists:
        await message.answer("Bu promokod mavjud. Boshqa nom kiriting.")
        return

    await state.update_data(code=code)
    await state.set_state(PromoCreate.amount)

    await message.answer(
        f"✅ Promokod nomi: <code>{code}</code>\n\n"
        "Endi foydalanuvchi hisobiga qo‘shiladigan Stars miqdorini kiriting:"
    )


@dp.message(PromoCreate.amount)
async def promo_admin_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.isdigit():
        await message.answer("Faqat musbat Stars miqdorini kiriting.")
        return

    amount = int(message.text)

    if amount <= 0 or amount > 1000000:
        await message.answer("Stars miqdori 1 dan 1 000 000 gacha bo‘lishi kerak.")
        return

    data = await state.get_data()
    code = data["code"]

    con = db()
    con.execute("""
        INSERT INTO promo_codes(code,amount,created)
        VALUES(?,?,?)
    """, (code, amount, datetime.now().isoformat()))
    con.commit()
    con.close()

    await state.clear()

    await message.answer(
        f"🎉 <b>Promokod yaratildi!</b>\n\n"
        f"🎟 Kod: <code>{code}</code>\n"
        f"⭐ Qiymati: {amount} Stars\n\n"
        "Har bir foydalanuvchi koddan bir marta foydalanadi.",
        reply_markup=admin_menu()
    )


# Promokod matni faqat FSM holatida bo'lmagan oddiy
# foydalanuvchidan qabul qilinadi. Admin xabarlari bu yerga tushmaydi.
@dp.message(StateFilter(None), F.text)
async def promo_redeem(message: Message):
    if is_admin(message.from_user.id):
        return

    if is_banned(message.from_user.id):
        return

    reserved = {
        "💰 Mening hisobim", "👥 Referal",
        "🎁 Gift yechish", "📦 Buyurtmalarim",
        "🎟 Promokod", "🎁 Kunlik bonus",
        "📖 Qo‘llanma", "📩 Adminga murojaat"
    }

    code = message.text.strip().upper()

    if code in reserved or code.startswith("/"):
        return

    con = db()
    promo = con.execute(
        "SELECT * FROM promo_codes WHERE code=?",
        (code,)
    ).fetchone()

    if not promo:
        con.close()
        return

    used = con.execute(
        "SELECT 1 FROM promo_uses WHERE code=? AND user_id=?",
        (code, message.from_user.id)
    ).fetchone()

    if used:
        con.close()
        await message.answer("❌ Siz bu promokoddan avval foydalangansiz.")
        return

    amount = promo["amount"]

    con.execute("""
        INSERT INTO promo_uses(code,user_id,created)
        VALUES(?,?,?)
    """, (code, message.from_user.id, datetime.now().isoformat()))

    con.execute("""
        UPDATE users
        SET balance=balance+?, earned=earned+?
        WHERE user_id=?
    """, (amount, amount, message.from_user.id))

    con.commit()
    con.close()

    await message.answer(
        f"🎉 <b>Promokod qabul qilindi!</b>\n\n"
        f"🎟 Kod: {code}\n"
        f"⭐ Hisobingizga {amount} Stars qo‘shildi."
    )


@dp.message(F.text == "🗑 Promokodlar")
async def promo_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    con = db()
    rows = con.execute(
        "SELECT * FROM promo_codes ORDER BY created DESC"
    ).fetchall()
    con.close()

    if not rows:
        await message.answer("Promokodlar mavjud emas.")
        return

    text = "🎟 <b>Promokodlar</b>\n\n"

    for row in rows:
        text += f"• <code>{row['code']}</code> — {row['amount']} ⭐\n"

    await message.answer(text)


# ==================================================
# ADMIN USERS / SEARCH
# ==================================================

@dp.message(F.text == "👥 Foydalanuvchilar")
async def users_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    con = db()
    rows = con.execute("""
        SELECT user_id,full_name,username,balance
        FROM users ORDER BY joined DESC LIMIT 50
    """).fetchall()

    total = con.execute(
        "SELECT COUNT(*) AS n FROM users"
    ).fetchone()["n"]
    con.close()

    text = f"👥 <b>Jami foydalanuvchilar: {total}</b>\n\n"

    for row in rows:
        text += (
            f"👤 {row['full_name']}\n"
            f"🆔 <code>{row['user_id']}</code>\n"
            f"💰 {row['balance']} ⭐\n"
            f"──────────────\n"
        )

    await message.answer(text)


@dp.message(F.text == "🔎 Foydalanuvchi qidirish")
async def search_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(UserSearch.waiting)
    await message.answer("Foydalanuvchi Telegram ID raqamini yuboring:")


@dp.message(UserSearch.waiting)
async def search_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.isdigit():
        await message.answer("ID raqamini yuboring.")
        return

    user_id = int(message.text)
    user = get_user(user_id)

    await state.clear()

    if not user:
        await message.answer("Foydalanuvchi topilmadi.")
        return

    con = db()
    refs = con.execute(
        "SELECT COUNT(*) AS n FROM users WHERE referrer=?",
        (user_id,)
    ).fetchone()["n"]

    orders = con.execute("""
        SELECT * FROM orders WHERE user_id=?
        ORDER BY id DESC LIMIT 10
    """, (user_id,)).fetchall()
    con.close()

    text = (
        f"👤 <b>FOYDALANUVCHI PROFILI</b>\n\n"
        f"Ism: {user['full_name']}\n"
        f"Username: @{user['username'] or 'yo‘q'}\n"
        f"ID: <code>{user_id}</code>\n"
        f"Balans: {user['balance']} ⭐\n"
        f"Jami topgan: {user['earned']} ⭐\n"
        f"Referallar: {refs}\n"
        f"Ban: {'Ha' if user['banned'] else 'Yo‘q'}\n\n"
        f"📦 <b>Oxirgi buyurtmalar:</b>\n"
    )

    for order in orders:
        text += (
            f"#{order['id']} — {order['amount']} ⭐ — "
            f"{order['status']}\n"
        )

    await message.answer(text)


# ==================================================
# ADMIN BALANCE
# ==================================================

@dp.message(F.text == "💰 Balans boshqarish")
async def balance_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(BalanceEdit.user_id)
    await message.answer("Foydalanuvchi ID raqamini kiriting:")


@dp.message(BalanceEdit.user_id)
async def balance_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.isdigit():
        await message.answer("ID raqamini kiriting.")
        return

    user_id = int(message.text)

    if not get_user(user_id):
        await message.answer("Foydalanuvchi topilmadi.")
        return

    await state.update_data(user_id=user_id)
    await state.set_state(BalanceEdit.amount)

    await message.answer(
        "Stars miqdorini kiriting.\n"
        "Masalan: 50 yoki -20"
    )


@dp.message(BalanceEdit.amount)
async def balance_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        amount = int(message.text)
    except (ValueError, TypeError):
        await message.answer("Raqam yuboring.")
        return

    data = await state.get_data()
    user_id = data["user_id"]
    user = get_user(user_id)

    if user["balance"] + amount < 0:
        await message.answer("Balans manfiy bo‘lishi mumkin emas.")
        return

    add_balance(user_id, amount, earned=amount > 0)
    await state.clear()

    await message.answer(
        "✅ Balans o‘zgartirildi.",
        reply_markup=admin_menu()
    )

    try:
        await bot.send_message(
            user_id,
            f"💰 Admin hisobingizga {amount} ⭐ o‘zgartirish kiritdi."
        )
    except Exception:
        pass


# ==================================================
# BAN / UNBAN
# ==================================================

@dp.message(F.text.in_(["🚫 Ban qilish", "✅ Bandan chiqarish"]))
async def ban_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    action = "ban" if message.text == "🚫 Ban qilish" else "unban"

    await state.set_state(BanUser.waiting)
    await state.update_data(action=action)

    await message.answer("Foydalanuvchi ID raqamini yuboring:")


@dp.message(BanUser.waiting)
async def ban_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.isdigit():
        await message.answer("ID raqamini yuboring.")
        return

    user_id = int(message.text)

    if not get_user(user_id):
        await message.answer("Foydalanuvchi topilmadi.")
        return

    data = await state.get_data()
    banned = 1 if data["action"] == "ban" else 0

    con = db()
    con.execute(
        "UPDATE users SET banned=? WHERE user_id=?",
        (banned, user_id)
    )
    con.commit()
    con.close()

    await state.clear()

    await message.answer(
        "✅ Amal bajarildi.",
        reply_markup=admin_menu()
    )

    try:
        await bot.send_message(
            user_id,
            "🚫 Siz botdan bloklandingiz."
            if banned else
            "✅ Sizning banningiz olib tashlandi."
        )
    except Exception:
        pass


# ==================================================
# STATISTICS
# ==================================================

@dp.message(F.text == "📊 Statistika")
async def statistics(message: Message):
    if not is_admin(message.from_user.id):
        return

    con = db()

    users = con.execute(
        "SELECT COUNT(*) AS n FROM users"
    ).fetchone()["n"]

    banned = con.execute(
        "SELECT COUNT(*) AS n FROM users WHERE banned=1"
    ).fetchone()["n"]

    balance = con.execute(
        "SELECT COALESCE(SUM(balance),0) AS n FROM users"
    ).fetchone()["n"]

    earned = con.execute(
        "SELECT COALESCE(SUM(earned),0) AS n FROM users"
    ).fetchone()["n"]

    orders = con.execute(
        "SELECT COUNT(*) AS n FROM orders"
    ).fetchone()["n"]

    pending = con.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE status='pending'"
    ).fetchone()["n"]

    channels = con.execute(
        "SELECT COUNT(*) AS n FROM channels"
    ).fetchone()["n"]

    con.close()

    await message.answer(
        f"📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"🚫 Ban qilinganlar: {banned}\n"
        f"💰 Jami balans: {balance} ⭐\n"
        f"📈 Jami ishlab topilgan: {earned} ⭐\n"
        f"📦 Buyurtmalar: {orders}\n"
        f"⏳ Kutilayotgan buyurtmalar: {pending}\n"
        f"📡 Kanallar: {channels}"
    )


# ==================================================
# ADMIN ORDERS
# ==================================================

@dp.message(F.text == "📦 Buyurtmalar")
async def admin_orders(message: Message):
    if not is_admin(message.from_user.id):
        return

    con = db()
    rows = con.execute("""
        SELECT * FROM orders ORDER BY id DESC LIMIT 30
    """).fetchall()
    con.close()

    if not rows:
        await message.answer("Buyurtmalar mavjud emas.")
        return

    for order in rows:
        await message.answer(
            f"📦 <b>Buyurtma #{order['id']}</b>\n"
            f"👤 ID: <code>{order['user_id']}</code>\n"
            f"⭐ {order['amount']} Stars\n"
            f"Holat: {order['status']}",
            reply_markup=(
                order_buttons(order["id"])
                if order["status"] == "pending" else None
            )
        )


# ==================================================
# CHANNEL MANAGEMENT
# ==================================================

@dp.message(F.text == "📡 Kanallar")
async def channels_menu(message: Message):
    if not is_admin(message.from_user.id):
        return

    channels = get_channels()

    text = "📡 <b>Kanallar boshqaruvi</b>\n\n"

    for channel in channels:
        text += (
            f"• {channel['title']}\n"
            f"<code>{channel['channel_id']}</code>\n\n"
        )

    if not channels:
        text += "Hozircha kanal qo‘shilmagan."

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="➕ Kanal qo‘shish",
                callback_data="add_channel"
            )
        ],
        [
            InlineKeyboardButton(
                text="➖ Kanal o‘chirish",
                callback_data="remove_channel"
            )
        ]
    ])

    await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data == "add_channel")
async def add_channel_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return

    await state.set_state(ChannelAdd.waiting)
    await call.message.answer(
        "Kanal username yoki ID sini yuboring.\n"
        "Masalan: @kanal_nomi"
    )
    await call.answer()


@dp.message(ChannelAdd.waiting)
async def add_channel_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text:
        await message.answer("Kanal username yoki ID sini yuboring.")
        return

    channel_value = message.text.strip()

    try:
        chat = await bot.get_chat(channel_value)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)

        if member.status not in ("administrator", "creator"):
            await message.answer(
                "❌ Botni avval kanalga administrator qiling."
            )
            return

        if member.status != "creator" and not member.can_post_messages:
            await message.answer(
                "❌ Botga kanalda xabar yuborish huquqini bering."
            )
            return

        invite_link = chat.invite_link

        if not chat.username:
            try:
                invite_link = await bot.export_chat_invite_link(chat.id)
            except Exception:
                invite_link = None

        con = db()
        con.execute("""
            INSERT OR REPLACE INTO channels(
                channel_id,title,invite_link
            )
            VALUES(?,?,?)
        """, (
            str(chat.id),
            chat.title or channel_value,
            invite_link
        ))
        con.commit()
        con.close()

        await state.clear()

        await message.answer(
            "✅ Kanal qo‘shildi!\n"
            "U majburiy obuna va kanal reklamasi uchun ishlatiladi.",
            reply_markup=admin_menu()
        )

    except Exception:
        logging.exception("Kanal qo‘shish xatosi")
        await message.answer(
            "❌ Kanal qo‘shilmadi. Username yoki ID ni tekshiring, "
            "bot admin ekanini tekshiring."
        )


@dp.callback_query(F.data == "remove_channel")
async def remove_channel_menu(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    channels = get_channels()

    if not channels:
        await call.answer("Kanallar yo‘q.", show_alert=True)
        return

    buttons = []

    for channel in channels:
        buttons.append([
            InlineKeyboardButton(
                text="❌ " + channel["title"],
                callback_data="del_channel:" + channel["channel_id"]
            )
        ])

    await call.message.answer(
        "O‘chiriladigan kanalni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()


@dp.callback_query(F.data.startswith("del_channel:"))
async def remove_channel_finish(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    channel_id = call.data.split(":", 1)[1]

    con = db()
    con.execute(
        "DELETE FROM channels WHERE channel_id=?",
        (channel_id,)
    )
    con.commit()
    con.close()

    await call.message.edit_text("✅ Kanal o‘chirildi.")
    await call.answer()


# ==================================================
# BROADCAST TO USERS
# ==================================================

@dp.message(F.text == "📢 Reklama tarqatish")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(Broadcast.waiting)
    await message.answer(
        "📢 Foydalanuvchilarga yuboriladigan xabarni yuboring.\n"
        "Matn, rasm, video yoki boshqa media bo‘lishi mumkin.\n"
        "Bekor qilish: /cancel"
    )


@dp.message(Broadcast.waiting)
async def broadcast_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    con = db()
    users = con.execute(
        "SELECT user_id FROM users WHERE banned=0"
    ).fetchall()
    con.close()

    success = 0
    failed = 0

    await message.answer("⏳ Reklama yuborish boshlandi...")

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

    await state.clear()

    await message.answer(
        f"✅ <b>Tarqatish yakunlandi</b>\n\n"
        f"Yetkazildi: {success}\n"
        f"Yetkazilmadi: {failed}",
        reply_markup=admin_menu()
    )


# ==================================================
# BROADCAST TO CHANNELS
# ==================================================

@dp.message(F.text == "📣 Kanallarga reklama")
async def channel_broadcast_start(
    message: Message,
    state: FSMContext
):
    if not is_admin(message.from_user.id):
        return

    if not get_channels():
        await message.answer("Avval kanal qo‘shing.")
        return

    await state.set_state(ChannelBroadcast.waiting)

    await message.answer(
        "📣 Barcha qo‘shilgan kanallarga yuboriladigan "
        "matn, rasm yoki videoni yuboring.\n"
        "Bekor qilish: /cancel"
    )


@dp.message(ChannelBroadcast.waiting)
async def channel_broadcast_finish(
    message: Message,
    state: FSMContext
):
    if not is_admin(message.from_user.id):
        return

    success = 0
    failed = 0

    await message.answer("⏳ Kanallarga yuborilmoqda...")

    for channel in get_channels():
        try:
            await bot.copy_message(
                chat_id=channel["channel_id"],
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            success += 1
        except Exception:
            failed += 1

    await state.clear()

    await message.answer(
        f"📣 <b>Kanal reklamasi yakunlandi</b>\n\n"
        f"Yuborildi: {success}\n"
        f"Xatolik: {failed}",
        reply_markup=admin_menu()
    )


# ==================================================
# REFERRAL BONUS SETTING
# ==================================================

@dp.message(F.text == "⚙️ Referal bonus")
async def referral_edit_start(
    message: Message,
    state: FSMContext
):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(ReferralEdit.waiting)

    await message.answer(
        f"Hozirgi bonus: {setting('referral_bonus', DEFAULT_REFERRAL_BONUS)} ⭐\n\n"
        "Yangi bonus miqdorini yuboring:"
    )


@dp.message(ReferralEdit.waiting)
async def referral_edit_finish(
    message: Message,
    state: FSMContext
):
    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.isdigit():
        await message.answer("Musbat raqam yuboring.")
        return

    amount = int(message.text)

    if amount > 100000:
        await message.answer("Miqdor juda katta.")
        return

    set_setting("referral_bonus", amount)
    await state.clear()

    await message.answer(
        f"✅ Referal bonusi {amount} ⭐ qilib belgilandi.",
        reply_markup=admin_menu()
    )


# ==================================================
# SUPPORT
# ==================================================

@dp.message(F.text == "📩 Adminga murojaat")
async def support_start(message: Message, state: FSMContext):
    await state.set_state(Support.waiting)
    await message.answer("Xabaringizni yuboring. Admin’ga yetkaziladi.")


@dp.message(Support.waiting)
async def support_finish(message: Message, state: FSMContext):
    if is_banned(message.from_user.id):
        await state.clear()
        return

    try:
        await bot.send_message(
            ADMIN_ID,
            f"📩 <b>Yangi murojaat</b>\n\n"
            f"👤 {message.from_user.full_name}\n"
            f"🆔 <code>{message.from_user.id}</code>\n"
            f"Username: @{message.from_user.username or 'yo‘q'}"
        )

        await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

        await message.answer(
            "✅ Xabaringiz adminga yuborildi.",
            reply_markup=user_menu()
        )
    except Exception:
        await message.answer("❌ Xabarni yuborib bo‘lmadi.")

    await state.clear()


# ==================================================
# GUIDE
# ==================================================

@dp.message(F.text == "📖 Qo‘llanma")
async def guide(message: Message):
    await message.answer(
        "📖 <b>BOT QO‘LLANMASI</b>\n\n"
        "💰 Mening hisobim — balansingizni ko‘rish.\n"
        "👥 Referal — do‘st taklif qilish.\n"
        "🎁 Gift yechish — 15 yoki 25 Stars buyurtma qilish.\n"
        "📦 Buyurtmalarim — buyurtmalar tarixini ko‘rish.\n"
        "🎟 Promokod — kod orqali Stars olish.\n"
        "🎁 Kunlik bonus — kuniga bir marta bonus olish.\n"
        "📩 Adminga murojaat — admin bilan bog‘lanish."
    )


# ==================================================
# CANCEL
# ==================================================

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()

    if is_admin(message.from_user.id):
        await message.answer(
            "❌ Amal bekor qilindi.",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "❌ Amal bekor qilindi.",
            reply_markup=user_menu()
        )


# ==================================================
# ADMIN COMMAND
# ==================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🛠 Admin panel",
        reply_markup=admin_menu()
    )


# ==================================================
# FALLBACK
# ==================================================

@dp.message()
async def fallback(message: Message):
    if is_banned(message.from_user.id):
        await message.answer("🚫 Siz botdan bloklangansiz.")
        return

    if is_admin(message.from_user.id):
        await message.answer(
            "Admin paneldan kerakli tugmani tanlang.",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "Kerakli tugmani menyudan tanlang.",
            reply_markup=user_menu()
        )


# ==================================================
# RENDER WEB SERVER
# ==================================================

async def health(request):
    return web.Response(text="Bot is running")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()


# ==================================================
# MAIN
# ==================================================

async def main():
    if BOT_TOKEN == "TOKENINGIZNI_BU_YERGA":
        raise RuntimeError("BOT_TOKEN ni kiriting!")

    init_db()
    await start_web_server()

    logging.info("Bot ishga tushdi!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
