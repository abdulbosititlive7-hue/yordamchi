
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

# ==================================================
# SOZLAMALAR
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5200398952"))
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")

DAILY_BONUS = 1
DEFAULT_REFERRAL_BONUS = 2

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================================================
# DATABASE
# ==================================================

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

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    description TEXT,
    status TEXT DEFAULT 'Kutilmoqda',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    username TEXT DEFAULT '',
    invite_url TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
""")

# Eski bazani yangilash
columns = [
    row["name"]
    for row in db.execute("PRAGMA table_info(users)").fetchall()
]

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

for column, definition in migrations.items():
    if column not in columns:
        db.execute(
            f"ALTER TABLE users ADD COLUMN {column} {definition}"
        )

db.commit()


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


def get_user(user_id):
    return db.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()


def get_channels():
    return db.execute(
        "SELECT * FROM channels ORDER BY title"
    ).fetchall()


def add_stars(user_id, amount, earned=True):
    if earned:
        db.execute("""
            UPDATE users
            SET balance=balance+?,
                earned_stars=earned_stars+?
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
            UPDATE users
            SET username=?, first_name=?
            WHERE user_id=?
        """, (
            user.username or "",
            user.first_name or "",
            user.id
        ))
    else:
        if referrer_id == user.id:
            referrer_id = 0

        if referrer_id and not get_user(referrer_id):
            referrer_id = 0

        db.execute("""
            INSERT INTO users(
                user_id, username, first_name, referrer_id
            )
            VALUES (?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            referrer_id
        ))

    db.commit()


async def reward_referrer(user_id):
    user = get_user(user_id)

    if not user:
        return

    referrer_id = user["referrer_id"]

    if not referrer_id or user["referral_rewarded"]:
        return

    bonus = int(get_setting(
        "referral_bonus",
        DEFAULT_REFERRAL_BONUS
    ))

    db.execute("""
        UPDATE users SET referral_rewarded=1
        WHERE user_id=?
    """, (user_id,))
    db.commit()

    add_stars(referrer_id, bonus)

    try:
        await bot.send_message(
            referrer_id,
            f"🎉 Yangi taklif uchun {bonus} Stars hisobingizga qo‘shildi!"
        )
    except Exception:
        pass


def is_admin(user_id):
    return user_id == ADMIN_ID


# ==================================================
# FSM HOLATLARI
# ==================================================

class OrderState(StatesGroup):
    waiting = State()


class AdState(StatesGroup):
    waiting = State()


class AddChannelState(StatesGroup):
    waiting = State()


class BalanceState(StatesGroup):
    waiting = State()


class ReferralState(StatesGroup):
    waiting = State()


class SupportState(StatesGroup):
    waiting = State()


# ==================================================
# MENYULAR
# ==================================================

def user_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Mening hisobim")],
            [
                KeyboardButton(text="🔗 Taklif qilish"),
                KeyboardButton(text="📦 Buyurtma berish")
            ],
            [
                KeyboardButton(text="📋 Buyurtmalarim"),
                KeyboardButton(text="🎁 Kunlik bonus")
            ],
            [
                KeyboardButton(text="💬 Adminga murojaat"),
                KeyboardButton(text="📖 Qo‘llanma")
            ]
        ],
        resize_keyboard=True
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Foydalanuvchilar")],
            [
                KeyboardButton(text="📊 Statistika"),
                KeyboardButton(text="📢 Kanalga reklama")
            ],
            [
                KeyboardButton(text="📡 Kanallar boshqaruvi"),
                KeyboardButton(text="📦 Buyurtmalar")
            ],
            [
                KeyboardButton(text="💰 Balans boshqarish"),
                KeyboardButton(text="⚙️ Referal sozlamasi")
            ],
            [KeyboardButton(text="⬅️ Asosiy menyu")]
        ],
        resize_keyboard=True
    )


# ==================================================
# KANALLAR VA MAJBURIY OBUNA
# ==================================================

def subscription_keyboard():
    buttons = []

    for channel in get_channels():
        url = channel["invite_url"]

        if url:
            buttons.append([
                InlineKeyboardButton(
                    text=f"📢 {channel['title'] or 'Kanalga obuna'}",
                    url=url
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def subscription_ok(user_id):
    channels = get_channels()

    for channel in channels:
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

        except Exception as e:
            logging.error(
                "Kanal obunasini tekshirish xatosi %s: %s",
                channel["channel_id"],
                e
            )
            return False

    return True


async def show_start(message):
    if is_admin(message.from_user.id):
        await message.answer(
            "🛠 Admin panelga xush kelibsiz!",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "🏠 Asosiy menyu",
            reply_markup=user_menu()
        )


# ==================================================
# START
# ==================================================

@dp.message(CommandStart())
async def start(message: Message, command: CommandObject):
    referrer_id = 0

    if command.args and command.args.isdigit():
        referrer_id = int(command.args)

    register_user(message.from_user, referrer_id)

    user = get_user(message.from_user.id)

    if user["banned"]:
        await message.answer("⛔ Siz botdan foydalanish huquqidan mahrum qilingansiz.")
        return

    if is_admin(message.from_user.id):
        await show_start(message)
        return

    if not await subscription_ok(message.from_user.id):
        await message.answer(
            "📢 Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
            reply_markup=subscription_keyboard()
        )
        return

    await reward_referrer(message.from_user.id)
    await show_start(message)


@dp.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery):
    if not await subscription_ok(callback.from_user.id):
        await callback.answer(
            "❌ Hamma kanallarga obuna bo‘ling!",
            show_alert=True
        )
        return

    await reward_referrer(callback.from_user.id)

    await callback.message.answer(
        "✅ Obuna tasdiqlandi!",
        reply_markup=user_menu()
    )

    await callback.answer()


# ==================================================
# FOYDALANUVCHI HISOBI
# ==================================================

@dp.message(F.text == "👤 Mening hisobim")
async def my_account(message: Message):
    user = get_user(message.from_user.id)

    if not user:
        return

    referrals = db.execute("""
        SELECT user_id, username, first_name
        FROM users
        WHERE referrer_id=?
        ORDER BY created_at DESC
    """, (message.from_user.id,)).fetchall()

    text = (
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Ism: {user['first_name']}\n"
        f"💰 Balans: {user['balance']} Stars\n"
        f"⭐ Jami to‘plagan Stars: {user['earned_stars']}\n"
        f"👥 Taklif qilganlar: {len(referrals)} ta\n\n"
        "📋 <b>Siz taklif qilgan foydalanuvchilar:</b>\n"
    )

    if referrals:
        for i, person in enumerate(referrals[:30], 1):
            name = person["first_name"] or "Foydalanuvchi"
            username = (
                "@" + person["username"]
                if person["username"] else "username yo‘q"
            )
            text += f"\n{i}. {name} — {username}"
    else:
        text += "\nHozircha hech kimni taklif qilmagansiz."

    await message.answer(text)


# ==================================================
# REFERAL
# ==================================================

@dp.message(F.text == "🔗 Taklif qilish")
async def referral(message: Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"

    bonus = get_setting(
        "referral_bonus",
        DEFAULT_REFERRAL_BONUS
    )

    await message.answer(
        "🔗 <b>SIZNING TAKLIF HAVOLANGIZ</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Har bir yangi taklif uchun {bonus} Stars olasiz."
    )


# ==================================================
# KUNLIK BONUS
# ==================================================

@dp.message(F.text == "🎁 Kunlik bonus")
async def daily_bonus(message: Message):
    user = get_user(message.from_user.id)

    if not user:
        return

    today = date.today().isoformat()

    if user["last_daily"] == today:
        await message.answer("⏳ Bugungi bonusni olib bo‘lgansiz.")
        return

    db.execute("""
        UPDATE users SET last_daily=?
        WHERE user_id=?
    """, (today, message.from_user.id))
    db.commit()

    add_stars(message.from_user.id, DAILY_BONUS)

    await message.answer(
        f"🎉 Sizga {DAILY_BONUS} Stars bonus berildi!"
    )


# ==================================================
# BUYURTMA
# ==================================================

@dp.message(F.text == "📦 Buyurtma berish")
async def new_order(message: Message, state: FSMContext):
    await state.set_state(OrderState.waiting)
    await message.answer(
        "📦 Buyurtmangiz haqida ma’lumot yuboring:"
    )


@dp.message(OrderState.waiting)
async def save_order(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Buyurtmani matn ko‘rinishida yuboring.")
        return

    db.execute("""
        INSERT INTO orders(user_id, description)
        VALUES (?, ?)
    """, (message.from_user.id, message.text))
    db.commit()

    order_id = db.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    await state.clear()

    await message.answer(
        f"✅ Buyurtmangiz qabul qilindi!\n"
        f"📦 Raqami: #{order_id}"
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            f"📦 Yangi buyurtma!\n"
            f"🆔 #{order_id}\n"
            f"👤 User ID: {message.from_user.id}\n"
            f"📝 {message.text}"
        )
    except Exception:
        pass


@dp.message(F.text == "📋 Buyurtmalarim")
async def my_orders(message: Message):
    orders = db.execute("""
        SELECT * FROM orders
        WHERE user_id=?
        ORDER BY id DESC LIMIT 20
    """, (message.from_user.id,)).fetchall()

    if not orders:
        await message.answer("Sizda hozircha buyurtmalar yo‘q.")
        return

    text = "📋 <b>BUYURTMALARIM</b>\n\n"

    for order in orders:
        text += (
            f"📦 #{order['id']}\n"
            f"📝 {order['description']}\n"
            f"📌 Holati: {order['status']}\n\n"
        )

    await message.answer(text)


# ==================================================
# QO‘LLANMA
# ==================================================

@dp.message(F.text == "📖 Qo‘llanma")
async def guide(message: Message):
    await message.answer(
        "📖 <b>BOT QO‘LLANMASI</b>\n\n"
        "👤 Mening hisobim — balans va takliflar.\n"
        "🔗 Taklif qilish — referal havolangiz.\n"
        "📦 Buyurtma berish — buyurtma yuborish.\n"
        "🎁 Kunlik bonus — har kuni bonus olish.\n"
        "💬 Adminga murojaat — admin bilan bog‘lanish."
    )


# ==================================================
# ADIMGA MUROJAAT
# ==================================================

@dp.message(F.text == "💬 Adminga murojaat")
async def support_start(message: Message, state: FSMContext):
    await state.set_state(SupportState.waiting)
    await message.answer("✍️ Adminga yuboriladigan xabarni yuboring:")


@dp.message(SupportState.waiting)
async def support_send(message: Message, state: FSMContext):
    await state.clear()

    try:
        await bot.send_message(
            ADMIN_ID,
            f"💬 Yangi murojaat\n"
            f"👤 ID: {message.from_user.id}\n"
            f"Ism: {message.from_user.full_name}"
        )

        await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

        await message.answer("✅ Xabaringiz adminga yuborildi.")

    except Exception:
        await message.answer("❌ Xabar yuborilmadi.")


# ==================================================
# ADMIN PANEL
# ==================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🛠 Admin panel",
        reply_markup=admin_menu()
    )


@dp.message(F.text == "⬅️ Asosiy menyu")
async def back_menu(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("Admin panel", reply_markup=admin_menu())
    else:
        await message.answer("Asosiy menyu", reply_markup=user_menu())


# ==================================================
# ADMIN: STATISTIKA
# ==================================================

@dp.message(F.text == "📊 Statistika")
async def statistics(message: Message):
    if not is_admin(message.from_user.id):
        return

    users = db.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    orders = db.execute(
        "SELECT COUNT(*) FROM orders"
    ).fetchone()[0]

    balance = db.execute(
        "SELECT SUM(balance) FROM users"
    ).fetchone()[0] or 0

    earned = db.execute(
        "SELECT SUM(earned_stars) FROM users"
    ).fetchone()[0] or 0

    channels = len(get_channels())

    await message.answer(
        "📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"📦 Buyurtmalar: {orders}\n"
        f"💰 Foydalanuvchilar balanslari: {balance} Stars\n"
        f"⭐ Jami to‘plangan Stars: {earned}\n"
        f"📡 Kanallar: {channels} ta"
    )


# ==================================================
# ADMIN: FOYDALANUVCHILAR
# ==================================================

@dp.message(F.text == "👥 Foydalanuvchilar")
async def users_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    users = db.execute("""
        SELECT user_id, first_name, username
        FROM users
        ORDER BY created_at DESC
        LIMIT 50
    """).fetchall()

    if not users:
        await message.answer("Foydalanuvchilar yo‘q.")
        return

    buttons = []

    for user in users:
        name = user["first_name"] or "Foydalanuvchi"

        buttons.append([
            InlineKeyboardButton(
                text=f"👤 {name} | {user['user_id']}",
                callback_data=f"user:{user['user_id']}"
            )
        ])

    await message.answer(
        "👥 Foydalanuvchini tanlang:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
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

    referrals = db.execute("""
        SELECT user_id, first_name, username
        FROM users WHERE referrer_id=?
    """, (user_id,)).fetchall()

    orders = db.execute("""
        SELECT id, description, status
        FROM orders
        WHERE user_id=?
        ORDER BY id DESC LIMIT 10
    """, (user_id,)).fetchall()

    text = (
        "👤 <b>FOYDALANUVCHI MA’LUMOTI</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Ism: {user['first_name']}\n"
        f"🔗 Username: @{user['username'] or 'yo‘q'}\n"
        f"💰 Balans: {user['balance']} Stars\n"
        f"⭐ Jami to‘plagan Stars: {user['earned_stars']}\n"
        f"👥 Taklif qilganlari: {len(referrals)} ta\n"
        f"⛔ Bloklangan: {'Ha' if user['banned'] else 'Yo‘q'}\n\n"
        "📋 <b>Taklif qilgan foydalanuvchilari:</b>\n"
    )

    if referrals:
        for person in referrals[:20]:
            text += (
                f"\n• {person['first_name'] or 'Foydalanuvchi'}"
                f" — ID: {person['user_id']}"
            )
    else:
        text += "\nTakliflari yo‘q."

    text += "\n\n📦 <b>Oxirgi buyurtmalari:</b>\n"

    if orders:
        for order in orders:
            text += (
                f"\n#{order['id']} — {order['status']}\n"
                f"{order['description'][:100]}\n"
            )
    else:
        text += "\nBuyurtmalari yo‘q."

    await callback.message.answer(text)
    await callback.answer()


# ==================================================
# ADMIN: KANALLARNI BOSHQARISH
# ==================================================

@dp.message(F.text == "📡 Kanallar boshqaruvi")
async def channels_menu(message: Message):
    if not is_admin(message.from_user.id):
        return

    channels = get_channels()

    text = "📡 <b>KANALLAR BOSHQARUVI</b>\n\n"

    if channels:
        for i, channel in enumerate(channels, 1):
            text += (
                f"{i}. {channel['title']}\n"
                f"🆔 {channel['channel_id']}\n\n"
            )
    else:
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
                callback_data="channel_remove_menu"
            )
        ]
    ])

    await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data == "channel_add")
async def channel_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    await state.set_state(AddChannelState.waiting)

    await callback.message.answer(
        "➕ Kanal ma’lumotini yuboring.\n\n"
        "Ommaviy kanal uchun:\n"
        "<code>@kanal_username</code>\n\n"
        "Yopiq kanal uchun:\n"
        "<code>-1001234567890 https://t.me/+taklif_havolasi</code>\n\n"
        "Bot o‘sha kanalga administrator qilingan bo‘lishi kerak."
    )

    await callback.answer()


@dp.message(AddChannelState.waiting)
async def channel_add_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    if not message.text:
        await message.answer("Kanal ma’lumotini matn ko‘rinishida yuboring.")
        return

    parts = message.text.strip().split(maxsplit=1)
    channel_ref = parts[0]
    custom_url = parts[1].strip() if len(parts) > 1 else ""

    try:
        chat = await bot.get_chat(channel_ref)

        bot_member = await bot.get_chat_member(
            chat.id,
            bot.id
        )

        if bot_member.status not in ("administrator", "creator"):
            await message.answer(
                "❌ Bot bu kanalga administrator qilinmagan."
            )
            return

        if chat.type != "channel":
            await message.answer(
                "❌ Bu kanal emas. Telegram kanalini kiriting."
            )
            return

        can_post = getattr(
            bot_member,
            "can_post_messages",
            True
        )

        if not can_post:
            await message.answer(
                "❌ Botga kanalga xabar joylash huquqini bering."
            )
            return

        channel_id = str(chat.id)
        title = chat.title or "Kanal"
        username = chat.username or ""

        if custom_url:
            invite_url = custom_url
        elif username:
            invite_url = f"https://t.me/{username}"
        else:
            invite_url = ""

        db.execute("""
            INSERT INTO channels(
                channel_id, title, username, invite_url
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                title=excluded.title,
                username=excluded.username,
                invite_url=excluded.invite_url
        """, (
            channel_id,
            title,
            username,
            invite_url
        ))

        db.commit()
        await state.clear()

        await message.answer(
            f"✅ Kanal muvaffaqiyatli qo‘shildi!\n\n"
            f"📢 {title}\n"
            f"🆔 {channel_id}\n\n"
            "Endi bu kanal majburiy obuna va reklama tarqatish "
            "ro‘yxatiga qo‘shildi."
        )

    except Exception as e:
        logging.exception("Kanal qo‘shish xatosi")

        await message.answer(
            "❌ Kanalni qo‘shib bo‘lmadi.\n\n"
            "Kanal username yoki ID sini tekshiring. "
            "Bot kanalga administrator qilingan bo‘lishi kerak."
        )


@dp.callback_query(F.data == "channel_remove_menu")
async def channel_remove_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    channels = get_channels()

    if not channels:
        await callback.message.answer("O‘chirish uchun kanal yo‘q.")
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
        "Qaysi kanalni o‘chirmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("channel_del:"))
async def channel_remove(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    channel_id = callback.data.split(":", 1)[1]

    db.execute(
        "DELETE FROM channels WHERE channel_id=?",
        (channel_id,)
    )
    db.commit()

    await callback.message.answer(
        "✅ Kanal ro‘yxatdan o‘chirildi."
    )
    await callback.answer()


# ==================================================
# ADMIN: BARCHA KANALLARGA REKLAMA
# ==================================================

@dp.message(F.text == "📢 Kanalga reklama")
async def ad_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channels = get_channels()

    if not channels:
        await message.answer(
            "❌ Avval 📡 Kanallar boshqaruvi bo‘limidan kanal qo‘shing."
        )
        return

    await state.set_state(AdState.waiting)

    await message.answer(
        f"📢 Reklama yuboring.\n\n"
        f"Xabar {len(channels)} ta qo‘shilgan kanalning barchasiga "
        "yuboriladi.\n\n"
        "Matn, rasm, video yoki boshqa Telegram xabarini yuborishingiz mumkin."
    )


@dp.message(AdState.waiting)
async def ad_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    channels = get_channels()

    if not channels:
        await state.clear()
        await message.answer("Kanal ro‘yxati bo‘sh.")
        return

    sent = 0
    failed = []

    status_message = await message.answer(
        f"⏳ Reklama {len(channels)} ta kanalga yuborilmoqda..."
    )

    for channel in channels:
        try:
            await bot.copy_message(
                chat_id=channel["channel_id"],
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            sent += 1

        except Exception as e:
            logging.error(
                "Reklama %s kanalga yuborilmadi: %s",
                channel["channel_id"],
                e
            )
            failed.append(channel["title"])

        await asyncio.sleep(0.1)

    await state.clear()

    result = (
        "📢 <b>REKLAMA NATIJASI</b>\n\n"
        f"✅ Yuborildi: {sent} ta kanal\n"
        f"❌ Yuborilmadi: {len(failed)} ta kanal"
    )

    if failed:
        result += "\n\n❌ <b>Xato bo‘lgan kanallar:</b>\n"
        result += "\n".join(f"• {name}" for name in failed[:20])

    await status_message.edit_text(result)


# ==================================================
# ADMIN: BUYURTMALAR
# ==================================================

@dp.message(F.text == "📦 Buyurtmalar")
async def admin_orders(message: Message):
    if not is_admin(message.from_user.id):
        return

    orders = db.execute("""
        SELECT * FROM orders
        ORDER BY id DESC LIMIT 20
    """).fetchall()

    if not orders:
        await message.answer("Hozircha buyurtmalar yo‘q.")
        return

    for order in orders:
        await message.answer(
            f"📦 Buyurtma #{order['id']}\n"
            f"👤 User ID: {order['user_id']}\n"
            f"📝 {order['description']}\n"
            f"📌 Holati: {order['status']}"
        )


# ==================================================
# ADMIN: BALANS
# ==================================================

@dp.message(F.text == "💰 Balans boshqarish")
async def balance_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(BalanceState.waiting)

    await message.answer(
        "Quyidagi ko‘rinishda yuboring:\n\n"
        "<code>USER_ID MIQDOR</code>\n\n"
        "Masalan:\n"
        "<code>123456789 50</code> — 50 Stars qo‘shish.\n"
        "<code>123456789 -20</code> — 20 Stars ayirish."
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
            await message.answer("❌ Foydalanuvchi topilmadi.")
            return

        if user["balance"] + amount < 0:
            await message.answer("❌ Balans manfiy bo‘lishi mumkin emas.")
            return

        if amount >= 0:
            add_stars(user_id, amount)
        else:
            db.execute("""
                UPDATE users SET balance=balance+?
                WHERE user_id=?
            """, (amount, user_id))
            db.commit()

        await state.clear()

        await message.answer("✅ Balans o‘zgartirildi.")

        try:
            await bot.send_message(
                user_id,
                f"💰 Hisobingiz o‘zgartirildi: {amount:+} Stars"
            )
        except Exception:
            pass

    except Exception:
        await message.answer(
            "❌ Format xato. Masalan: <code>123456789 50</code>"
        )


# ==================================================
# ADMIN: REFERAL BONUSINI SOZLASH
# ==================================================

@dp.message(F.text == "⚙️ Referal sozlamasi")
async def referral_settings(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    current = get_setting(
        "referral_bonus",
        DEFAULT_REFERRAL_BONUS
    )

    await state.set_state(ReferralState.waiting)

    await message.answer(
        f"⚙️ Hozirgi referal bonusi: {current} Stars.\n\n"
        "Yangi bonus miqdorini raqam bilan yuboring."
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

        await message.answer(
            f"✅ Referal bonusi {amount} Stars qilib o‘zgartirildi."
        )

    except Exception:
        await message.answer("Faqat raqam yuboring.")


# ==================================================
# BOSHQA XABARLAR
# ==================================================

@dp.message()
async def other_messages(message: Message):
    user = get_user(message.from_user.id)

    if user and user["banned"]:
        await message.answer(
            "⛔ Siz botdan foydalanish huquqidan mahrum qilingansiz."
        )
        return

    if is_admin(message.from_user.id):
        await message.answer(
            "Admin paneldan kerakli bo‘limni tanlang.",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "Menyudagi tugmalardan foydalaning.",
            reply_markup=user_menu()
        )


# ==================================================
# RENDER WEB SERVER
# ==================================================

async def health(request):
    return web.Response(text="Bot is running!")


async def main():
    if BOT_TOKEN == "TOKEN_BU_YERGA":
        raise RuntimeError("BOT_TOKEN ni kiriting!")

    app = web.Application()
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    logging.info("Web server ishga tushdi.")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
