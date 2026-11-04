
import asyncio
import logging
import os
import sqlite3
from datetime import date

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# =====================================================
# SOZLAMALAR
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5200398952"))
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")

DAILY_BONUS = 1
DEFAULT_REFERRAL_BONUS = 2

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =====================================================
# DATABASE
# =====================================================

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

db.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    referrer_id INTEGER DEFAULT 0,
    balance INTEGER DEFAULT 0,
    earned_stars INTEGER DEFAULT 0,
    referral_rewarded INTEGER DEFAULT 0,
    banned INTEGER DEFAULT 0,
    last_daily TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    invite_url TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    gift_count INTEGER DEFAULT 0,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'Kutilmoqda',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY,
    amount INTEGER NOT NULL,
    max_uses INTEGER DEFAULT 0,
    used_count INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS promo_uses (
    code TEXT,
    user_id INTEGER,
    PRIMARY KEY(code, user_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
""")

# Eski bazani yangilash
columns = {
    row["name"]
    for row in db.execute("PRAGMA table_info(users)").fetchall()
}

migrations = {
    "username": "TEXT DEFAULT ''",
    "first_name": "TEXT DEFAULT ''",
    "referrer_id": "INTEGER DEFAULT 0",
    "balance": "INTEGER DEFAULT 0",
    "earned_stars": "INTEGER DEFAULT 0",
    "referral_rewarded": "INTEGER DEFAULT 0",
    "banned": "INTEGER DEFAULT 0",
    "last_daily": "TEXT DEFAULT ''",
    "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
}

for name, definition in migrations.items():
    if name not in columns:
        db.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")

order_columns = {
    row["name"]
    for row in db.execute("PRAGMA table_info(orders)").fetchall()
}

if "gift_count" not in order_columns:
    db.execute("ALTER TABLE orders ADD COLUMN gift_count INTEGER DEFAULT 0")

if "description" not in order_columns:
    db.execute("ALTER TABLE orders ADD COLUMN description TEXT DEFAULT ''")

db.commit()


# =====================================================
# YORDAMCHI FUNKSIYALAR
# =====================================================

def is_admin(user_id):
    return user_id == ADMIN_ID


def get_user(user_id):
    return db.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()


def get_setting(key, default):
    row = db.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    return row["value"] if row else str(default)


def set_setting(key, value):
    db.execute("""
        INSERT INTO settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, str(value)))
    db.commit()


def get_channels():
    return db.execute(
        "SELECT * FROM channels ORDER BY title"
    ).fetchall()


def add_stars(user_id, amount, earned=True):
    if earned:
        db.execute("""
            UPDATE users
            SET balance=balance+?, earned_stars=earned_stars+?
            WHERE user_id=?
        """, (amount, amount, user_id))
    else:
        db.execute("""
            UPDATE users SET balance=balance+?
            WHERE user_id=?
        """, (amount, user_id))
    db.commit()


def register_user(user, referrer_id=0):
    old = get_user(user.id)

    if old:
        db.execute("""
            UPDATE users SET username=?, first_name=?
            WHERE user_id=?
        """, (user.username or "", user.first_name or "", user.id))
    else:
        if referrer_id == user.id:
            referrer_id = 0

        if referrer_id and not get_user(referrer_id):
            referrer_id = 0

        db.execute("""
            INSERT INTO users(user_id, username, first_name, referrer_id)
            VALUES(?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            referrer_id
        ))

    db.commit()


async def reward_referrer(user_id):
    user = get_user(user_id)

    if not user or not user["referrer_id"] or user["referral_rewarded"]:
        return

    bonus = int(get_setting("referral_bonus", DEFAULT_REFERRAL_BONUS))

    db.execute(
        "UPDATE users SET referral_rewarded=1 WHERE user_id=?",
        (user_id,)
    )
    db.commit()

    add_stars(user["referrer_id"], bonus)

    try:
        await bot.send_message(
            user["referrer_id"],
            f"🎉 Sizga yangi taklif uchun {bonus} Stars berildi!"
        )
    except Exception:
        pass


async def is_subscribed(user_id):
    for channel in get_channels():
        try:
            member = await bot.get_chat_member(
                channel["channel_id"],
                user_id
            )

            if member.status in ("member", "administrator", "creator"):
                continue

            if member.status == "restricted" and getattr(
                member, "is_member", False
            ):
                continue

            return False

        except Exception as error:
            logging.error("Obuna tekshirish xatosi: %s", error)
            return False

    return True


def user_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Mening hisobim")],
            [
                KeyboardButton(text="🔗 Taklif qilish"),
                KeyboardButton(text="🎁 Gift buyurtma")
            ],
            [
                KeyboardButton(text="📦 Buyurtmalarim"),
                KeyboardButton(text="🎟 Promokod")
            ],
            [
                KeyboardButton(text="🎁 Kunlik bonus"),
                KeyboardButton(text="💬 Adminga murojaat")
            ],
            [KeyboardButton(text="📖 Qo‘llanma")]
        ],
        resize_keyboard=True
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Foydalanuvchilar")],
            [
                KeyboardButton(text="📊 Statistika"),
                KeyboardButton(text="📢 Hammaga xabar")
            ],
            [
                KeyboardButton(text="📡 Kanallar"),
                KeyboardButton(text="📣 Kanallarga reklama")
            ],
            [
                KeyboardButton(text="🎟 Promokod yaratish"),
                KeyboardButton(text="📋 Promokodlar")
            ],
            [
                KeyboardButton(text="🚫 Ban / Unban"),
                KeyboardButton(text="💰 Balans boshqarish")
            ],
            [
                KeyboardButton(text="📦 Buyurtmalar"),
                KeyboardButton(text="⚙️ Referal bonusi")
            ],
            [KeyboardButton(text="⬅️ Asosiy menyu")]
        ],
        resize_keyboard=True
    )


# =====================================================
# HOLATLAR
# =====================================================

class GiftState(StatesGroup):
    count = State()
    description = State()


class BroadcastState(StatesGroup):
    waiting = State()


class AdState(StatesGroup):
    waiting = State()


class ChannelState(StatesGroup):
    waiting = State()


class PromoCreateState(StatesGroup):
    waiting = State()


class PromoUseState(StatesGroup):
    waiting = State()


class BanState(StatesGroup):
    waiting = State()


class BalanceState(StatesGroup):
    waiting = State()


class ReferralState(StatesGroup):
    waiting = State()


class SupportState(StatesGroup):
    waiting = State()


# =====================================================
# OBUNA TUGMALARI
# =====================================================

def subscription_keyboard():
    buttons = []

    for channel in get_channels():
        if channel["invite_url"]:
            buttons.append([
                InlineKeyboardButton(
                    text=f"📢 {channel['title']}",
                    url=channel["invite_url"]
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =====================================================
# START
# =====================================================

@dp.message(CommandStart())
async def start(message: Message, command: CommandObject):
    referrer_id = 0

    if command.args and command.args.isdigit():
        referrer_id = int(command.args)

    register_user(message.from_user, referrer_id)

    user = get_user(message.from_user.id)

    if user["banned"] and not is_admin(message.from_user.id):
        await message.answer("🚫 Siz botdan bloklangansiz.")
        return

    if is_admin(message.from_user.id):
        await message.answer("🛠 Admin panel", reply_markup=admin_menu())
        return

    if not await is_subscribed(message.from_user.id):
        await message.answer(
            "📢 Botdan foydalanish uchun barcha kanallarga obuna bo‘ling:",
            reply_markup=subscription_keyboard()
        )
        return

    await reward_referrer(message.from_user.id)
    await message.answer("🏠 Asosiy menyu", reply_markup=user_menu())


@dp.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery):
    if not await is_subscribed(callback.from_user.id):
        await callback.answer(
            "❌ Barcha kanallarga obuna bo‘ling!",
            show_alert=True
        )
        return

    await reward_referrer(callback.from_user.id)

    await callback.message.answer(
        "✅ Obuna tasdiqlandi!",
        reply_markup=user_menu()
    )
    await callback.answer()


# =====================================================
# FOYDALANUVCHI HISOBI
# =====================================================

@dp.message(F.text == "👤 Mening hisobim")
async def my_account(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        return

    referrals = db.execute("""
        SELECT user_id, first_name, username
        FROM users WHERE referrer_id=?
        ORDER BY created_at DESC
    """, (message.from_user.id,)).fetchall()

    text = (
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Ism: {user['first_name']}\n"
        f"💰 Balans: {user['balance']} Stars\n"
        f"⭐ Jami to‘plagan Stars: {user['earned_stars']}\n"
        f"👥 Taklif qilganlar: {len(referrals)} ta\n\n"
        "<b>Taklif qilgan foydalanuvchilaringiz:</b>\n"
    )

    if referrals:
        for i, person in enumerate(referrals[:40], 1):
            text += (
                f"\n{i}. {person['first_name'] or 'Foydalanuvchi'}"
                f" — ID: {person['user_id']}"
            )
    else:
        text += "\nHozircha takliflar yo‘q."

    await message.answer(text)


@dp.message(F.text == "🔗 Taklif qilish")
async def referral_link(message: Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"
    bonus = get_setting("referral_bonus", DEFAULT_REFERRAL_BONUS)

    await message.answer(
        "🔗 <b>Sizning referal havolangiz:</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Har bir yangi foydalanuvchi uchun {bonus} Stars."
    )


# =====================================================
# KUNLIK BONUS
# =====================================================

@dp.message(F.text == "🎁 Kunlik bonus")
async def daily_bonus(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        return

    today = date.today().isoformat()

    if user["last_daily"] == today:
        await message.answer("⏳ Bugungi bonusni olib bo‘lgansiz.")
        return

    db.execute(
        "UPDATE users SET last_daily=? WHERE user_id=?",
        (today, message.from_user.id)
    )
    db.commit()

    add_stars(message.from_user.id, DAILY_BONUS)

    await message.answer(f"🎉 Sizga {DAILY_BONUS} Stars berildi!")


# =====================================================
# GIFT BUYURTMA
# =====================================================

@dp.message(F.text == "🎁 Gift buyurtma")
async def gift_start(message: Message, state: FSMContext):
    await state.set_state(GiftState.count)
    await message.answer(
        "🎁 Nechta gift buyurtma qilmoqchisiz?\n\n"
        "Faqat son yuboring. Masalan: 10"
    )


@dp.message(GiftState.count)
async def gift_count(message: Message, state: FSMContext):
    try:
        count = int(message.text)

        if count < 1 or count > 10000:
            await message.answer("1 dan 10000 gacha son kiriting.")
            return

        await state.update_data(gift_count=count)
        await state.set_state(GiftState.description)

        await message.answer(
            f"🎁 {count} ta gift tanlandi.\n"
            "Endi gift haqida qo‘shimcha ma’lumot yoki username yuboring."
        )

    except (ValueError, TypeError):
        await message.answer("Faqat raqam yuboring. Masalan: 10")


@dp.message(GiftState.description)
async def gift_description(message: Message, state: FSMContext):
    data = await state.get_data()
    count = data["gift_count"]

    db.execute("""
        INSERT INTO orders(user_id, gift_count, description)
        VALUES (?, ?, ?)
    """, (
        message.from_user.id,
        count,
        message.text or "Izoh yo‘q"
    ))
    db.commit()

    order_id = db.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    await state.clear()

    await message.answer(
        "✅ Gift buyurtmangiz adminga yuborildi!\n\n"
        f"📦 Buyurtma: #{order_id}\n"
        f"🎁 Gift soni: {count} ta",
        reply_markup=user_menu()
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            "🎁 <b>YANGI GIFT BUYURTMA</b>\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"👤 Ism: {message.from_user.full_name}\n"
            f"🆔 User ID: <code>{message.from_user.id}</code>\n"
            f"🔗 Username: @{message.from_user.username or 'yo‘q'}\n"
            f"🎁 Gift miqdori: <b>{count} ta</b>\n"
            f"📝 Izoh: {message.text or 'yo‘q'}"
        )
    except Exception:
        logging.exception("Adminga buyurtma xabari yuborilmadi")


# =====================================================
# FOYDALANUVCHI BUYURTMALARI
# =====================================================

@dp.message(F.text == "📦 Buyurtmalarim")
async def my_orders(message: Message):
    orders = db.execute("""
        SELECT * FROM orders
        WHERE user_id=?
        ORDER BY id DESC LIMIT 20
    """, (message.from_user.id,)).fetchall()

    if not orders:
        await message.answer("Sizda hozircha buyurtmalar yo‘q.")
        return

    text = "📦 <b>BUYURTMALARIM</b>\n\n"

    for order in orders:
        text += (
            f"#{order['id']}\n"
            f"🎁 Gift: {order['gift_count']} ta\n"
            f"📝 {order['description']}\n"
            f"📌 Holati: {order['status']}\n\n"
        )

    await message.answer(text)


# =====================================================
# PROMOKOD ISHLATISH
# =====================================================

@dp.message(F.text == "🎟 Promokod")
async def promo_start(message: Message, state: FSMContext):
    await state.set_state(PromoUseState.waiting)
    await message.answer("🎟 Promokodingizni yuboring:")


@dp.message(PromoUseState.waiting)
async def promo_redeem(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    user_id = message.from_user.id

    promo = db.execute(
        "SELECT * FROM promo_codes WHERE code=? AND active=1",
        (code,)
    ).fetchone()

    if not promo:
        await message.answer("❌ Promokod noto‘g‘ri yoki faol emas.")
        await state.clear()
        return

    used = db.execute(
        "SELECT 1 FROM promo_uses WHERE code=? AND user_id=?",
        (code, user_id)
    ).fetchone()

    if used:
        await message.answer("❌ Siz bu promokodni oldin ishlatgansiz.")
        await state.clear()
        return

    if promo["max_uses"] > 0 and promo["used_count"] >= promo["max_uses"]:
        await message.answer("❌ Bu promokoddan foydalanish limiti tugagan.")
        await state.clear()
        return

    db.execute(
        "INSERT INTO promo_uses(code, user_id) VALUES(?, ?)",
        (code, user_id)
    )
    db.execute(
        "UPDATE promo_codes SET used_count=used_count+1 WHERE code=?",
        (code,)
    )
    db.commit()

    add_stars(user_id, promo["amount"])
    await state.clear()

    await message.answer(
        f"🎉 Promokod qabul qilindi!\n"
        f"⭐ Hisobingizga {promo['amount']} Stars qo‘shildi."
    )


# =====================================================
# ADMIN: PROMOKOD YARATISH
# =====================================================

@dp.message(F.text == "🎟 Promokod yaratish")
async def promo_create_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(PromoCreateState.waiting)

    await message.answer(
        "Promokodni quyidagi formatda yuboring:\n\n"
        "<code>KOD STARS LIMIT</code>\n\n"
        "Masalan:\n"
        "<code>WELCOME 50 100</code>\n\n"
        "Bu 100 foydalanuvchiga 50 Stars beradi.\n"
        "Limit cheklanmasin desangiz 0 yozing."
    )


@dp.message(PromoCreateState.waiting)
async def promo_create_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        code, amount, limit = message.text.split()
        code = code.upper()
        amount = int(amount)
        limit = int(limit)

        if not code.isalnum() or amount < 1 or limit < 0:
            raise ValueError

        db.execute("""
            INSERT INTO promo_codes(code, amount, max_uses)
            VALUES (?, ?, ?)
        """, (code, amount, limit))
        db.commit()

        await state.clear()

        await message.answer(
            "✅ Promokod yaratildi!\n\n"
            f"🎟 Kod: <code>{code}</code>\n"
            f"⭐ Mukofot: {amount} Stars\n"
            f"👥 Limit: {'Cheksiz' if limit == 0 else limit}"
        )

    except sqlite3.IntegrityError:
        await message.answer("Bu promokod avval yaratilgan.")
    except Exception:
        await message.answer(
            "Format xato.\nMasalan: <code>WELCOME 50 100</code>"
        )


@dp.message(F.text == "📋 Promokodlar")
async def promo_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    promos = db.execute(
        "SELECT * FROM promo_codes ORDER BY rowid DESC LIMIT 30"
    ).fetchall()

    if not promos:
        await message.answer("Promokodlar yo‘q.")
        return

    for promo in promos:
        await message.answer(
            f"🎟 Kod: {promo['code']}\n"
            f"⭐ Mukofot: {promo['amount']} Stars\n"
            f"👥 Ishlatilgan: {promo['used_count']}\n"
            f"📌 Limit: {promo['max_uses'] or 'Cheksiz'}\n"
            f"Holati: {'Faol' if promo['active'] else 'O‘chirilgan'}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 O‘chirish",
                        callback_data=f"promo_del:{promo['code']}"
                    )
                ]
            ])
        )


@dp.callback_query(F.data.startswith("promo_del:"))
async def promo_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    code = callback.data.split(":", 1)[1]

    db.execute(
        "UPDATE promo_codes SET active=0 WHERE code=?",
        (code,)
    )
    db.commit()

    await callback.message.answer("✅ Promokod o‘chirildi.")
    await callback.answer()


# =====================================================
# ADMIN: BARCHA FOYDALANUVCHILARGA XABAR
# =====================================================

@dp.message(F.text == "📢 Hammaga xabar")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(BroadcastState.waiting)

    await message.answer(
        "📢 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring.\n\n"
        "Matn, rasm, video yoki boshqa Telegram xabarini yuborishingiz mumkin."
    )


@dp.message(BroadcastState.waiting)
async def broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    users = db.execute(
        "SELECT user_id FROM users WHERE banned=0"
    ).fetchall()

    sent = 0
    failed = 0

    status = await message.answer(
        f"⏳ Xabar {len(users)} ta foydalanuvchiga yuborilmoqda..."
    )

    for user in users:
        try:
            await bot.copy_message(
                chat_id=user["user_id"],
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            sent += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.04)

    await state.clear()

    await status.edit_text(
        "📢 <b>XABAR TARQATISH YAKUNLANDI</b>\n\n"
        f"✅ Yetkazildi: {sent}\n"
        f"❌ Yetkazilmadi: {failed}\n"
        f"👥 Jami: {len(users)}"
    )


# =====================================================
# ADMIN: KANALLARNI BOSHQARISH
# =====================================================

@dp.message(F.text == "📡 Kanallar")
async def channels_menu(message: Message):
    if not is_admin(message.from_user.id):
        return

    channels = get_channels()
    text = "📡 <b>KANALLAR RO‘YXATI</b>\n\n"

    for channel in channels:
        text += (
            f"📢 {channel['title']}\n"
            f"🆔 <code>{channel['channel_id']}</code>\n\n"
        )

    if not channels:
        text += "Hozircha kanal qo‘shilmagan.\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="➕ Kanal qo‘shish",
                callback_data="channel_add"
            )
        ],
        [
            InlineKeyboardButton(
                text="➖ Kanalni o‘chirish",
                callback_data="channel_remove"
            )
        ]
    ])

    await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data == "channel_add")
async def channel_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    await state.set_state(ChannelState.waiting)

    await callback.message.answer(
        "Kanal username yoki ID sini yuboring.\n\n"
        "Ommaviy kanal: <code>@kanal_username</code>\n"
        "Yopiq kanal: <code>-1001234567890</code>\n\n"
        "Bot avval o‘sha kanalga administrator qilingan bo‘lishi kerak."
    )
    await callback.answer()


@dp.message(ChannelState.waiting)
async def channel_add_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        chat = await bot.get_chat(message.text.strip())

        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)

        if chat.type != "channel":
            await message.answer("Bu Telegram kanal emas.")
            return

        if member.status not in ("administrator", "creator"):
            await message.answer("Bot bu kanalga administrator qilinmagan.")
            return

        if not getattr(member, "can_post_messages", False):
            await message.answer(
                "Botga kanalga xabar yuborish huquqini bering."
            )
            return

        invite_url = (
            f"https://t.me/{chat.username}"
            if chat.username
            else ""
        )

        if not invite_url:
            invite_url = await bot.export_chat_invite_link(chat.id)

        db.execute("""
            INSERT INTO channels(channel_id, title, invite_url)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                title=excluded.title,
                invite_url=excluded.invite_url
        """, (str(chat.id), chat.title or "Kanal", invite_url))
        db.commit()

        await state.clear()

        await message.answer(
            f"✅ Kanal qo‘shildi!\n"
            f"📢 {chat.title}\n"
            f"🆔 {chat.id}\n\n"
            "Bu kanal majburiy obuna va reklama tarqatish ro‘yxatiga qo‘shildi."
        )

    except Exception:
        logging.exception("Kanal qo‘shish xatosi")
        await message.answer(
            "❌ Kanal qo‘shilmadi. Username/ID va bot admin huquqlarini tekshiring."
        )


@dp.callback_query(F.data == "channel_remove")
async def channel_remove_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    channels = get_channels()

    if not channels:
        await callback.message.answer("Kanallar yo‘q.")
        await callback.answer()
        return

    buttons = []

    for channel in channels:
        buttons.append([
            InlineKeyboardButton(
                text=f"❌ {channel['title']}",
                callback_data=f"channel_del:{channel['channel_id']}"
            )
        ])

    await callback.message.answer(
        "O‘chirmoqchi bo‘lgan kanalni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("channel_del:"))
async def channel_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    channel_id = callback.data.split(":", 1)[1]

    db.execute(
        "DELETE FROM channels WHERE channel_id=?",
        (channel_id,)
    )
    db.commit()

    await callback.message.answer("✅ Kanal o‘chirildi.")
    await callback.answer()


# =====================================================
# ADMIN: BARCHA KANALLARGA REKLAMA
# =====================================================

@dp.message(F.text == "📣 Kanallarga reklama")
async def ad_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channels = get_channels()

    if not channels:
        await message.answer("Avval kanallar qo‘shing.")
        return

    await state.set_state(AdState.waiting)

    await message.answer(
        f"📣 Reklama xabarini yuboring.\n"
        f"Xabar {len(channels)} ta kanalingizga tarqatiladi.\n\n"
        "Matn, rasm, video yoki boshqa xabar yuborishingiz mumkin."
    )


@dp.message(AdState.waiting)
async def ad_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    channels = get_channels()
    sent = 0
    failed = []

    status = await message.answer("⏳ Reklama yuborilmoqda...")

    for channel in channels:
        try:
            await bot.copy_message(
                chat_id=channel["channel_id"],
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            sent += 1
        except Exception as error:
            logging.error("Kanalga reklama xatosi: %s", error)
            failed.append(channel["title"])

        await asyncio.sleep(0.1)

    await state.clear()

    result = (
        "📣 <b>REKLAMA NATIJASI</b>\n\n"
        f"✅ Yuborildi: {sent}\n"
        f"❌ Xato: {len(failed)}"
    )

    if failed:
        result += "\n\nXato bo‘lgan kanallar:\n"
        result += "\n".join(f"• {name}" for name in failed[:30])

    await status.edit_text(result)


# =====================================================
# ADMIN: FOYDALANUVCHILAR VA PROFIL
# =====================================================

@dp.message(F.text == "👥 Foydalanuvchilar")
async def users_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    users = db.execute("""
        SELECT user_id, first_name
        FROM users ORDER BY created_at DESC LIMIT 50
    """).fetchall()

    if not users:
        await message.answer("Foydalanuvchilar yo‘q.")
        return

    buttons = []

    for user in users:
        buttons.append([
            InlineKeyboardButton(
                text=f"{user['first_name'] or 'User'} | {user['user_id']}",
                callback_data=f"user:{user['user_id']}"
            )
        ])

    await message.answer(
        "👥 Oxirgi 50 foydalanuvchi:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("user:"))
async def user_detail(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    user_id = int(callback.data.split(":", 1)[1])
    user = get_user(user_id)

    if not user:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    referrals = db.execute(
        "SELECT user_id, first_name FROM users WHERE referrer_id=?",
        (user_id,)
    ).fetchall()

    orders = db.execute(
        "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (user_id,)
    ).fetchall()

    text = (
        "👤 <b>FOYDALANUVCHI PROFILI</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Ism: {user['first_name']}\n"
        f"🔗 Username: @{user['username'] or 'yo‘q'}\n"
        f"💰 Balans: {user['balance']} Stars\n"
        f"⭐ Jami to‘plagan: {user['earned_stars']} Stars\n"
        f"👥 Referallar: {len(referrals)} ta\n"
        f"🚫 Ban: {'Ha' if user['banned'] else 'Yo‘q'}\n\n"
        "<b>Taklif qilgan foydalanuvchilari:</b>\n"
    )

    for person in referrals[:20]:
        text += f"\n• {person['first_name']} — {person['user_id']}"

    text += "\n\n<b>Oxirgi buyurtmalari:</b>\n"

    if orders:
        for order in orders:
            text += (
                f"\n#{order['id']} — {order['gift_count']} ta gift"
                f"\nHolati: {order['status']}"
            )
    else:
        text += "\nBuyurtma yo‘q."

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🚫 Ban",
                callback_data=f"ban:{user_id}"
            ),
            InlineKeyboardButton(
                text="✅ Unban",
                callback_data=f"unban:{user_id}"
            )
        ]
    ])

    await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


# =====================================================
# ADMIN: BAN / UNBAN
# =====================================================

@dp.message(F.text == "🚫 Ban / Unban")
async def ban_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(BanState.waiting)
    await message.answer(
        "Foydalanuvchi ID sini yuboring.\n\n"
        "Masalan: <code>123456789</code>"
    )


@dp.message(BanState.waiting)
async def ban_by_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        user_id = int(message.text)

        if user_id == ADMIN_ID:
            await message.answer("Adminni bloklab bo‘lmaydi.")
            return

        if not get_user(user_id):
            await message.answer("Foydalanuvchi topilmadi.")
            return

        db.execute(
            "UPDATE users SET banned=1 WHERE user_id=?",
            (user_id,)
        )
        db.commit()

        await state.clear()
        await message.answer(f"🚫 {user_id} bloklandi.")

        try:
            await bot.send_message(user_id, "🚫 Siz admin tomonidan bloklandingiz.")
        except Exception:
            pass

    except Exception:
        await message.answer("ID raqamini to‘g‘ri yuboring.")


@dp.callback_query(F.data.startswith("ban:"))
async def ban_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    user_id = int(callback.data.split(":")[1])

    if user_id == ADMIN_ID:
        await callback.answer("Adminni bloklab bo‘lmaydi.", show_alert=True)
        return

    db.execute(
        "UPDATE users SET banned=1 WHERE user_id=?",
        (user_id,)
    )
    db.commit()

    await callback.message.answer(f"🚫 {user_id} bloklandi.")
    await callback.answer()


@dp.callback_query(F.data.startswith("unban:"))
async def unban_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    user_id = int(callback.data.split(":")[1])

    db.execute(
        "UPDATE users SET banned=0 WHERE user_id=?",
        (user_id,)
    )
    db.commit()

    await callback.message.answer(f"✅ {user_id} blokdan chiqarildi.")
    await callback.answer()


# =====================================================
# ADMIN: BALANS
# =====================================================

@dp.message(F.text == "💰 Balans boshqarish")
async def balance_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(BalanceState.waiting)
    await message.answer(
        "Format:\n<code>USER_ID MIQDOR</code>\n\n"
        "Masalan:\n<code>123456789 50</code>\n"
        "50 Stars qo‘shadi.\n"
        "<code>123456789 -20</code>\n"
        "20 Stars ayiradi."
    )


@dp.message(BalanceState.waiting)
async def balance_change(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        user_id, amount = map(int, message.text.split())
        user = get_user(user_id)

        if not user:
            await message.answer("Foydalanuvchi topilmadi.")
            return

        if user["balance"] + amount < 0:
            await message.answer("Balans manfiy bo‘lishi mumkin emas.")
            return

        if amount >= 0:
            add_stars(user_id, amount)
        else:
            db.execute(
                "UPDATE users SET balance=balance+? WHERE user_id=?",
                (amount, user_id)
            )
            db.commit()

        await state.clear()
        await message.answer("✅ Balans yangilandi.")

        try:
            await bot.send_message(
                user_id,
                f"💰 Balansingiz o‘zgartirildi: {amount:+} Stars"
            )
        except Exception:
            pass

    except Exception:
        await message.answer("Format xato. Masalan: 123456789 50")


# =====================================================
# ADMIN: REFERAL BONUS
# =====================================================

@dp.message(F.text == "⚙️ Referal bonusi")
async def referral_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    current = get_setting("referral_bonus", DEFAULT_REFERRAL_BONUS)
    await state.set_state(ReferralState.waiting)

    await message.answer(
        f"Hozirgi bonus: {current} Stars.\n"
        "Yangi miqdorni yuboring:"
    )


@dp.message(ReferralState.waiting)
async def referral_change(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        amount = int(message.text)

        if amount < 0 or amount > 100000:
            await message.answer("0 dan 100000 gacha son yuboring.")
            return

        set_setting("referral_bonus", amount)
        await state.clear()

        await message.answer(f"✅ Referal bonusi {amount} Stars bo‘ldi.")

    except Exception:
        await message.answer("Faqat raqam yuboring.")


# =====================================================
# ADMIN: STATISTIKA
# =====================================================

@dp.message(F.text == "📊 Statistika")
async def statistics(message: Message):
    if not is_admin(message.from_user.id):
        return

    users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    banned = db.execute(
        "SELECT COUNT(*) FROM users WHERE banned=1"
    ).fetchone()[0]
    orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    gifts = db.execute(
        "SELECT SUM(gift_count) FROM orders"
    ).fetchone()[0] or 0
    balance = db.execute(
        "SELECT SUM(balance) FROM users"
    ).fetchone()[0] or 0
    earned = db.execute(
        "SELECT SUM(earned_stars) FROM users"
    ).fetchone()[0] or 0

    await message.answer(
        "📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"🚫 Bloklanganlar: {banned}\n"
        f"📦 Buyurtmalar: {orders}\n"
        f"🎁 Buyurtma qilingan giftlar: {gifts} ta\n"
        f"💰 Jami balans: {balance} Stars\n"
        f"⭐ Jami to‘plangan: {earned} Stars\n"
        f"📡 Kanallar: {len(get_channels())} ta"
    )


# =====================================================
# ADMIN: BUYURTMALAR VA HOLATINI O‘ZGARTIRISH
# =====================================================

@dp.message(F.text == "📦 Buyurtmalar")
async def admin_orders(message: Message):
    if not is_admin(message.from_user.id):
        return

    orders = db.execute(
        "SELECT * FROM orders ORDER BY id DESC LIMIT 20"
    ).fetchall()

    if not orders:
        await message.answer("Buyurtmalar yo‘q.")
        return

    for order in orders:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Bajarildi",
                    callback_data=f"order_done:{order['id']}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=f"order_reject:{order['id']}"
                )
            ]
        ])

        await message.answer(
            f"📦 Buyurtma #{order['id']}\n"
            f"👤 User: {order['user_id']}\n"
            f"🎁 Gift: {order['gift_count']} ta\n"
            f"📝 Izoh: {order['description']}\n"
            f"📌 Holat: {order['status']}",
            reply_markup=keyboard
        )


@dp.callback_query(F.data.startswith("order_done:"))
async def order_done(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])

    order = db.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

    if not order:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return

    db.execute(
        "UPDATE orders SET status='Bajarildi' WHERE id=?",
        (order_id,)
    )
    db.commit()

    try:
        await bot.send_message(
            order["user_id"],
            f"✅ #{order_id} raqamli buyurtmangiz bajarildi."
        )
    except Exception:
        pass

    await callback.message.edit_text(
        callback.message.text + "\n\n✅ HOLATI: BAJARILDI"
    )
    await callback.answer("Buyurtma bajarildi.")


@dp.callback_query(F.data.startswith("order_reject:"))
async def order_reject(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])

    order = db.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

    if not order:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return

    db.execute(
        "UPDATE orders SET status='Rad etildi' WHERE id=?",
        (order_id,)
    )
    db.commit()

    try:
        await bot.send_message(
            order["user_id"],
            f"❌ #{order_id} raqamli buyurtmangiz rad etildi."
        )
    except Exception:
        pass

    await callback.message.edit_text(
        callback.message.text + "\n\n❌ HOLATI: RAD ETILDI"
    )
    await callback.answer("Buyurtma rad etildi.")


# =====================================================
# QO‘LLANMA VA MUROJAAT
# =====================================================

@dp.message(F.text == "📖 Qo‘llanma")
async def guide(message: Message):
    await message.answer(
        "📖 <b>QO‘LLANMA</b>\n\n"
        "👤 Mening hisobim — balans va referallar.\n"
        "🔗 Taklif qilish — referal havolasi.\n"
        "🎁 Gift buyurtma — gift sonini yuborish.\n"
        "🎟 Promokod — promokodni ishlatish.\n"
        "📦 Buyurtmalarim — buyurtmalar holati.\n"
        "🎁 Kunlik bonus — har kungi bonus."
    )


@dp.message(F.text == "💬 Adminga murojaat")
async def support_start(message: Message, state: FSMContext):
    await state.set_state(SupportState.waiting)
    await message.answer("Adminga yuboriladigan xabarni yozing:")


@dp.message(SupportState.waiting)
async def support_send(message: Message, state: FSMContext):
    await state.clear()

    try:
        await bot.send_message(
            ADMIN_ID,
            f"💬 Yangi murojaat\n"
            f"👤 {message.from_user.full_name}\n"
            f"🆔 {message.from_user.id}"
        )
        await bot.copy_message(
            ADMIN_ID,
            message.chat.id,
            message.message_id
        )
        await message.answer("✅ Xabaringiz adminga yuborildi.")
    except Exception:
        await message.answer("❌ Xabar yuborilmadi.")


# =====================================================
# ADMIN BUYRUQLARI
# =====================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("🛠 Admin panel", reply_markup=admin_menu())


@dp.message(Command("cancel"))
async def cancel_state(message: Message, state: FSMContext):
    await state.clear()

    if is_admin(message.from_user.id):
        await message.answer("❌ Amal bekor qilindi.", reply_markup=admin_menu())
    else:
        await message.answer("❌ Amal bekor qilindi.", reply_markup=user_menu())


@dp.message(F.text == "⬅️ Asosiy menyu")
async def back_menu(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("Admin panel", reply_markup=admin_menu())
    else:
        await message.answer("Asosiy menyu", reply_markup=user_menu())


# =====================================================
# OXIRGI XABAR HANDLER
# =====================================================

@dp.message()
async def fallback(message: Message):
    user = get_user(message.from_user.id)

    if user and user["banned"] and not is_admin(message.from_user.id):
        await message.answer("🚫 Siz botdan bloklangansiz.")
        return

    if is_admin(message.from_user.id):
        await message.answer(
            "Admin paneldagi tugmalardan foydalaning.",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "Menyudagi tugmalardan foydalaning.",
            reply_markup=user_menu()
        )


# =====================================================
# RENDER SERVER
# =====================================================

async def health(request):
    return web.Response(text="Bot is running!")


async def main():
    if BOT_TOKEN == "TOKEN_BU_YERGA":
        raise RuntimeError("BOT_TOKEN sozlanmagan!")

    app = web.Application()
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logging.info("Render web server ishga tushdi.")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
