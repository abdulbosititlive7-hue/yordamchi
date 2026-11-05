import asyncio
import logging
import os
import aiosqlite

from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)

from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


# =========================================
# SOZLAMALAR
# =========================================

BOT_TOKEN = "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo"

ADMIN_ID_1 = 5200398952
ADMIN_ID_2 = 7676544759

DB_NAME = "stars.db"

GIFT_PRICES = [15, 25]

logging.basicConfig(level=logging.INFO)

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())


def is_admin(uid):
    return uid == ADMIN_ID_1 or uid == ADMIN_ID_2


# =========================================
# HOLATLAR
# =========================================

class Form(StatesGroup):
    add_channel = State()
    remove_channel = State()
    referral_reward = State()
    promo_create = State()
    promo_use = State()
    broadcast = State()
    search_user = State()
    add_stars = State()
    remove_stars = State()
    topup = State()


# =========================================
# MENYULAR
# =========================================

def user_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="⭐ Stars olish"),
                KeyboardButton(text="🎁 Gift yechish")
            ],
            [
                KeyboardButton(text="👤 Mening hisobim"),
                KeyboardButton(text="📦 Buyurtmalar")
            ],
            [
                KeyboardButton(text="👥 Referal"),
                KeyboardButton(text="🏆 TOP referal")
            ],
            [
                KeyboardButton(text="🎟 Promokod"),
                KeyboardButton(text="💰 Hisob to'ldirish")
            ],
            [
                KeyboardButton(text="🎰 777 Slot"),
                KeyboardButton(text="📊 Statistika")
            ],
            [
                KeyboardButton(text="☎️ Yordam"),
                KeyboardButton(text="📚 Qo'llanma")
            ]
        ],
        resize_keyboard=True,
        persistent=True
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👥 Foydalanuvchilar"),
                KeyboardButton(text="📊 Statistika")
            ],
            [
                KeyboardButton(text="🔎 Foydalanuvchi qidirish"),
                KeyboardButton(text="🔗 Referallar")
            ],
            [
                KeyboardButton(text="⭐ Stars qo'shish"),
                KeyboardButton(text="📉 Stars ayirish")
            ],
            [
                KeyboardButton(text="🚫 Ban / Unban"),
                KeyboardButton(text="📢 Reklama")
            ],
            [
                KeyboardButton(text="➕ Kanal qo'shish"),
                KeyboardButton(text="➖ Kanal o'chirish")
            ],
            [
                KeyboardButton(text="📡 Kanallar"),
                KeyboardButton(text="🎁 Gift buyurtmalari")
            ],
            [
                KeyboardButton(text="🎟 Promo yaratish"),
                KeyboardButton(text="📋 Promokodlar")
            ],
            [
                KeyboardButton(text="⚙️ Referal sozlamasi"),
                KeyboardButton(text="💾 Baza")
            ],
            [
                KeyboardButton(text="💳 Hisob so'rovlari"),
                KeyboardButton(text="🏠 Asosiy menyu")
            ]
        ],
        resize_keyboard=True,
        persistent=True
    )


# =========================================
# DATABASE
# =========================================

async def db_init():
    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            stars INTEGER DEFAULT 0,
            referrer INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            created TEXT
        )
        """)

        # Eski bazaga first_name ustunini qo'shish
        async with db.execute("PRAGMA table_info(users)") as cur:
            columns = [r[1] for r in await cur.fetchall()]

        if "first_name" not in columns:
            await db.execute(
                "ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT ''"
            )

        await db.execute("""
        CREATE TABLE IF NOT EXISTS channels(
            channel TEXT PRIMARY KEY
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS referrals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer INTEGER,
            invited INTEGER UNIQUE,
            reward INTEGER,
            active INTEGER DEFAULT 1
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS gifts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            stars INTEGER,
            status TEXT DEFAULT 'pending',
            created TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS promos(
            code TEXT PRIMARY KEY,
            stars INTEGER,
            limit_count INTEGER,
            used INTEGER DEFAULT 0
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS promo_users(
            user_id INTEGER,
            code TEXT,
            UNIQUE(user_id,code)
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS topups(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            stars INTEGER,
            status TEXT DEFAULT 'pending'
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            name TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        await db.execute("""
        INSERT OR IGNORE INTO settings(name,value)
        VALUES('referral_reward','5')
        """)

        await db.commit()


# =========================================
# YORDAMCHI FUNKSIYALAR
# =========================================

async def get_setting(name):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT value FROM settings WHERE name=?",
            (name,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else "0"


async def set_setting(name, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT OR REPLACE INTO settings(name,value)
        VALUES(?,?)
        """, (name, str(value)))
        await db.commit()


async def get_balance(uid):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT stars FROM users WHERE user_id=?",
            (uid,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def change_stars(uid, amount, reason):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("BEGIN IMMEDIATE")

        async with db.execute(
            "SELECT stars FROM users WHERE user_id=?",
            (uid,)
        ) as cur:
            row = await cur.fetchone()

        if not row or row[0] + amount < 0:
            await db.rollback()
            return False

        await db.execute(
            "UPDATE users SET stars=stars+? WHERE user_id=?",
            (amount, uid)
        )

        await db.execute("""
        INSERT INTO transactions(user_id,amount,reason,created)
        VALUES(?,?,?,?)
        """, (
            uid, amount, reason, datetime.now().isoformat()
        ))

        await db.commit()
        return True


async def register(message, referrer=0):
    uid = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (uid,)
        ) as cur:
            exists = await cur.fetchone()

        if exists:
            await db.execute("""
            UPDATE users SET username=?,first_name=?
            WHERE user_id=?
            """, (
                message.from_user.username or "",
                message.from_user.first_name or "",
                uid
            ))
        else:
            if referrer == uid:
                referrer = 0

            async with db.execute(
                "SELECT user_id FROM users WHERE user_id=?",
                (referrer,)
            ) as cur:
                valid = await cur.fetchone()

            if not valid:
                referrer = 0

            await db.execute("""
            INSERT INTO users(
                user_id,username,stars,referrer,
                banned,created,first_name
            )
            VALUES(?,?,0,?,0,?,?)
            """, (
                uid,
                message.from_user.username or "",
                referrer,
                datetime.now().isoformat(),
                message.from_user.first_name or ""
            ))

        await db.commit()


async def get_channels():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT channel FROM channels"
        ) as cur:
            return await cur.fetchall()


# =========================================
# KANAL OBUNASI
# =========================================

async def check_subscription(uid):
    for (channel,) in await get_channels():
        try:
            member = await bot.get_chat_member(channel, uid)

            if member.status in ("left", "kicked"):
                return False

        except Exception:
            logging.exception("Obuna tekshirish xatosi")
            return False

    return True


async def subscription_buttons():
    rows = []

    for (channel,) in await get_channels():
        try:
            chat = await bot.get_chat(channel)

            link = (
                "https://t.me/" + channel[1:]
                if channel.startswith("@")
                else channel
            )

            rows.append([
                InlineKeyboardButton(
                    text="📢 " + chat.title,
                    url=link
                )
            ])
        except Exception:
            pass

    rows.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def check_user(message):
    uid = message.from_user.id

    if is_admin(uid):
        return True

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT banned FROM users WHERE user_id=?",
            (uid,)
        ) as cur:
            row = await cur.fetchone()

    if row and row[0]:
        await message.answer("🚫 Siz bloklangansiz.")
        return False

    if not await check_subscription(uid):
        await message.answer(
            "📢 Botdan foydalanish uchun kanallarga obuna bo'ling.",
            reply_markup=await subscription_buttons()
        )
        return False

    return True


# =========================================
# REFERAL MUKOFOTI
# =========================================

async def give_referral_reward(uid):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("BEGIN IMMEDIATE")

        async with db.execute("""
        SELECT referrer FROM users
        WHERE user_id=? AND referrer>0
        """, (uid,)) as cur:
            row = await cur.fetchone()

        if not row:
            await db.rollback()
            return

        ref = row[0]

        async with db.execute(
            "SELECT id FROM referrals WHERE invited=?",
            (uid,)
        ) as cur:
            exists = await cur.fetchone()

        if exists:
            await db.rollback()
            return

        reward = int(await get_setting("referral_reward"))

        await db.execute("""
        INSERT INTO referrals(referrer,invited,reward,active)
        VALUES(?,?,?,1)
        """, (ref, uid, reward))

        await db.execute(
            "UPDATE users SET stars=stars+? WHERE user_id=?",
            (reward, ref)
        )

        await db.execute("""
        INSERT INTO transactions(user_id,amount,reason,created)
        VALUES(?,?,?,?)
        """, (
            ref, reward, "Referal mukofoti",
            datetime.now().isoformat()
        ))

        await db.commit()

    try:
        await bot.send_message(
            ref,
            f"🎉 Yangi referal!\n⭐ +{reward} Stars"
        )
    except Exception:
        pass


async def referral_monitor():
    while True:
        try:
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("""
                SELECT invited,referrer,reward
                FROM referrals WHERE active=1
                """) as cur:
                    rows = await cur.fetchall()

            for uid, ref, reward in rows:
                if not await check_subscription(uid):
                    async with aiosqlite.connect(DB_NAME) as db:
                        await db.execute("BEGIN IMMEDIATE")

                        async with db.execute(
                            "SELECT stars FROM users WHERE user_id=?",
                            (ref,)
                        ) as cur:
                            row = await cur.fetchone()

                        if row:
                            # Balansni manfiy qilmaslik
                            deduction = min(row[0], reward)

                            await db.execute(
                                "UPDATE users SET stars=stars-? WHERE user_id=?",
                                (deduction, ref)
                            )

                            await db.execute("""
                            INSERT INTO transactions(
                                user_id,amount,reason,created
                            ) VALUES(?,?,?,?)
                            """, (
                                ref, -deduction,
                                "Referal obunadan chiqdi",
                                datetime.now().isoformat()
                            ))

                        await db.execute(
                            "UPDATE referrals SET active=0 WHERE invited=?",
                            (uid,)
                        )

                        await db.commit()

                        try:
                            await bot.send_message(
                                ref,
                                f"⚠️ Referalingiz obunadan chiqdi.\n"
                                f"⭐ {deduction if row else 0} Stars bekor qilindi."
                            )
                        except Exception:
                            pass

                await asyncio.sleep(0.5)

        except Exception:
            logging.exception("Referal monitoring xatosi")

        await asyncio.sleep(600)


# =========================================
# START
# =========================================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    ref = 0
    args = message.text.split(maxsplit=1)

    if len(args) > 1:
        try:
            ref = int(args[1])
        except ValueError:
            pass

    await register(message, ref)

    if is_admin(message.from_user.id):
        await message.answer(
            "👑 Admin panelga xush kelibsiz!",
            reply_markup=admin_menu()
        )
        return

    if not await check_subscription(message.from_user.id):
        await message.answer(
            "📢 Avval kanallarga obuna bo'ling.",
            reply_markup=await subscription_buttons()
        )
        return

    await give_referral_reward(message.from_user.id)

    await message.answer(
        "👋 STARS BOT ga xush kelibsiz!",
        reply_markup=user_menu()
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        if not is_admin(call.from_user.id):
            await give_referral_reward(call.from_user.id)

        await call.message.answer(
            "✅ Obuna tasdiqlandi!",
            reply_markup=(
                admin_menu()
                if is_admin(call.from_user.id)
                else user_menu()
            )
        )
        await call.answer()
    else:
        await call.answer(
            "❌ Barcha kanallarga obuna bo'ling!",
            show_alert=True
        )


# =========================================
# FOYDALANUVCHI: STARS
# =========================================

@dp.message(F.text == "⭐ Stars olish")
async def stars_get(message: Message):
    if not await check_user(message):
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"

    await message.answer(
        "⭐ <b>STARS OLISH</b>\n\n"
        "Do'stlaringizni taklif qiling.\n\n"
        f"🔗 <code>{link}</code>\n\n"
        f"Har bir referal: {await get_setting('referral_reward')} Stars"
    )


@dp.message(F.text == "👤 Mening hisobim")
async def account(message: Message):
    if not await check_user(message):
        return

    uid = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer=? AND active=1",
            (uid,)
        ) as cur:
            refs = (await cur.fetchone())[0]

    await message.answer(
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Ism: {message.from_user.first_name}\n"
        f"Username: @{message.from_user.username or 'Mavjud emas'}\n"
        f"⭐ Stars: <b>{await get_balance(uid)}</b>\n"
        f"👥 Faol referallar: {refs}"
    )


@dp.message(F.text == "👥 Referal")
async def referral(message: Message):
    if not await check_user(message):
        return

    uid = message.from_user.id
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={uid}"

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT COUNT(*),COALESCE(SUM(reward),0)
        FROM referrals WHERE referrer=? AND active=1
        """, (uid,)) as cur:
            count, earned = await cur.fetchone()

    await message.answer(
        "🔗 <b>REFERAL BO'LIMI</b>\n\n"
        f"Havola:\n<code>{link}</code>\n\n"
        f"👥 Referallar: {count}\n"
        f"⭐ Mukofotlar: {earned} Stars"
    )


@dp.message(F.text == "🏆 TOP referal")
async def top_referral(message: Message):
    if not await check_user(message):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT u.user_id,u.first_name,u.username,COUNT(r.id)
        FROM users u
        LEFT JOIN referrals r
        ON u.user_id=r.referrer AND r.active=1
        GROUP BY u.user_id
        ORDER BY COUNT(r.id) DESC
        LIMIT 10
        """) as cur:
            rows = await cur.fetchall()

    text = "🏆 <b>TOP REFERAL</b>\n\n"

    for i, (uid, name, username, count) in enumerate(rows, 1):
        label = name or username or str(uid)
        text += f"{i}. {label} — {count} ta\n"

    await message.answer(text)


# =========================================
# GIFT TIZIMI
# FAQAT 15 VA 25 STARS
# =========================================

@dp.message(F.text == "🎁 Gift yechish")
async def gift_menu(message: Message):
    if not await check_user(message):
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 15 Stars Gift",
                    callback_data="gift_order:15"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎁 25 Stars Gift",
                    callback_data="gift_order:25"
                )
            ]
        ]
    )

    await message.answer(
        "🎁 <b>GIFT BUYURTMA</b>\n\n"
        f"⭐ Balansingiz: {await get_balance(message.from_user.id)} Stars\n\n"
        "Kerakli giftni tanlang:",
        reply_markup=kb
    )


@dp.callback_query(F.data.startswith("gift_order:"))
async def gift_order(call: CallbackQuery):
    uid = call.from_user.id

    if is_admin(uid):
        pass
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT banned FROM users WHERE user_id=?",
                (uid,)
            ) as cur:
                row = await cur.fetchone()

        if row and row[0]:
            await call.answer("Siz bloklangansiz.", show_alert=True)
            return

        if not await check_subscription(uid):
            await call.message.answer(
                "📢 Avval kanallarga obuna bo'ling.",
                reply_markup=await subscription_buttons()
            )
            await call.answer()
            return

    try:
        amount = int(call.data.split(":")[1])
    except ValueError:
        await call.answer("Xato buyurtma.", show_alert=True)
        return

    if amount not in GIFT_PRICES:
        await call.answer("Bunday gift mavjud emas.", show_alert=True)
        return

    # Balansni tekshirish va Starsni bir tranzaksiyada ayirish
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("BEGIN IMMEDIATE")

        async with db.execute(
            "SELECT stars FROM users WHERE user_id=?",
            (uid,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            await db.rollback()
            await call.answer("Hisob topilmadi.", show_alert=True)
            return

        if row[0] < amount:
            await db.rollback()
            await call.answer(
                f"❌ Stars yetarli emas! Sizda {row[0]} Stars bor.",
                show_alert=True
            )
            return

        # Buyurtma berilishi bilan balansdan ayiriladi
        await db.execute(
            "UPDATE users SET stars=stars-? WHERE user_id=?",
            (amount, uid)
        )

        cur = await db.execute("""
        INSERT INTO gifts(user_id,stars,status,created)
        VALUES(?,?,'pending',?)
        """, (
            uid, amount, datetime.now().isoformat()
        ))

        gid = cur.lastrowid

        await db.execute("""
        INSERT INTO transactions(user_id,amount,reason,created)
        VALUES(?,?,?,?)
        """, (
            uid, -amount, f"{amount} Stars Gift buyurtmasi",
            datetime.now().isoformat()
        ))

        await db.commit()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash",
                    callback_data=f"gift_yes:{gid}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=f"gift_no:{gid}"
                )
            ]
        ]
    )

    admin_text = (
        "🎁 <b>YANGI GIFT BUYURTMASI</b>\n\n"
        f"📦 Buyurtma: #{gid}\n"
        f"👤 Ism: {call.from_user.first_name}\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"⭐ Gift: {amount} Stars\n"
        f"💰 Qolgan balans: {await get_balance(uid)} Stars"
    )

    for admin in (ADMIN_ID_1, ADMIN_ID_2):
        try:
            await bot.send_message(
                admin,
                admin_text,
                reply_markup=kb
            )
        except Exception:
            logging.exception("Adminga gift xabari yuborilmadi")

    await call.message.answer(
        "✅ <b>BUYURTMA QABUL QILINDI!</b>\n\n"
        f"🎁 Gift: {amount} Stars\n"
        f"⭐ Hisobingizdan: -{amount} Stars\n"
        f"💰 Qolgan balans: {await get_balance(uid)} Stars\n\n"
        "Admin tasdiqlashini kuting."
    )

    await call.answer("Buyurtma yaratildi!")


# =========================================
# ADMIN: GIFT TASDIQLASH
# =========================================

@dp.callback_query(F.data.startswith("gift_yes:"))
async def gift_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    gid = int(call.data.split(":")[1])

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("BEGIN IMMEDIATE")

        async with db.execute(
            "SELECT user_id,stars,status FROM gifts WHERE id=?",
            (gid,)
        ) as cur:
            row = await cur.fetchone()

        if not row or row[2] != "pending":
            await db.rollback()
            await call.answer("Bu buyurtma allaqachon ko'rib chiqilgan.")
            return

        uid, amount, _ = row

        await db.execute(
            "UPDATE gifts SET status='approved' WHERE id=?",
            (gid,)
        )

        await db.commit()

    await call.message.edit_text(
        f"✅ #{gid} buyurtma tasdiqlandi.\n"
        f"User: {uid}\nGift: {amount} Stars"
    )

    try:
        await bot.send_message(
            uid,
            "🎉 <b>GIFT BUYURTMANGIZ TASDIQLANDI!</b>\n\n"
            f"🎁 Gift: {amount} Stars\n"
            "Admin buyurtmangizni tasdiqladi."
        )
    except Exception:
        pass

    await call.answer("Tasdiqlandi!")


@dp.callback_query(F.data.startswith("gift_no:"))
async def gift_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    gid = int(call.data.split(":")[1])

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("BEGIN IMMEDIATE")

        async with db.execute(
            "SELECT user_id,stars,status FROM gifts WHERE id=?",
            (gid,)
        ) as cur:
            row = await cur.fetchone()

        if not row or row[2] != "pending":
            await db.rollback()
            await call.answer("Bu buyurtma allaqachon ko'rib chiqilgan.")
            return

        uid, amount, _ = row

        # Rad etilganda pulni qaytarish
        await db.execute(
            "UPDATE users SET stars=stars+? WHERE user_id=?",
            (amount, uid)
        )

        await db.execute(
            "UPDATE gifts SET status='rejected' WHERE id=?",
            (gid,)
        )

        await db.execute("""
        INSERT INTO transactions(user_id,amount,reason,created)
        VALUES(?,?,?,?)
        """, (
            uid, amount, "Rad etilgan gift uchun qaytarildi",
            datetime.now().isoformat()
        ))

        await db.commit()

    await call.message.edit_text(
        f"❌ #{gid} buyurtma rad etildi.\n"
        f"⭐ {amount} Stars qaytarildi."
    )

    try:
        await bot.send_message(
            uid,
            "❌ Gift buyurtmangiz rad etildi.\n\n"
            f"⭐ {amount} Stars hisobingizga qaytarildi."
        )
    except Exception:
        pass

    await call.answer("Rad etildi. Stars qaytarildi!")


# =========================================
# BUYURTMALAR TARIXI
# =========================================

@dp.message(F.text == "📦 Buyurtmalar")
async def my_orders(message: Message):
    if not await check_user(message):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT id,stars,status,created
        FROM gifts WHERE user_id=?
        ORDER BY id DESC LIMIT 30
        """, (message.from_user.id,)) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("📦 Sizda buyurtmalar mavjud emas.")
        return

    text = "📦 <b>BUYURTMALARIM</b>\n\n"

    statuses = {
        "pending": "⏳ Kutilmoqda",
        "approved": "✅ Tasdiqlangan",
        "rejected": "❌ Rad etilgan"
    }

    for gid, amount, status, created in rows:
        text += (
            f"🆔 Buyurtma: #{gid}\n"
            f"🎁 Gift: {amount} Stars\n"
            f"Holati: {statuses.get(status, status)}\n"
            f"📅 {created[:16]}\n\n"
        )

    await message.answer(text)


# =========================================
# ADMIN: GIFT BUYURTMALARI
# =========================================

@dp.message(F.text == "🎁 Gift buyurtmalari")
async def admin_gifts(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT id,user_id,stars,created
        FROM gifts WHERE status='pending'
        ORDER BY id DESC
        """) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("🎁 Kutilayotgan buyurtmalar yo'q.")
        return

    for gid, uid, amount, created in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"gift_yes:{gid}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"gift_no:{gid}"
            )
        ]])

        await message.answer(
            f"🎁 Buyurtma #{gid}\n"
            f"👤 User: {uid}\n"
            f"⭐ Miqdor: {amount}\n"
            f"📅 {created[:16]}",
            reply_markup=kb
        )


# =========================================
# FOYDALANUVCHI: PROMOKOD
# =========================================

@dp.message(F.text == "🎟 Promokod")
async def promo_start(message: Message, state: FSMContext):
    if not await check_user(message):
        return

    await message.answer("🎟 Promokodni yuboring:")
    await state.set_state(Form.promo_use)


@dp.message(Form.promo_use)
async def promo_use(message: Message, state: FSMContext):
    if not await check_user(message):
        return

    code = message.text.strip().upper()
    uid = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("BEGIN IMMEDIATE")

        async with db.execute(
            "SELECT stars,limit_count,used FROM promos WHERE code=?",
            (code,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            await db.rollback()
            await state.clear()
            await message.answer("❌ Promokod topilmadi.")
            return

        async with db.execute(
            "SELECT 1 FROM promo_users WHERE user_id=? AND code=?",
            (uid, code)
        ) as cur:
            used = await cur.fetchone()

        if used:
            await db.rollback()
            await state.clear()
            await message.answer("❌ Bu promokoddan oldin foydalangansiz.")
            return

        stars, limit, count = row

        if limit > 0 and count >= limit:
            await db.rollback()
            await state.clear()
            await message.answer("❌ Promokod tugagan.")
            return

        await db.execute(
            "INSERT INTO promo_users(user_id,code) VALUES(?,?)",
            (uid, code)
        )

        await db.execute(
            "UPDATE promos SET used=used+1 WHERE code=?",
            (code,)
        )

        await db.execute(
            "UPDATE users SET stars=stars+? WHERE user_id=?",
            (stars, uid)
        )

        await db.execute("""
        INSERT INTO transactions(user_id,amount,reason,created)
        VALUES(?,?,?,?)
        """, (
            uid, stars, "Promokod " + code,
            datetime.now().isoformat()
        ))

        await db.commit()

    await state.clear()
    await message.answer(f"🎉 Promokod qabul qilindi!\n⭐ +{stars} Stars")


# =========================================
# FOYDALANUVCHI: SLOT
# =========================================

@dp.message(F.text == "🎰 777 Slot")
async def slot(message: Message):
    if not await check_user(message):
        return

    dice = await message.answer_dice(emoji="🎰")

    if dice.dice.value == 64:
        await change_stars(
            message.from_user.id, 5, "Slot jackpot"
        )
        await message.answer("🎉 JACKPOT! +5 Stars")
    else:
        await message.answer("🎰 Omad kelmadi. Yana urinib ko'ring!")


# =========================================
# FOYDALANUVCHI: HISOB TO'LDIRISH
# =========================================

@dp.message(F.text == "💰 Hisob to'ldirish")
async def topup_start(message: Message, state: FSMContext):
    if not await check_user(message):
        return

    await message.answer("Qancha Stars kerak? Miqdorni yuboring:")
    await state.set_state(Form.topup)


@dp.message(Form.topup)
async def topup_finish(message: Message, state: FSMContext):
    if not await check_user(message):
        return

    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Musbat son yuboring.")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "INSERT INTO topups(user_id,stars) VALUES(?,?)",
            (message.from_user.id, amount)
        )
        rid = cur.lastrowid
        await db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Tasdiqlash",
            callback_data=f"topup_yes:{rid}"
        ),
        InlineKeyboardButton(
            text="❌ Rad etish",
            callback_data=f"topup_no:{rid}"
        )
    ]])

    for admin in (ADMIN_ID_1, ADMIN_ID_2):
        try:
            await bot.send_message(
                admin,
                f"💰 Hisob so'rovi #{rid}\n"
                f"User: {message.from_user.id}\n"
                f"Stars: {amount}",
                reply_markup=kb
            )
        except Exception:
            pass

    await state.clear()
    await message.answer("✅ So'rov adminga yuborildi.")


@dp.callback_query(F.data.startswith("topup_yes:"))
async def topup_yes(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    rid = int(call.data.split(":")[1])

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("BEGIN IMMEDIATE")

        async with db.execute(
            "SELECT user_id,stars,status FROM topups WHERE id=?",
            (rid,)
        ) as cur:
            row = await cur.fetchone()

        if not row or row[2] != "pending":
            await db.rollback()
            await call.answer("So'rov ko'rib chiqilgan.")
            return

        uid, amount, _ = row

        await db.execute(
            "UPDATE users SET stars=stars+? WHERE user_id=?",
            (amount, uid)
        )

        await db.execute(
            "UPDATE topups SET status='approved' WHERE id=?",
            (rid,)
        )

        await db.execute("""
        INSERT INTO transactions(user_id,amount,reason,created)
        VALUES(?,?,?,?)
        """, (
            uid, amount, "Hisob to'ldirish",
            datetime.now().isoformat()
        ))

        await db.commit()

    await call.message.edit_text("✅ Hisob to'ldirildi.")

    try:
        await bot.send_message(uid, f"⭐ +{amount} Stars hisobingizga qo'shildi.")
    except Exception:
        pass

    await call.answer("Tasdiqlandi!")


@dp.callback_query(F.data.startswith("topup_no:"))
async def topup_no(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    rid = int(call.data.split(":")[1])

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id,status FROM topups WHERE id=?",
            (rid,)
        ) as cur:
            row = await cur.fetchone()

        if not row or row[1] != "pending":
            await call.answer("So'rov ko'rib chiqilgan.")
            return

        await db.execute(
            "UPDATE topups SET status='rejected' WHERE id=?",
            (rid,)
        )
        await db.commit()

    await call.message.edit_text("❌ So'rov rad etildi.")

    try:
        await bot.send_message(row[0], "❌ Hisob to'ldirish so'rovingiz rad etildi.")
    except Exception:
        pass

    await call.answer("Rad etildi!")


# =========================================
# FOYDALANUVCHI: QOLGAN MENYULAR
# =========================================

@dp.message(F.text == "📊 Statistika")
async def user_statistics(message: Message):
    if not await check_user(message):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users"
        ) as cur:
            count = (await cur.fetchone())[0]

    await message.answer(
        f"📊 Bot foydalanuvchilari: {count}"
    )


@dp.message(F.text == "☎️ Yordam")
async def support(message: Message):
    if not await check_user(message):
        return

    await message.answer(
        "☎️ Yordam uchun adminlarga yozing.\n\n"
        f"Admin ID 1: <code>{ADMIN_ID_1}</code>\n"
        f"Admin ID 2: <code>{ADMIN_ID_2}</code>"
    )


@dp.message(F.text == "📚 Qo'llanma")
async def guide(message: Message):
    if not await check_user(message):
        return

    await message.answer(
        "📚 <b>QO'LLANMA</b>\n\n"
        "⭐ Stars olish — referal orqali Stars yig'ish.\n"
        "🎁 Gift yechish — 15 yoki 25 Stars gift buyurtma qilish.\n"
        "📦 Buyurtmalar — buyurtmalar tarixini ko'rish.\n"
        "👤 Mening hisobim — hisobingizni ko'rish.\n"
        "🎟 Promokod — promokod ishlatish.\n"
        "🏆 TOP referal — eng faol taklif qiluvchilar."
    )


# =========================================
# ADMIN: FOYDALANUVCHILAR RO'YXATI
# =========================================

USERS_PER_PAGE = 10


async def users_keyboard(page=0):
    offset = page * USERS_PER_PAGE

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT user_id,first_name,username
        FROM users
        ORDER BY user_id DESC
        LIMIT ? OFFSET ?
        """, (USERS_PER_PAGE, offset)) as cur:
            rows = await cur.fetchall()

        async with db.execute(
            "SELECT COUNT(*) FROM users"
        ) as cur:
            total = (await cur.fetchone())[0]

    buttons = []

    for uid, name, username in rows:
        label = name or username or f"User {uid}"

        if username:
            label = f"{label} (@{username})"

        buttons.append([
            InlineKeyboardButton(
                text=f"👤 {label[:45]}",
                callback_data=f"user_profile:{uid}"
            )
        ])

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"users_page:{page-1}"
            )
        )

    if offset + USERS_PER_PAGE < total:
        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"users_page:{page+1}"
            )
        )

    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons), total


@dp.message(F.text == "👥 Foydalanuvchilar")
async def admin_users(message: Message):
    if not is_admin(message.from_user.id):
        return

    kb, total = await users_keyboard(0)

    await message.answer(
        f"👥 <b>FOYDALANUVCHILAR</b>\n\n"
        f"Jami: {total} ta\n"
        "Profilni ko'rish uchun ismni bosing:",
        reply_markup=kb
    )


@dp.callback_query(F.data.startswith("users_page:"))
async def users_page(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    page = int(call.data.split(":")[1])
    kb, total = await users_keyboard(page)

    await call.message.edit_text(
        f"👥 <b>FOYDALANUVCHILAR</b>\n\n"
        f"Jami: {total} ta\n"
        "Profilni ko'rish uchun ismni bosing:",
        reply_markup=kb
    )

    await call.answer()


# =========================================
# ADMIN: ALOHIDA FOYDALANUVCHI PROFILI
# =========================================

async def show_user_profile(message_or_call, uid):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT user_id,first_name,username,stars,referrer,
               banned,created
        FROM users WHERE user_id=?
        """, (uid,)) as cur:
            user = await cur.fetchone()

        if not user:
            return False

        async with db.execute("""
        SELECT COUNT(*) FROM referrals
        WHERE referrer=? AND active=1
        """, (uid,)) as cur:
            active_refs = (await cur.fetchone())[0]

        async with db.execute("""
        SELECT COUNT(*) FROM referrals
        WHERE referrer=?
        """, (uid,)) as cur:
            total_refs = (await cur.fetchone())[0]

        async with db.execute("""
        SELECT COUNT(*) FROM gifts
        WHERE user_id=? AND status='pending'
        """, (uid,)) as cur:
            pending_gifts = (await cur.fetchone())[0]

        async with db.execute("""
        SELECT amount,reason,created
        FROM transactions WHERE user_id=?
        ORDER BY id DESC LIMIT 5
        """, (uid,)) as cur:
            transactions = await cur.fetchall()

    uid, name, username, stars, referrer, banned, created = user

    name = name or "Ism mavjud emas"
    username_text = f"@{username}" if username else "Username mavjud emas"

    text = (
        "👤 <b>FOYDALANUVCHI PROFILI</b>\n\n"
        f"👤 Ism: <a href='tg://user?id={uid}'>{name}</a>\n"
        f"🔗 Username: {username_text}\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"⭐ Stars: <b>{stars}</b>\n"
        f"👥 Faol referallar: {active_refs}\n"
        f"🔗 Jami referallar: {total_refs}\n"
        f"👤 Taklif qilgan ID: {referrer or 'Yo‘q'}\n"
        f"🎁 Kutilayotgan buyurtmalar: {pending_gifts}\n"
        f"🚫 Holati: {'Bloklangan' if banned else 'Faol'}\n"
        f"📅 Ro'yxatdan o'tgan: {created or 'Noma’lum'}\n\n"
        "<b>Oxirgi 5 ta tranzaksiya:</b>\n"
    )

    if transactions:
        for amount, reason, date in transactions:
            sign = "+" if amount > 0 else ""
            text += f"{sign}{amount} ⭐ — {reason} ({date[:10]})\n"
    else:
        text += "Tranzaksiyalar mavjud emas.\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Stars qo'shish",
                    callback_data=f"quick_add:{uid}"
                ),
                InlineKeyboardButton(
                    text="📉 Stars ayirish",
                    callback_data=f"quick_remove:{uid}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Ban" if not banned else "✅ Unban",
                    callback_data=f"quick_ban:{uid}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Foydalanuvchilar",
                    callback_data="users_page:0"
                )
            ]
        ]
    )

    if isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.edit_text(
            text,
            reply_markup=kb
        )
    else:
        await message_or_call.answer(
            text,
            reply_markup=kb
        )

    return True


@dp.callback_query(F.data.startswith("user_profile:"))
async def user_profile(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    uid = int(call.data.split(":")[1])

    result = await show_user_profile(call, uid)

    if not result:
        await call.answer("Foydalanuvchi topilmadi.")
        return

    await call.answer()


# =========================================
# ADMIN: PROFILDAN STARS QO'SHISH
# =========================================

@dp.callback_query(F.data.startswith("quick_add:"))
async def quick_add(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    uid = int(call.data.split(":")[1])

    await state.update_data(target_uid=uid)
    await state.set_state(Form.add_stars)

    await call.message.answer(
        f"{uid} foydalanuvchiga qancha Stars qo'shilsin?"
    )

    await call.answer()


@dp.callback_query(F.data.startswith("quick_remove:"))
async def quick_remove(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    uid = int(call.data.split(":")[1])

    await state.update_data(target_uid=uid)
    await state.set_state(Form.remove_stars)

    await call.message.answer(
        f"{uid} foydalanuvchidan qancha Stars ayrilsin?"
    )

    await call.answer()


@dp.callback_query(F.data.startswith("quick_ban:"))
async def quick_ban(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    uid = int(call.data.split(":")[1])

    if is_admin(uid):
        await call.answer("Adminni bloklab bo'lmaydi.", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT banned FROM users WHERE user_id=?",
            (uid,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            await call.answer("Foydalanuvchi topilmadi.")
            return

        new_status = 0 if row[0] else 1

        await db.execute(
            "UPDATE users SET banned=? WHERE user_id=?",
            (new_status, uid)
        )
        await db.commit()

    await show_user_profile(call, uid)
    await call.answer("Holat o'zgartirildi.")


# =========================================
# ADMIN: QIDIRISH
# =========================================

@dp.message(F.text == "🔎 Foydalanuvchi qidirish")
async def search_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "Foydalanuvchi ID yoki username yuboring:"
    )
    await state.set_state(Form.search_user)


@dp.message(Form.search_user)
async def search_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    query = message.text.strip().replace("@", "")

    async with aiosqlite.connect(DB_NAME) as db:
        if query.isdigit():
            async with db.execute(
                "SELECT user_id FROM users WHERE user_id=?",
                (int(query),)
            ) as cur:
                row = await cur.fetchone()
        else:
            async with db.execute(
                "SELECT user_id FROM users WHERE username=?",
                (query,)
            ) as cur:
                row = await cur.fetchone()

    await state.clear()

    if not row:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return

    await show_user_profile(message, row[0])


# =========================================
# ADMIN: STARS QO'SHISH
# =========================================

@dp.message(F.text == "⭐ Stars qo'shish")
async def add_stars_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("ID va Stars miqdorini yuboring:\n123456789 50")
    await state.set_state(Form.add_stars)


@dp.message(Form.add_stars)
async def add_stars_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()

    try:
        if "target_uid" in data:
            uid = int(data["target_uid"])
            amount = int(message.text)
        else:
            uid, amount = map(int, message.text.split())

        if amount <= 0:
            raise ValueError

    except ValueError:
        await message.answer("Noto'g'ri format. ID MIQDOR yoki faqat miqdor.")
        return

    result = await change_stars(uid, amount, "Admin Stars qo'shdi")

    await state.clear()

    if not result:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return

    await message.answer(f"✅ {amount} Stars qo'shildi.")

    try:
        await bot.send_message(uid, f"⭐ Sizga +{amount} Stars qo'shildi.")
    except Exception:
        pass


# =========================================
# ADMIN: STARS AYIRISH
# =========================================

@dp.message(F.text == "📉 Stars ayirish")
async def remove_stars_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("ID va miqdorni yuboring:\n123456789 10")
    await state.set_state(Form.remove_stars)


@dp.message(Form.remove_stars)
async def remove_stars_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()

    try:
        if "target_uid" in data:
            uid = int(data["target_uid"])
            amount = int(message.text)
        else:
            uid, amount = map(int, message.text.split())

        if amount <= 0:
            raise ValueError

    except ValueError:
        await message.answer("Noto'g'ri format. ID MIQDOR yoki faqat miqdor.")
        return

    result = await change_stars(uid, -amount, "Admin Stars ayirdi")

    await state.clear()

    if result:
        await message.answer("✅ Stars ayirildi.")
        try:
            await bot.send_message(uid, f"⭐ Sizdan -{amount} Stars ayirildi.")
        except Exception:
            pass
    else:
        await message.answer("❌ Balans yetarli emas yoki foydalanuvchi topilmadi.")


# =========================================
# ADMIN: BAN / UNBAN
# =========================================

@dp.message(F.text == "🚫 Ban / Unban")
async def ban_help(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🚫 Ban: <code>/ban ID</code>\n"
        "✅ Unban: <code>/unban ID</code>"
    )


@dp.message(Command("ban"))
async def ban_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        uid = int(message.text.split()[1])
    except (ValueError, IndexError):
        await message.answer("Foydalanish: /ban ID")
        return

    if is_admin(uid):
        await message.answer("Adminni bloklab bo'lmaydi.")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "UPDATE users SET banned=1 WHERE user_id=?",
            (uid,)
        )
        await db.commit()

    await message.answer(
        "✅ Bloklandi." if cur.rowcount else "❌ Foydalanuvchi topilmadi."
    )


@dp.message(Command("unban"))
async def unban_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        uid = int(message.text.split()[1])
    except (ValueError, IndexError):
        await message.answer("Foydalanish: /unban ID")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "UPDATE users SET banned=0 WHERE user_id=?",
            (uid,)
        )
        await db.commit()

    await message.answer(
        "✅ Blokdan chiqarildi."
        if cur.rowcount else "❌ Foydalanuvchi topilmadi."
    )


# =========================================
# ADMIN: STATISTIKA
# =========================================

@dp.message(F.text == "📊 Statistika")
async def admin_statistics(message: Message):
    if not is_admin(message.from_user.id):
        # Oddiy foydalanuvchi statistikasi
        if not await check_user(message):
            return

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM users"
            ) as cur:
                total = (await cur.fetchone())[0]

        await message.answer(f"📊 Bot foydalanuvchilari: {total}")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users"
        ) as cur:
            users = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE banned=1"
        ) as cur:
            banned = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COALESCE(SUM(stars),0) FROM users"
        ) as cur:
            stars = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM referrals WHERE active=1"
        ) as cur:
            refs = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM gifts WHERE status='pending'"
        ) as cur:
            gifts = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM topups WHERE status='pending'"
        ) as cur:
            topups = (await cur.fetchone())[0]

    await message.answer(
        "📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Jami foydalanuvchilar: {users}\n"
        f"🚫 Bloklanganlar: {banned}\n"
        f"⭐ Jami Stars: {stars}\n"
        f"🔗 Faol referallar: {refs}\n"
        f"🎁 Kutilayotgan gift: {gifts}\n"
        f"💰 Kutilayotgan hisob so'rovlari: {topups}"
    )


# =========================================
# ADMIN: REFERALLAR
# =========================================

@dp.message(F.text == "🔗 Referallar")
async def admin_referrals(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT referrer,invited,reward,active
        FROM referrals ORDER BY id DESC LIMIT 30
        """) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("Referallar mavjud emas.")
        return

    text = "🔗 <b>OXIRGI REFERALLAR</b>\n\n"

    for ref, invited, reward, active in rows:
        text += (
            f"👤 Taklif qiluvchi: {ref}\n"
            f"👥 Taklif qilingan: {invited}\n"
            f"⭐ Mukofot: {reward}\n"
            f"Holati: {'Faol' if active else 'Bekor'}\n\n"
        )

    await message.answer(text)


# =========================================
# ADMIN: REFERAL SOZLAMASI
# =========================================

@dp.message(F.text == "⚙️ Referal sozlamasi")
async def referral_settings(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        f"Joriy referal mukofoti: {await get_setting('referral_reward')} Stars\n\n"
        "Yangi Stars miqdorini yuboring:"
    )

    await state.set_state(Form.referral_reward)


@dp.message(Form.referral_reward)
async def referral_settings_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        amount = int(message.text)
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("0 yoki undan katta son yuboring.")
        return

    await set_setting("referral_reward", amount)
    await state.clear()

    await message.answer(
        f"✅ Har bir yangi referal uchun {amount} Stars belgilanadi."
    )


# =========================================
# ADMIN: KANAL QO'SHISH
# =========================================

@dp.message(F.text == "➕ Kanal qo'shish")
async def add_channel_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("Kanal username yuboring. Masalan: @kanal")
    await state.set_state(Form.add_channel)


@dp.message(Form.add_channel)
async def add_channel_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channel = message.text.strip()

    if not channel.startswith("@"):
        await message.answer("@username ko'rinishida yuboring.")
        return

    try:
        chat = await bot.get_chat(channel)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)

        if member.status != "administrator":
            await message.answer("Botni kanalga administrator qiling.")
            return

    except Exception:
        await message.answer("Kanal topilmadi yoki bot administrator emas.")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO channels(channel) VALUES(?)",
                (channel,)
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            await message.answer("Bu kanal oldin qo'shilgan.")
            return

    await state.clear()
    await message.answer(
        "✅ Kanal qo'shildi!",
        reply_markup=admin_menu()
    )


# =========================================
# ADMIN: KANAL O'CHIRISH
# =========================================

@dp.message(F.text == "➖ Kanal o'chirish")
async def remove_channel_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("O'chiriladigan kanal username yuboring:")
    await state.set_state(Form.remove_channel)


@dp.message(Form.remove_channel)
async def remove_channel_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "DELETE FROM channels WHERE channel=?",
            (message.text.strip(),)
        )
        await db.commit()

    await state.clear()

    await message.answer(
        "✅ Kanal o'chirildi."
        if cur.rowcount else "❌ Kanal topilmadi."
    )


# =========================================
# ADMIN: KANALLAR RO'YXATI
# =========================================

@dp.message(F.text == "📡 Kanallar")
async def channel_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = await get_channels()

    if not rows:
        await message.answer("Kanallar mavjud emas.")
        return

    text = "📡 <b>KANALLAR RO'YXATI</b>\n\n"

    for i, (channel,) in enumerate(rows, 1):
        text += f"{i}. {channel}\n"

    await message.answer(text)


# =========================================
# ADMIN: PROMOKOD YARATISH
# =========================================

@dp.message(F.text == "🎟 Promo yaratish")
async def promo_create_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "Format:\n"
        "<code>KOD STARS LIMIT</code>\n\n"
        "Misol: <code>WELCOME 20 100</code>\n"
        "LIMIT = 0 bo'lsa cheksiz."
    )

    await state.set_state(Form.promo_create)


@dp.message(Form.promo_create)
async def promo_create_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        code, stars, limit = message.text.upper().split()
        stars = int(stars)
        limit = int(limit)

        if stars <= 0 or limit < 0:
            raise ValueError
    except ValueError:
        await message.answer("Format: KOD STARS LIMIT")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute("""
            INSERT INTO promos(code,stars,limit_count)
            VALUES(?,?,?)
            """, (code, stars, limit))
            await db.commit()
        except aiosqlite.IntegrityError:
            await message.answer("Bu promokod mavjud.")
            return

    await state.clear()

    await message.answer(
        f"✅ Promokod yaratildi!\n"
        f"Kod: {code}\n"
        f"Stars: {stars}\n"
        f"Limit: {limit or 'Cheksiz'}"
    )


# =========================================
# ADMIN: PROMOKODLAR
# =========================================

@dp.message(F.text == "📋 Promokodlar")
async def promo_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT code,stars,limit_count,used FROM promos ORDER BY code"
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("Promokodlar yo'q.")
        return

    text = "🎟 <b>PROMOKODLAR</b>\n\n"

    for code, stars, limit, used in rows:
        text += (
            f"🔑 {code}\n"
            f"⭐ {stars} Stars\n"
            f"Foydalanilgan: {used}/{limit or '∞'}\n\n"
        )

    await message.answer(text)


# =========================================
# ADMIN: REKLAMA
# =========================================

@dp.message(F.text == "📢 Reklama")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("Tarqatiladigan xabarni yuboring:")
    await state.set_state(Form.broadcast)


@dp.message(Form.broadcast)
async def broadcast_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE banned=0"
        ) as cur:
            users = await cur.fetchall()

    sent = 0
    failed = 0

    for (uid,) in users:
        try:
            await bot.copy_message(
                uid,
                message.chat.id,
                message.message_id
            )
            sent += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    await message.answer(
        f"📢 Reklama tugadi!\n"
        f"✅ Yuborildi: {sent}\n"
        f"❌ Yuborilmadi: {failed}"
    )


# =========================================
# ADMIN: HISOB SO'ROVLARI
# =========================================

@dp.message(F.text == "💳 Hisob so'rovlari")
async def admin_topups(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT id,user_id,stars
        FROM topups WHERE status='pending'
        ORDER BY id DESC
        """) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("Kutilayotgan hisob so'rovlari yo'q.")
        return

    for rid, uid, amount in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"topup_yes:{rid}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"topup_no:{rid}"
            )
        ]])

        await message.answer(
            f"💳 So'rov #{rid}\n"
            f"User: {uid}\n"
            f"Stars: {amount}",
            reply_markup=kb
        )


# =========================================
# ADMIN: BAZA ZAXIRASI
# =========================================

@dp.message(F.text == "💾 Baza")
async def database_backup(message: Message):
    if not is_admin(message.from_user.id):
        return

    if not os.path.exists(DB_NAME):
        await message.answer("Baza topilmadi.")
        return

    await message.answer_document(
        FSInputFile(DB_NAME),
        caption="💾 Stars bot bazasi"
    )


# =========================================
# ADMIN: ASOSIY MENYU
# =========================================

@dp.message(F.text == "🏠 Asosiy menyu")
async def admin_home(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()

    await message.answer(
        "👑 ADMIN PANEL",
        reply_markup=admin_menu()
    )


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "👑 ADMIN PANEL",
        reply_markup=admin_menu()
    )


@dp.message(Command("id"))
async def id_command(message: Message):
    await message.answer(
        f"🆔 Sizning ID: <code>{message.from_user.id}</code>"
    )


# =========================================
# BEGONA XABARLAR
# =========================================

@dp.message()
async def unknown_message(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "Admin paneldan bo'lim tanlang.",
            reply_markup=admin_menu()
        )
    else:
        if not await check_user(message):
            return

        await message.answer(
            "Menyudan kerakli bo'limni tanlang.",
            reply_markup=user_menu()
        )


# =========================================
# ISHGA TUSHIRISH
# =========================================

async def main():
    await db_init()

    asyncio.create_task(referral_monitor())

    print("STARS BOT ISHGA TUSHDI")
    print("ADMIN 1:", ADMIN_ID_1)
    print("ADMIN 2:", ADMIN_ID_2)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
