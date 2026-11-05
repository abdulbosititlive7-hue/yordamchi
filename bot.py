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


# ==================================================
# SOZLAMALAR
# ==================================================

BOT_TOKEN = "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo"

ADMIN_ID_1 = 5200398952
ADMIN_ID_2 = 7676544759

DB_NAME = "stars.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(storage=MemoryStorage())


def is_admin(user_id):
    return user_id == ADMIN_ID_1 or user_id == ADMIN_ID_2


# ==================================================
# HOLATLAR
# ==================================================

class Form(StatesGroup):
    channel_add = State()
    channel_remove = State()
    promo_create = State()
    promo_use = State()
    search = State()
    stars_add = State()
    stars_remove = State()
    reward = State()
    broadcast = State()
    channel_message = State()
    schedule_time = State()
    schedule_text = State()
    topup = State()


# ==================================================
# ADMIN MENYUSI
# ==================================================

def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👥 Foydalanuvchilar"),
                KeyboardButton(text="📊 Statistika")
            ],
            [
                KeyboardButton(text="🔎 Qidirish"),
                KeyboardButton(text="🔗 Referallar")
            ],
            [
                KeyboardButton(text="📢 Reklama tarqatish"),
                KeyboardButton(text="📣 Kanallarga xabar")
            ],
            [
                KeyboardButton(text="⏰ Rejalashtirish"),
                KeyboardButton(text="🎟 Promokod yaratish")
            ],
            [
                KeyboardButton(text="📋 Promokodlar"),
                KeyboardButton(text="💾 Baza zaxirasi")
            ],
            [
                KeyboardButton(text="🚫 Ban / Unban qilish")
            ],
            [
                KeyboardButton(text="💰 Pul qo'shish"),
                KeyboardButton(text="💸 Pul ayirish")
            ],
            [
                KeyboardButton(text="⭐ Stars qo'shish"),
                KeyboardButton(text="📉 Stars ayirish")
            ],
            [
                KeyboardButton(text="➕ Kanal qo'shish"),
                KeyboardButton(text="🗑 Kanalni o'chirish")
            ],
            [
                KeyboardButton(text="📡 Kanallar ro'yxati"),
                KeyboardButton(text="🎁 Gift so'rovlari")
            ],
            [
                KeyboardButton(text="⚙️ Referal sozlamasi")
            ],
            [
                KeyboardButton(text="🏠 Asosiy menyu")
            ]
        ],
        resize_keyboard=True,
        persistent=True
    )


# ==================================================
# FOYDALANUVCHI MENYUSI
# ==================================================

def user_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="⭐ Stars olish"),
                KeyboardButton(text="🎁 Gift yechish")
            ],
            [
                KeyboardButton(text="📦 Buyurtmalar"),
                KeyboardButton(text="👤 Mening hisobim")
            ],
            [
                KeyboardButton(text="🗣 Referal"),
                KeyboardButton(text="💰 Hisob to'ldirish")
            ],
            [
                KeyboardButton(text="🎟 Promokod"),
                KeyboardButton(text="🏆 TOP referal")
            ],
            [
                KeyboardButton(text="☎️ Murojaat"),
                KeyboardButton(text="📚 Qo'llanma")
            ],
            [
                KeyboardButton(text="🎰 Open"),
                KeyboardButton(text="📊 Son")
            ],
            [
                KeyboardButton(text="ℹ️ Ma'lumot"),
                KeyboardButton(text="🌐 Til")
            ]
        ],
        resize_keyboard=True,
        persistent=True
    )


# ==================================================
# DATABASE
# ==================================================

async def db_init():
    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            stars INTEGER DEFAULT 0,
            referrer INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            created TEXT
        )
        """)

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
        CREATE TABLE IF NOT EXISTS gifts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            stars INTEGER,
            status TEXT DEFAULT 'pending',
            created TEXT
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


# ==================================================
# YORDAMCHI
# ==================================================

async def setting(name):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT value FROM settings WHERE name=?",
            (name,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else "0"


async def set_setting(name, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings VALUES(?,?)",
            (name, str(value))
        )
        await db.commit()


async def balance(uid):
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
            uid, amount, reason,
            datetime.now().isoformat()
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
            await db.execute(
                "UPDATE users SET username=? WHERE user_id=?",
                (message.from_user.username or "", uid)
            )
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
                user_id,username,stars,referrer,banned,created
            )
            VALUES(?,?,0,?,0,?)
            """, (
                uid,
                message.from_user.username or "",
                referrer,
                datetime.now().isoformat()
            ))

        await db.commit()


async def channels():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT channel FROM channels"
        ) as cur:
            return await cur.fetchall()


# ==================================================
# OBUNA TEKSHIRISH
# ==================================================

async def subscribed(uid):
    for (channel,) in await channels():
        try:
            member = await bot.get_chat_member(channel, uid)

            if member.status in ("left", "kicked"):
                return False

        except Exception:
            logging.exception("Kanal tekshirish xatosi")
            return False

    return True


async def subscription_keyboard():
    rows = []

    for (channel,) in await channels():
        try:
            chat = await bot.get_chat(channel)

            if channel.startswith("@"):
                link = "https://t.me/" + channel[1:]
            else:
                link = channel

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
            text="✅ Tekshirish",
            callback_data="check_subscription"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def allowed(message):
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

    if not await subscribed(uid):
        await message.answer(
            "📢 Avval kanallarga obuna bo'ling.",
            reply_markup=await subscription_keyboard()
        )
        return False

    return True


# ==================================================
# REFERAL
# ==================================================

async def referral_reward(uid):
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

        reward = int(await setting("referral_reward"))

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
                if not await subscribed(uid):
                    async with aiosqlite.connect(DB_NAME) as db:
                        await db.execute("BEGIN IMMEDIATE")

                        async with db.execute(
                            "SELECT stars FROM users WHERE user_id=?",
                            (ref,)
                        ) as cur:
                            row = await cur.fetchone()

                        if row:
                            new_balance = max(0, row[0] - reward)

                            await db.execute(
                                "UPDATE users SET stars=? WHERE user_id=?",
                                (new_balance, ref)
                            )

                            await db.execute("""
                            INSERT INTO transactions(
                                user_id,amount,reason,created
                            ) VALUES(?,?,?,?)
                            """, (
                                ref, -reward,
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
                                f"⭐ {reward} Stars bekor qilindi."
                            )
                        except Exception:
                            pass

                await asyncio.sleep(1)

        except Exception:
            logging.exception("Referal tekshirish xatosi")

        await asyncio.sleep(600)


# ==================================================
# START
# ==================================================

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

    if not await subscribed(message.from_user.id):
        await message.answer(
            "👋 Botga xush kelibsiz!\n"
            "Avval kanallarga obuna bo'ling.",
            reply_markup=await subscription_keyboard()
        )
        return

    await referral_reward(message.from_user.id)

    await message.answer(
        "👋 Assalomu alaykum!\n"
        "⭐ STARS BOT ga xush kelibsiz!",
        reply_markup=user_menu()
    )


@dp.callback_query(F.data == "check_subscription")
async def check_sub(call: CallbackQuery):
    if await subscribed(call.from_user.id):
        if not is_admin(call.from_user.id):
            await referral_reward(call.from_user.id)

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


# ==================================================
# FOYDALANUVCHI: STARS
# ==================================================

@dp.message(F.text == "⭐ Stars olish")
async def stars_get(message: Message):
    if not await allowed(message):
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"

    await message.answer(
        "⭐ <b>STARS OLISH</b>\n\n"
        "Do'stlaringizni taklif qiling.\n\n"
        f"🔗 <code>{link}</code>\n\n"
        f"Har bir referal: {await setting('referral_reward')} Stars"
    )


@dp.message(F.text == "👤 Mening hisobim")
async def my_account(message: Message):
    if not await allowed(message):
        return

    await message.answer(
        "👤 <b>MENING HISOBIM</b>\n\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"⭐ Stars: <b>{await balance(message.from_user.id)}</b>\n"
        f"👤 Username: @{message.from_user.username or 'yoq'}"
    )


@dp.message(F.text == "🗣 Referal")
async def my_referral(message: Message):
    if not await allowed(message):
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
        "🔗 <b>REFERAL</b>\n\n"
        f"Havolangiz:\n<code>{link}</code>\n\n"
        f"👥 Referallar: {count}\n"
        f"⭐ Jami mukofot: {earned}"
    )


@dp.message(F.text == "🏆 TOP referal")
async def top_ref(message: Message):
    if not await allowed(message):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT u.username,COUNT(r.id)
        FROM users u
        LEFT JOIN referrals r
        ON u.user_id=r.referrer AND r.active=1
        GROUP BY u.user_id
        ORDER BY COUNT(r.id) DESC LIMIT 10
        """) as cur:
            rows = await cur.fetchall()

    text = "🏆 <b>TOP REFERAL</b>\n\n"

    for i, (username, count) in enumerate(rows, 1):
        text += f"{i}. @{username or 'user'} — {count}\n"

    await message.answer(text)


# ==================================================
# FOYDALANUVCHI: GIFT
# ==================================================

@dp.message(F.text == "🎁 Gift yechish")
async def gift_menu(message: Message):
    if not await allowed(message):
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎁 15 Stars Gift"),
                KeyboardButton(text="🎁 25 Stars Gift")
            ],
            [
                KeyboardButton(text="🎁 50 Stars Gift"),
                KeyboardButton(text="🎁 100 Stars Gift")
            ],
            [
                KeyboardButton(text="⬅️ Orqaga")
            ]
        ],
        resize_keyboard=True,
        persistent=True
    )

    await message.answer(
        "🎁 Gift miqdorini tanlang:",
        reply_markup=kb
    )


@dp.message(F.text.in_([
    "🎁 15 Stars Gift",
    "🎁 25 Stars Gift",
    "🎁 50 Stars Gift",
    "🎁 100 Stars Gift"
]))
async def gift_order(message: Message):
    if not await allowed(message):
        return

    amount = int(message.text.split()[1])
    uid = message.from_user.id

    if await balance(uid) < amount:
        await message.answer(
            f"❌ Stars yetarli emas!\n"
            f"Balans: {await balance(uid)} Stars"
        )
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("""
        INSERT INTO gifts(user_id,stars,created)
        VALUES(?,?,?)
        """, (uid, amount, datetime.now().isoformat()))

        gid = cur.lastrowid
        await db.commit()

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

    for admin in (ADMIN_ID_1, ADMIN_ID_2):
        try:
            await bot.send_message(
                admin,
                f"🎁 Gift so'rovi\n"
                f"ID: {gid}\n"
                f"User: {uid}\n"
                f"Stars: {amount}",
                reply_markup=kb
            )
        except Exception:
            pass

    await message.answer("✅ Gift so'rovingiz adminga yuborildi.")


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
            await call.answer("So'rov allaqachon ko'rib chiqilgan.")
            return

        uid, amount, _ = row

        async with db.execute(
            "SELECT stars FROM users WHERE user_id=?",
            (uid,)
        ) as cur:
            bal = await cur.fetchone()

        if not bal or bal[0] < amount:
            await db.execute(
                "UPDATE gifts SET status='rejected' WHERE id=?",
                (gid,)
            )
            await db.commit()
            await call.message.edit_text("❌ Balans yetarli emas.")
            await bot.send_message(uid, "❌ Gift rad etildi: balans yetarli emas.")
            return

        await db.execute(
            "UPDATE users SET stars=stars-? WHERE user_id=?",
            (amount, uid)
        )

        await db.execute(
            "UPDATE gifts SET status='approved' WHERE id=?",
            (gid,)
        )

        await db.execute("""
        INSERT INTO transactions(user_id,amount,reason,created)
        VALUES(?,?,?,?)
        """, (
            uid, -amount, "Gift yechish",
            datetime.now().isoformat()
        ))

        await db.commit()

    await call.message.edit_text("✅ Gift tasdiqlandi.")

    await bot.send_message(
        uid,
        f"🎁 Gift tasdiqlandi!\n⭐ -{amount} Stars"
    )

    await call.answer("Bajarildi!")


@dp.callback_query(F.data.startswith("gift_no:"))
async def gift_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return

    gid = int(call.data.split(":")[1])

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id,status FROM gifts WHERE id=?",
            (gid,)
        ) as cur:
            row = await cur.fetchone()

        if not row or row[1] != "pending":
            await call.answer("So'rov ko'rib chiqilgan.")
            return

        await db.execute(
            "UPDATE gifts SET status='rejected' WHERE id=?",
            (gid,)
        )
        await db.commit()

    await call.message.edit_text("❌ Gift rad etildi.")
    await bot.send_message(row[0], "❌ Gift so'rovingiz rad etildi.")
    await call.answer("Rad etildi!")


# ==================================================
# BUYURTMALAR
# ==================================================

@dp.message(F.text == "📦 Buyurtmalar")
async def orders(message: Message):
    if not await allowed(message):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT id,stars,status,created
        FROM gifts WHERE user_id=?
        ORDER BY id DESC LIMIT 20
        """, (message.from_user.id,)) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("📦 Buyurtmalar mavjud emas.")
        return

    text = "📦 <b>BUYURTMALAR</b>\n\n"

    for gid, stars, status, created in rows:
        text += f"#{gid} — {stars} Stars\n{status}\n{created}\n\n"

    await message.answer(text)


# ==================================================
# HISOB TO'LDIRISH
# ==================================================

@dp.message(F.text == "💰 Hisob to'ldirish")
async def topup_start(message: Message, state: FSMContext):
    if not await allowed(message):
        return

    await message.answer("Qancha Stars olmoqchisiz? Miqdorni yuboring:")
    await state.set_state(Form.topup)


@dp.message(Form.topup)
async def topup_finish(message: Message, state: FSMContext):
    if not await allowed(message):
        return

    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat son kiriting.")
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
                f"💰 Hisob to'ldirish\n"
                f"ID: {rid}\n"
                f"User: {message.from_user.id}\n"
                f"Stars: {amount}",
                reply_markup=kb
            )
        except Exception:
            pass

    await state.clear()
    await message.answer("✅ So'rov yuborildi. Admin tasdiqlashini kuting.")


@dp.callback_query(F.data.startswith("topup_yes:"))
async def topup_approve(call: CallbackQuery):
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
    await bot.send_message(uid, f"🎉 +{amount} Stars hisobingizga qo'shildi!")
    await call.answer("Bajarildi!")


@dp.callback_query(F.data.startswith("topup_no:"))
async def topup_reject(call: CallbackQuery):
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
    await bot.send_message(row[0], "❌ Hisob to'ldirish rad etildi.")
    await call.answer("Rad etildi!")


# ==================================================
# PROMOKOD FOYDALANISH
# ==================================================

@dp.message(F.text == "🎟 Promokod")
async def promo_start(message: Message, state: FSMContext):
    if not await allowed(message):
        return

    await message.answer("🎟 Promokodni yuboring:")
    await state.set_state(Form.promo_use)


@dp.message(Form.promo_use)
async def promo_use(message: Message, state: FSMContext):
    if not await allowed(message):
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
            await message.answer("❌ Bu promokoddan foydalangansiz.")
            return

        stars, limit, count = row

        if limit > 0 and count >= limit:
            await db.rollback()
            await state.clear()
            await message.answer("❌ Promokod tugagan.")
            return

        await db.execute(
            "INSERT INTO promo_users VALUES(?,?)",
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


# ==================================================
# SLOT
# ==================================================

@dp.message(F.text == "🎰 Open")
async def slot(message: Message):
    if not await allowed(message):
        return

    dice = await message.answer_dice(emoji="🎰")

    if dice.dice.value == 64:
        await change_stars(
            message.from_user.id, 5, "777 slot yutug'i"
        )
        await message.answer("🎉 JACKPOT! +5 Stars")
    else:
        await message.answer("🎰 Omad kelmadi. Yana urinib ko'ring!")


# ==================================================
# FOYDALANUVCHI QOLGAN MENYULARI
# ==================================================

@dp.message(F.text == "📊 Son")
async def user_stats(message: Message):
    if not await allowed(message):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users"
        ) as cur:
            count = (await cur.fetchone())[0]

    await message.answer(f"📊 Bot foydalanuvchilari: {count}")


@dp.message(F.text == "☎️ Murojaat")
async def support(message: Message):
    if not await allowed(message):
        return

    await message.answer(
        "☎️ Yordam uchun adminlarga murojaat qiling:\n\n"
        f"Admin 1 ID: <code>{ADMIN_ID_1}</code>\n"
        f"Admin 2 ID: <code>{ADMIN_ID_2}</code>"
    )


@dp.message(F.text == "📚 Qo'llanma")
async def guide(message: Message):
    if not await allowed(message):
        return

    await message.answer(
        "📚 <b>QO'LLANMA</b>\n\n"
        "⭐ Stars olish — referal orqali Stars yig'ish.\n"
        "🎁 Gift yechish — gift so'rovi yuborish.\n"
        "📦 Buyurtmalar — buyurtmalar tarixini ko'rish.\n"
        "👤 Mening hisobim — balansni tekshirish.\n"
        "🗣 Referal — havolangizni olish.\n"
        "🎟 Promokod — kodni ishlatish."
    )


@dp.message(F.text == "ℹ️ Ma'lumot")
async def info(message: Message):
    if not await allowed(message):
        return

    await message.answer(
        "⭐ STARS BOT\n\n"
        "Referal, Stars va gift buyurtmalari tizimi."
    )


@dp.message(F.text == "🌐 Til")
async def language(message: Message):
    if not await allowed(message):
        return

    await message.answer("🌐 Hozirgi til: O'zbek tili.")


@dp.message(F.text == "⬅️ Orqaga")
async def back(message: Message):
    await message.answer(
        "Asosiy menyu:",
        reply_markup=user_menu()
    )


# ==================================================
# ADMIN: FOYDALANUVCHILAR
# ==================================================

@dp.message(F.text == "👥 Foydalanuvchilar")
async def admin_users(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT user_id,username,stars,banned
        FROM users ORDER BY user_id DESC LIMIT 30
        """) as cur:
            rows = await cur.fetchall()

    text = "👥 <b>FOYDALANUVCHILAR</b>\n\n"

    for uid, username, stars, banned in rows:
        text += (
            f"ID: {uid}\n"
            f"Username: @{username or 'yoq'}\n"
            f"Stars: {stars}\n"
            f"Holati: {'Ban' if banned else 'Faol'}\n\n"
        )

    await message.answer(text if rows else "Foydalanuvchilar yo'q.")


# ==================================================
# ADMIN: STATISTIKA
# ==================================================

@dp.message(F.text == "📊 Statistika")
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users"
        ) as cur:
            users = (await cur.fetchone())[0]

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

    await message.answer(
        "📊 <b>STATISTIKA</b>\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"⭐ Jami Stars: {stars}\n"
        f"🔗 Faol referallar: {refs}\n"
        f"🎁 Kutilayotgan gift: {gifts}"
    )


# ==================================================
# ADMIN: QIDIRISH
# ==================================================

@dp.message(F.text == "🔎 Qidirish")
async def search_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("Foydalanuvchi ID sini yuboring:")
    await state.set_state(Form.search)


@dp.message(Form.search)
async def search_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        uid = int(message.text)
    except ValueError:
        await message.answer("ID raqam bo'lishi kerak.")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT username,stars,banned,created
        FROM users WHERE user_id=?
        """, (uid,)) as cur:
            row = await cur.fetchone()

    await state.clear()

    if not row:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return

    await message.answer(
        f"👤 @{row[0] or 'yoq'}\n"
        f"🆔 {uid}\n"
        f"⭐ {row[1]}\n"
        f"🚫 Ban: {row[2]}\n"
        f"📅 {row[3]}"
    )


# ==================================================
# ADMIN: REFERALLAR
# ==================================================

@dp.message(F.text == "🔗 Referallar")
async def admin_refs(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT referrer,invited,reward,active
        FROM referrals ORDER BY id DESC LIMIT 30
        """) as cur:
            rows = await cur.fetchall()

    text = "🔗 <b>REFERALLAR</b>\n\n"

    for ref, invited, reward, active in rows:
        text += (
            f"Taklif qiluvchi: {ref}\n"
            f"Taklif qilingan: {invited}\n"
            f"Mukofot: {reward} Stars\n"
            f"Holati: {'Faol' if active else 'Bekor'}\n\n"
        )

    await message.answer(text if rows else "Referallar mavjud emas.")


# ==================================================
# ADMIN: STARS QO'SHISH
# ==================================================

@dp.message(F.text.in_([
    "💰 Pul qo'shish",
    "⭐ Stars qo'shish"
]))
async def add_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "ID va miqdorni yuboring:\n"
        "<code>123456789 50</code>"
    )
    await state.set_state(Form.stars_add)


@dp.message(Form.stars_add)
async def add_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        uid, amount = map(int, message.text.split())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Format: ID MIQDOR")
        return

    result = await change_stars(uid, amount, "Admin Stars qo'shdi")
    await state.clear()

    if result:
        await message.answer("✅ Stars qo'shildi.")
        try:
            await bot.send_message(uid, f"⭐ +{amount} Stars qo'shildi!")
        except Exception:
            pass
    else:
        await message.answer("❌ Foydalanuvchi topilmadi.")


# ==================================================
# ADMIN: STARS AYIRISH
# ==================================================

@dp.message(F.text.in_([
    "💸 Pul ayirish",
    "📉 Stars ayirish"
]))
async def remove_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "ID va miqdorni yuboring:\n"
        "<code>123456789 10</code>"
    )
    await state.set_state(Form.stars_remove)


@dp.message(Form.stars_remove)
async def remove_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        uid, amount = map(int, message.text.split())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Format: ID MIQDOR")
        return

    result = await change_stars(uid, -amount, "Admin Stars ayirdi")
    await state.clear()

    await message.answer(
        "✅ Stars ayirildi."
        if result
        else "❌ Foydalanuvchi topilmadi yoki Stars yetarli emas."
    )


# ==================================================
# ADMIN: BAN / UNBAN
# ==================================================

@dp.message(F.text == "🚫 Ban / Unban qilish")
async def ban_help(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🚫 Bloklash: <code>/ban ID</code>\n"
        "✅ Blokdan chiqarish: <code>/unban ID</code>"
    )


@dp.message(Command("ban"))
async def ban(message: Message):
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
async def unban(message: Message):
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


# ==================================================
# ADMIN: KANAL QO'SHISH
# ==================================================

@dp.message(F.text == "➕ Kanal qo'shish")
async def channel_add_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "Kanal username yuboring.\n"
        "Misol: <code>@kanal_nomi</code>\n"
        "Bot kanal administratori bo'lishi kerak."
    )
    await state.set_state(Form.channel_add)


@dp.message(Form.channel_add)
async def channel_add_finish(message: Message, state: FSMContext):
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
        await message.answer("Kanal topilmadi yoki bot admin emas.")
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


# ==================================================
# ADMIN: KANAL O'CHIRISH
# ==================================================

@dp.message(F.text == "🗑 Kanalni o'chirish")
async def channel_remove_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("O'chiriladigan kanalni yuboring:")
    await state.set_state(Form.channel_remove)


@dp.message(Form.channel_remove)
async def channel_remove_finish(message: Message, state: FSMContext):
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


# ==================================================
# ADMIN: KANALLAR RO'YXATI
# ==================================================

@dp.message(F.text == "📡 Kanallar ro'yxati")
async def channel_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = await channels()

    text = "📡 <b>KANALLAR</b>\n\n"

    for i, (channel,) in enumerate(rows, 1):
        text += f"{i}. {channel}\n"

    await message.answer(text if rows else "Kanallar mavjud emas.")


# ==================================================
# ADMIN: REFERAL SOZLAMASI
# ==================================================

@dp.message(F.text == "⚙️ Referal sozlamasi")
async def reward_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        f"Hozirgi mukofot: {await setting('referral_reward')} Stars\n\n"
        "Yangi miqdorni yuboring:"
    )
    await state.set_state(Form.reward)


@dp.message(Form.reward)
async def reward_finish(message: Message, state: FSMContext):
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
        f"✅ Referal mukofoti {amount} Stars qilindi."
    )


# ==================================================
# ADMIN: PROMOKOD YARATISH
# ==================================================

@dp.message(F.text == "🎟 Promokod yaratish")
async def promo_create_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "Format:\n"
        "<code>KOD STARS LIMIT</code>\n\n"
        "Misol: <code>WELCOME 20 100</code>\n"
        "0 = cheksiz"
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
            await db.execute(
                "INSERT INTO promos(code,stars,limit_count) VALUES(?,?,?)",
                (code, stars, limit)
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            await message.answer("Promokod mavjud.")
            return

    await state.clear()

    await message.answer(
        f"✅ Promokod yaratildi!\n"
        f"Kod: <code>{code}</code>\n"
        f"Stars: {stars}\n"
        f"Limit: {limit or 'Cheksiz'}"
    )


# ==================================================
# ADMIN: PROMOKODLAR
# ==================================================

@dp.message(F.text == "📋 Promokodlar")
async def promo_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT code,stars,limit_count,used FROM promos"
        ) as cur:
            rows = await cur.fetchall()

    text = "🎟 <b>PROMOKODLAR</b>\n\n"

    for code, stars, limit, used in rows:
        text += (
            f"🔑 {code}\n"
            f"⭐ {stars}\n"
            f"Foydalanilgan: {used}/{limit or '∞'}\n\n"
        )

    await message.answer(text if rows else "Promokodlar yo'q.")


# ==================================================
# ADMIN: REKLAMA
# ==================================================

@dp.message(F.text == "📢 Reklama tarqatish")
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
        f"📢 Tarqatish tugadi!\n"
        f"✅ Yuborildi: {sent}\n"
        f"❌ Yuborilmadi: {failed}"
    )


# ==================================================
# ADMIN: KANALLARGA XABAR
# ==================================================

@dp.message(F.text == "📣 Kanallarga xabar")
async def channel_broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("Kanallarga yuboriladigan xabarni yuboring:")
    await state.set_state(Form.channel_message)


@dp.message(Form.channel_message)
async def channel_broadcast_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()

    sent = 0
    failed = 0

    for (channel,) in await channels():
        try:
            await bot.copy_message(
                channel,
                message.chat.id,
                message.message_id
            )
            sent += 1
        except Exception:
            failed += 1

    await message.answer(
        f"📣 Yuborildi: {sent}\n"
        f"❌ Xato: {failed}"
    )


# ==================================================
# ADMIN: REJALASHTIRISH
# ==================================================

@dp.message(F.text == "⏰ Rejalashtirish")
async def schedule_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("Necha daqiqadan keyin yuborilsin?")
    await state.set_state(Form.schedule_time)


@dp.message(Form.schedule_time)
async def schedule_time(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        minutes = int(message.text)
        if minutes < 1:
            raise ValueError
    except ValueError:
        await message.answer("Kamida 1 daqiqa kiriting.")
        return

    await state.update_data(minutes=minutes)
    await message.answer("Yuboriladigan xabarni yuboring:")
    await state.set_state(Form.schedule_text)


@dp.message(Form.schedule_text)
async def schedule_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    minutes = data["minutes"]

    chat_id = message.chat.id
    message_id = message.message_id

    await state.clear()

    await message.answer(
        f"✅ Xabar {minutes} daqiqadan keyin yuboriladi."
    )

    async def send_later():
        await asyncio.sleep(minutes * 60)

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT user_id FROM users WHERE banned=0"
            ) as cur:
                users = await cur.fetchall()

        for (uid,) in users:
            try:
                await bot.copy_message(uid, chat_id, message_id)
            except Exception:
                pass

            await asyncio.sleep(0.05)

    asyncio.create_task(send_later())


# ==================================================
# ADMIN: GIFT SO'ROVLARI
# ==================================================

@dp.message(F.text == "🎁 Gift so'rovlari")
async def admin_gifts(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
        SELECT id,user_id,stars FROM gifts
        WHERE status='pending'
        ORDER BY id
        """) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("Gift so'rovlari yo'q.")
        return

    for gid, uid, stars in rows:
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
            f"🎁 Gift #{gid}\n"
            f"User: {uid}\n"
            f"Stars: {stars}",
            reply_markup=kb
        )


# ==================================================
# ADMIN: BAZA ZAXIRASI
# ==================================================

@dp.message(F.text == "💾 Baza zaxirasi")
async def backup(message: Message):
    if not is_admin(message.from_user.id):
        return

    if not os.path.exists(DB_NAME):
        await message.answer("Baza topilmadi.")
        return

    await message.answer_document(
        FSInputFile(DB_NAME),
        caption="💾 Stars bot bazasi"
    )


# ==================================================
# ADMIN: ASOSIY MENYU
# ==================================================

@dp.message(F.text == "🏠 Asosiy menyu")
async def admin_home(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()

    await message.answer(
        "👑 Admin panel",
        reply_markup=admin_menu()
    )


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "👑 Admin panel",
        reply_markup=admin_menu()
    )


# ==================================================
# ID
# ==================================================

@dp.message(Command("id"))
async def get_id(message: Message):
    await message.answer(
        f"🆔 ID: <code>{message.from_user.id}</code>"
    )


# ==================================================
# NOMA'LUM XABAR
# ==================================================

@dp.message()
async def unknown(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "Admin paneldan bo'lim tanlang.",
            reply_markup=admin_menu()
        )
    else:
        if not await allowed(message):
            return

        await message.answer(
            "Menyudan bo'lim tanlang.",
            reply_markup=user_menu()
        )


# ==================================================
# ISHGA TUSHIRISH
# ==================================================

async def main():
    await db_init()

    asyncio.create_task(referral_monitor())

    print("STARS BOT ISHGA TUSHDI")
    print("ADMIN 1:", ADMIN_ID_1)
    print("ADMIN 2:", ADMIN_ID_2)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
