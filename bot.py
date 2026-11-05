
import asyncio
import logging
import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup,
    KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ================= SOZLAMALAR =================

BOT_TOKEN = "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo"

ADMIN_ID_1 = 5200398952
ADMIN_ID_2 = 7676544759

DB = "stars.db"

# ===============================================

logging.basicConfig(level=logging.INFO)

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


def is_admin(user_id):
    return user_id in [ADMIN_ID_1, ADMIN_ID_2]


class Form(StatesGroup):
    add_channel = State()
    remove_channel = State()
    set_reward = State()
    advertisement = State()
    support = State()


def user_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⭐ Stars balansim"),
             KeyboardButton(text="👥 Referal")],
            [KeyboardButton(text="🎁 Sovg'alar"),
             KeyboardButton(text="📊 Reyting")],
            [KeyboardButton(text="📢 Kanallar"),
             KeyboardButton(text="☎️ Yordam")]
        ],
        resize_keyboard=True,
        persistent=True
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Statistika"),
             KeyboardButton(text="👥 Foydalanuvchilar")],
            [KeyboardButton(text="➕ Kanal qo'shish"),
             KeyboardButton(text="➖ Kanal o'chirish")],
            [KeyboardButton(text="📋 Kanallar"),
             KeyboardButton(text="📢 Kanalga reklama")],
            [KeyboardButton(text="⭐ Referal Stars sozlash"),
             KeyboardButton(text="🎁 Sovg'a so'rovlari")],
            [KeyboardButton(text="📨 Xabar yuborish"),
             KeyboardButton(text="⬅️ Menyu")]
        ],
        resize_keyboard=True,
        persistent=True
    )


async def db():
    return await aiosqlite.connect(DB)


async def init_db():
    async with aiosqlite.connect(DB) as con:
        await con.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT,
            stars INTEGER DEFAULT 0,
            referrer INTEGER,
            banned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS channels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT UNIQUE
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS referrals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter INTEGER,
            invited INTEGER UNIQUE,
            active INTEGER DEFAULT 1,
            reward INTEGER DEFAULT 0
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS gifts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            gift TEXT,
            price INTEGER,
            status TEXT DEFAULT 'pending'
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        await con.execute("""
        INSERT OR IGNORE INTO settings(key,value)
        VALUES('referral_reward','5')
        """)

        await con.commit()


async def get_reward():
    async with aiosqlite.connect(DB) as con:
        cur = await con.execute(
            "SELECT value FROM settings WHERE key='referral_reward'"
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 5


async def get_channels():
    async with aiosqlite.connect(DB) as con:
        cur = await con.execute("SELECT channel FROM channels")
        return await cur.fetchall()


async def check_subscription(user_id):
    channels = await get_channels()

    for (channel,) in channels:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception:
            logging.exception("Kanal obunasini tekshirishda xato")
            return None

    return True


async def subscription_keyboard():
    channels = await get_channels()
    rows = []

    for (channel,) in channels:
        try:
            chat = await bot.get_chat(channel)
            link = chat.invite_link

            if not link:
                if chat.username:
                    link = f"https://t.me/{chat.username}"
                else:
                    continue

            rows.append([
                InlineKeyboardButton(
                    text=f"📢 {chat.title}",
                    url=link
                )
            ])
        except Exception:
            continue

    rows.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def give_referral(user_id):
    async with aiosqlite.connect(DB) as con:
        cur = await con.execute(
            "SELECT referrer FROM users WHERE user_id=?",
            (user_id,)
        )
        row = await cur.fetchone()

        if not row or not row[0]:
            return

        inviter = row[0]

        if inviter == user_id:
            return

        cur = await con.execute(
            "SELECT id FROM referrals WHERE invited=?",
            (user_id,)
        )
        if await cur.fetchone():
            return

        reward = await get_reward()

        await con.execute(
            "UPDATE users SET stars=stars+? WHERE user_id=?",
            (reward, inviter)
        )

        await con.execute(
            "INSERT INTO referrals(inviter,invited,reward) VALUES(?,?,?)",
            (inviter, user_id, reward)
        )

        await con.commit()

    try:
        await bot.send_message(
            inviter,
            f"🎉 Yangi referalingiz tasdiqlandi!\n"
            f"⭐ Hisobingizga <b>{reward} Stars</b> qo'shildi."
        )
    except Exception:
        pass


async def register_user(message, referrer=None):
    user = message.from_user

    async with aiosqlite.connect(DB) as con:
        cur = await con.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (user.id,)
        )
        exists = await cur.fetchone()

        if not exists:
            if referrer == user.id:
                referrer = None

            if referrer:
                cur = await con.execute(
                    "SELECT user_id FROM users WHERE user_id=?",
                    (referrer,)
                )
                if not await cur.fetchone():
                    referrer = None

            await con.execute("""
                INSERT INTO users(user_id,name,username,referrer)
                VALUES(?,?,?,?)
            """, (
                user.id,
                user.full_name,
                user.username,
                referrer
            ))
        else:
            await con.execute(
                "UPDATE users SET name=?,username=? WHERE user_id=?",
                (user.full_name, user.username, user.id)
            )

        await con.commit()


async def show_home(message):
    if is_admin(message.from_user.id):
        await message.answer(
            "👑 <b>ADMIN PANEL</b>",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "🏠 <b>Asosiy menyu</b>",
            reply_markup=user_menu()
        )


@dp.message(CommandStart())
async def start(message: Message):
    referrer = None

    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].isdigit():
        referrer = int(parts[1])

    await register_user(message, referrer)

    async with aiosqlite.connect(DB) as con:
        cur = await con.execute(
            "SELECT banned FROM users WHERE user_id=?",
            (message.from_user.id,)
        )
        row = await cur.fetchone()

    if row and row[0]:
        return await message.answer("⛔ Siz bloklangansiz.")

    status = await check_subscription(message.from_user.id)

    if status is False:
        return await message.answer(
            "❗ Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
            reply_markup=await subscription_keyboard()
        )

    if status is None:
        return await message.answer(
            "⚠️ Obunani tekshirishda xatolik. Keyinroq urinib ko'ring."
        )

    await give_referral(message.from_user.id)
    await show_home(message)


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):
    status = await check_subscription(call.from_user.id)

    if status is True:
        await give_referral(call.from_user.id)
        await call.message.answer(
            "✅ Obuna tasdiqlandi!",
            reply_markup=admin_menu() if is_admin(call.from_user.id)
            else user_menu()
        )
    elif status is False:
        await call.answer("Avval barcha kanallarga obuna bo'ling!", show_alert=True)
    else:
        await call.answer("Tekshirishda xatolik. Keyinroq urinib ko'ring.",
                          show_alert=True)


# ================ FOYDALANUVCHI =================

@dp.message(F.text == "⬅️ Menyu")
async def back_menu(message: Message):
    await show_home(message)


@dp.message(F.text == "⭐ Stars balansim")
async def balance(message: Message):
    async with aiosqlite.connect(DB) as con:
        cur = await con.execute(
            "SELECT stars FROM users WHERE user_id=?",
            (message.from_user.id,)
        )
        row = await cur.fetchone()

    stars = row[0] if row else 0

    await message.answer(
        f"⭐ <b>Stars balansingiz:</b> {stars}"
    )


@dp.message(F.text == "👥 Referal")
async def referral(message: Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"

    async with aiosqlite.connect(DB) as con:
        cur = await con.execute(
            "SELECT COUNT(*) FROM referrals WHERE inviter=? AND active=1",
            (message.from_user.id,)
        )
        count = (await cur.fetchone())[0]

    reward = await get_reward()

    await message.answer(
        f"👥 <b>Referal tizimi</b>\n\n"
        f"🔗 Sizning havolangiz:\n<code>{link}</code>\n\n"
        f"👤 Faol referallar: {count}\n"
        f"⭐ Har bir referal uchun: {reward} Stars\n\n"
        f"Do'stlaringizni taklif qiling va Stars yig'ing!"
    )


@dp.message(F.text == "🎁 Sovg'alar")
async def gifts(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 15 Stars sovg'a",
                              callback_data="gift_15")],
        [InlineKeyboardButton(text="🎁 25 Stars sovg'a",
                              callback_data="gift_25")]
    ])

    await message.answer(
        "🎁 <b>Sovg'alar bo'limi</b>\n"
        "Kerakli sovg'ani tanlang. Narxi Stars balansingizdan ayriladi.",
        reply_markup=kb
    )


@dp.callback_query(F.data.in_(["gift_15", "gift_25"]))
async def gift_request(call: CallbackQuery):
    price = int(call.data.split("_")[1])

    async with aiosqlite.connect(DB) as con:
        await con.execute("BEGIN IMMEDIATE")

        cur = await con.execute(
            "SELECT stars FROM users WHERE user_id=?",
            (call.from_user.id,)
        )
        row = await cur.fetchone()

        if not row or row[0] < price:
            await con.rollback()
            return await call.answer(
                "❌ Stars yetarli emas!",
                show_alert=True
            )

        await con.execute(
            "UPDATE users SET stars=stars-? WHERE user_id=?",
            (price, call.from_user.id)
        )

        await con.execute(
            "INSERT INTO gifts(user_id,gift,price) VALUES(?,?,?)",
            (call.from_user.id, f"{price} Stars sovg'a", price)
        )

        cur = await con.execute("SELECT last_insert_rowid()")
        gift_id = (await cur.fetchone())[0]

        await con.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"gift_ok_{gift_id}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"gift_no_{gift_id}"
            )
        ]
    ])

    for admin in [ADMIN_ID_1, ADMIN_ID_2]:
        try:
            await bot.send_message(
                admin,
                f"🎁 <b>Yangi sovg'a so'rovi</b>\n"
                f"Foydalanuvchi: <code>{call.from_user.id}</code>\n"
                f"Sovg'a: {price} Stars",
                reply_markup=kb
            )
        except Exception:
            pass

    await call.answer("So'rov yuborildi!")
    await call.message.answer(
        "✅ Sovg'a so'rovingiz adminga yuborildi."
    )


@dp.callback_query(F.data.startswith("gift_ok_"))
async def gift_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q!", show_alert=True)

    gift_id = int(call.data.split("_")[2])

    async with aiosqlite.connect(DB) as con:
        cur = await con.execute(
            "SELECT user_id,status FROM gifts WHERE id=?",
            (gift_id,)
        )
        row = await cur.fetchone()

        if not row or row[1] != "pending":
            return await call.answer("Bu so'rov allaqachon ko'rib chiqilgan.")

        await con.execute(
            "UPDATE gifts SET status='approved' WHERE id=?",
            (gift_id,)
        )
        await con.commit()

    await bot.send_message(
        row[0],
        "🎉 Sovg'a so'rovingiz tasdiqlandi!"
    )
    await call.message.edit_text("✅ Sovg'a tasdiqlandi.")


@dp.callback_query(F.data.startswith("gift_no_"))
async def gift_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q!", show_alert=True)

    gift_id = int(call.data.split("_")[2])

    async with aiosqlite.connect(DB) as con:
        cur = await con.execute(
            "SELECT user_id,price,status FROM gifts WHERE id=?",
            (gift_id,)
        )
        row = await cur.fetchone()

        if not row or row[2] != "pending":
            return await call.answer("Bu so'rov allaqachon ko'rib chiqilgan.")

        await con.execute(
            "UPDATE users SET stars=stars+? WHERE user_id=?",
            (row[1], row[0])
        )
        await con.execute(
            "UPDATE gifts SET status='rejected' WHERE id=?",
            (gift_id,)
        )
        await con.commit()

    await bot.send_message(
        row[0],
        f"❌ So'rovingiz rad etildi. {row[1]} Stars balansingizga qaytarildi."
    )
    await call.message.edit_text("❌ So'rov rad etildi. Stars qaytarildi.")


@dp.message(F.text == "📊 Reyting")
async def leaderboard(message: Message):
    async with aiosqlite.connect(DB) as con:
        cur = await con.execute("""
            SELECT name,stars FROM users
            ORDER BY stars DESC LIMIT 10
        """)
        rows = await cur.fetchall()

    text = "🏆 <b>TOP 10 foydalanuvchi</b>\n\n"

    for i, (name, stars) in enumerate(rows, 1):
        text += f"{i}. {name} — ⭐ {stars}\n"

    await message.answer(text)


@dp.message(F.text == "📢 Kanallar")
async def user_channels(message: Message):
    channels = await get_channels()

    if not channels:
        return await message.answer("Hozircha kanallar yo'q.")

    text = "📢 <b>Bizning kanallar:</b>\n\n"

    for (channel,) in channels:
        try:
            chat = await bot.get_chat(channel)
            link = f"https://t.me/{chat.username}" if chat.username else channel
            text += f"• <a href='{link}'>{chat.title}</a>\n"
        except Exception:
            text += f"• {channel}\n"

    await message.answer(text)


@dp.message(F.text == "☎️ Yordam")
async def support(message: Message):
    await message.answer(
        "☎️ Yordam uchun admin bilan bog'laning:\n"
        f"<a href='tg://user?id={ADMIN_ID_1}'>Admin</a>"
    )


# ================= ADMIN PANEL =================

@dp.message(F.text == "📊 Statistika")
async def statistics(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB) as con:
        users = (await (await con.execute(
            "SELECT COUNT(*) FROM users"
        )).fetchone())[0]

        stars = (await (await con.execute(
            "SELECT COALESCE(SUM(stars),0) FROM users"
        )).fetchone())[0]

        refs = (await (await con.execute(
            "SELECT COUNT(*) FROM referrals WHERE active=1"
        )).fetchone())[0]

        gifts = (await (await con.execute(
            "SELECT COUNT(*) FROM gifts WHERE status='pending'"
        )).fetchone())[0]

    await message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"⭐ Jami Stars: {stars}\n"
        f"👥 Faol referallar: {refs}\n"
        f"🎁 Kutilayotgan sovg'alar: {gifts}"
    )


@dp.message(F.text == "👥 Foydalanuvchilar")
async def users_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB) as con:
        cur = await con.execute("""
            SELECT user_id,name,stars FROM users
            ORDER BY created_at DESC LIMIT 30
        """)
        rows = await cur.fetchall()

    if not rows:
        return await message.answer("Foydalanuvchilar yo'q.")

    text = "👥 <b>Oxirgi 30 foydalanuvchi</b>\n\n"

    for uid, name, stars in rows:
        text += (
            f"• <a href='tg://user?id={uid}'>{name}</a>\n"
            f"ID: <code>{uid}</code> | ⭐ {stars}\n\n"
        )

    await message.answer(text)


@dp.message(F.text == "➕ Kanal qo'shish")
async def add_channel_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(Form.add_channel)
    await message.answer(
        "Kanal username'ini yuboring.\n"
        "Masalan: <code>@kanal_nomi</code>\n\n"
        "Bot kanal administratori bo'lishi shart."
    )


@dp.message(Form.add_channel)
async def add_channel_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channel = message.text.strip()

    if not channel.startswith("@"):
        return await message.answer("Kanal @username ko'rinishida bo'lsin.")

    try:
        chat = await bot.get_chat(channel)
        member = await bot.get_chat_member(chat.id, (await bot.get_me()).id)

        if member.status not in ["administrator", "creator"]:
            return await message.answer(
                "❌ Avval botni kanalga administrator qiling."
            )

        async with aiosqlite.connect(DB) as con:
            await con.execute(
                "INSERT OR IGNORE INTO channels(channel) VALUES(?)",
                (channel,)
            )
            await con.commit()

        await message.answer(
            f"✅ {chat.title} kanali qo'shildi.",
            reply_markup=admin_menu()
        )
        await state.clear()

    except Exception:
        await message.answer(
            "❌ Kanal topilmadi yoki botda kerakli ruxsat yo'q."
        )


@dp.message(F.text == "➖ Kanal o'chirish")
async def remove_channel_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(Form.remove_channel)
    await message.answer("O'chiriladigan kanal username'ini yuboring.")


@dp.message(Form.remove_channel)
async def remove_channel_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB) as con:
        await con.execute(
            "DELETE FROM channels WHERE channel=?",
            (message.text.strip(),)
        )
        await con.commit()

    await message.answer("✅ Kanal o'chirildi.", reply_markup=admin_menu())
    await state.clear()


@dp.message(F.text == "📋 Kanallar")
async def channels_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    channels = await get_channels()

    if not channels:
        return await message.answer("Kanallar mavjud emas.")

    text = "📋 <b>Kanallar ro'yxati</b>\n\n"
    for i, (channel,) in enumerate(channels, 1):
        text += f"{i}. {channel}\n"

    await message.answer(text)


# ============ KANALLARGA REKLAMA ============

@dp.message(F.text == "📢 Kanalga reklama")
async def ad_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channels = await get_channels()

    if not channels:
        return await message.answer(
            "❌ Avval kanal qo'shing."
        )

    await state.set_state(Form.advertisement)
    await message.answer(
        "📢 Kanallarga yuboriladigan reklama matnini yuboring.\n\n"
        "Reklama barcha qo'shilgan kanallarga yuboriladi."
    )


@dp.message(Form.advertisement)
async def ad_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    channels = await get_channels()

    if not channels:
        await state.clear()
        return await message.answer("Kanallar mavjud emas.")

    success = 0
    failed = 0

    for (channel,) in channels:
        try:
            await bot.copy_message(
                chat_id=channel,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            success += 1
        except Exception:
            logging.exception("Reklama yuborilmadi: %s", channel)
            failed += 1

    await state.clear()

    await message.answer(
        f"📢 <b>Reklama yuborish yakunlandi!</b>\n\n"
        f"✅ Yuborildi: {success} ta kanal\n"
        f"❌ Xatolik: {failed} ta kanal",
        reply_markup=admin_menu()
    )


# ============ REFERAL STARS SOZLASH ============

@dp.message(F.text == "⭐ Referal Stars sozlash")
async def reward_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    current = await get_reward()
    await state.set_state(Form.set_reward)

    await message.answer(
        f"Hozirgi referal mukofoti: ⭐ {current}\n\n"
        "Yangi Stars miqdorini yuboring."
    )


@dp.message(Form.set_reward)
async def reward_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not message.text.isdigit() or int(message.text) < 0:
        return await message.answer("Faqat musbat son yuboring.")

    async with aiosqlite.connect(DB) as con:
        await con.execute(
            "UPDATE settings SET value=? WHERE key='referral_reward'",
            (message.text,)
        )
        await con.commit()

    await state.clear()
    await message.answer(
        f"✅ Har bir referal uchun ⭐ {message.text} Stars belgilandi.",
        reply_markup=admin_menu()
    )


# ============ SOVG'A SO'ROVLARI ============

@dp.message(F.text == "🎁 Sovg'a so'rovlari")
async def pending_gifts(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB) as con:
        cur = await con.execute("""
            SELECT id,user_id,price FROM gifts
            WHERE status='pending'
            ORDER BY id DESC
        """)
        rows = await cur.fetchall()

    if not rows:
        return await message.answer("Kutilayotgan so'rovlar yo'q.")

    for gift_id, uid, price in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash",
                    callback_data=f"gift_ok_{gift_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=f"gift_no_{gift_id}"
                )
            ]
        ])

        await message.answer(
            f"🎁 So'rov #{gift_id}\n"
            f"Foydalanuvchi: <code>{uid}</code>\n"
            f"Narxi: ⭐ {price}",
            reply_markup=kb
        )


# ================ XABAR YUBORISH ================

@dp.message(F.text == "📨 Xabar yuborish")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(Form.support)
    await message.answer("Barcha foydalanuvchilarga yuboriladigan xabarni yuboring.")


@dp.message(Form.support)
async def broadcast_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB) as con:
        cur = await con.execute("SELECT user_id FROM users")
        users = await cur.fetchall()

    success = 0
    failed = 0

    for (uid,) in users:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            success += 1
        except Exception:
            failed += 1

    await state.clear()

    await message.answer(
        f"📨 Xabar yuborildi.\n"
        f"✅ {success}\n"
        f"❌ {failed}",
        reply_markup=admin_menu()
    )


# ================ BLOK NAZORATI =================

@dp.message()
async def unknown_message(message: Message):
    async with aiosqlite.connect(DB) as con:
        cur = await con.execute(
            "SELECT banned FROM users WHERE user_id=?",
            (message.from_user.id,)
        )
        row = await cur.fetchone()

    if row and row[0]:
        return

    await message.answer(
        "Menyudagi tugmalardan foydalaning.",
        reply_markup=admin_menu() if is_admin(message.from_user.id)
        else user_menu()
    )


async def main():
    await init_db()
    print("Bot ishga tushdi!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
