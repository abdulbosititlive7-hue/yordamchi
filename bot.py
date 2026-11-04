
import asyncio
import logging
import os
import sqlite3
import html
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, LabeledPrice
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# =============== SOZLAMALAR ===============

TOKEN = os.getenv("BOT_TOKEN", "9269203317:AAFCoXtE8EHT9IR5HGhLtFPzG_qkyf6sFDo")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5200398952"))
PORT = int(os.getenv("PORT", "10000"))

DB = "bot.sqlite3"
REF_REWARD = 2
GIFTS = [15, 25, 50, 100]

REQUIRED_CHANNELS = [
    # "@kanal_nomi",
]

logging.basicConfig(level=logging.INFO)

if not TOKEN:
    raise RuntimeError("BOT_TOKEN Render Environment ichida yo'q!")

bot = Bot(TOKEN, default=DefaultBotProperties(
    parse_mode=ParseMode.HTML
))
dp = Dispatcher()


# =============== DATABASE ===============

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        name TEXT,
        username TEXT,
        balance INTEGER DEFAULT 0,
        referrer INTEGER DEFAULT NULL,
        banned INTEGER DEFAULT 0,
        joined TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS referrals(
        user_id INTEGER PRIMARY KEY,
        referrer INTEGER,
        reward INTEGER DEFAULT 2
    );

    CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        description TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS contests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        prize TEXT,
        kind TEXT,
        status TEXT DEFAULT 'active'
    );

    CREATE TABLE IF NOT EXISTS participants(
        contest_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY(contest_id,user_id)
    );

    CREATE TABLE IF NOT EXISTS votes(
        contest_id INTEGER,
        voter_id INTEGER,
        participant_id INTEGER,
        PRIMARY KEY(contest_id,voter_id)
    );

    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        status TEXT DEFAULT 'pending',
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS payments(
        charge_id TEXT PRIMARY KEY,
        user_id INTEGER,
        amount INTEGER
    );

    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    con.commit()
    con.close()


def setting(key, default):
    con = db()
    row = con.execute(
        "SELECT value FROM settings WHERE key=?", (key,)
    ).fetchone()
    con.close()
    return row["value"] if row else str(default)


def save_setting(key, value):
    con = db()
    con.execute("""
        INSERT INTO settings(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, str(value)))
    con.commit()
    con.close()


def register(user, ref=None):
    con = db()
    exists = con.execute(
        "SELECT id FROM users WHERE id=?", (user.id,)
    ).fetchone()

    if not exists:
        con.execute("""
            INSERT INTO users(id,name,username,referrer)
            VALUES(?,?,?,?)
        """, (
            user.id, user.full_name,
            user.username or "", ref
        ))

    con.commit()
    con.close()


def is_admin(uid):
    return uid == ADMIN_ID


def add_balance(uid, amount, description):
    con = db()
    con.execute(
        "UPDATE users SET balance=balance+? WHERE id=?",
        (amount, uid)
    )
    con.execute("""
        INSERT INTO transactions(user_id,amount,description)
        VALUES(?,?,?)
    """, (uid, amount, description))
    con.commit()
    con.close()


def balance(uid):
    con = db()
    row = con.execute(
        "SELECT balance FROM users WHERE id=?", (uid,)
    ).fetchone()
    con.close()
    return row["balance"] if row else 0


def banned(uid):
    con = db()
    row = con.execute(
        "SELECT banned FROM users WHERE id=?", (uid,)
    ).fetchone()
    con.close()
    return bool(row and row["banned"])


# =============== KEYBOARDS ===============

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎉 Konkurs", callback_data="contest"),
            InlineKeyboardButton(text="⚔️ Battle", callback_data="battle")
        ],
        [
            InlineKeyboardButton(text="👥 Referal", callback_data="ref"),
            InlineKeyboardButton(text="⭐ Hisobim", callback_data="profile")
        ],
        [
            InlineKeyboardButton(text="🎁 Gift yechish", callback_data="gift"),
            InlineKeyboardButton(text="📦 Buyurtmalarim", callback_data="orders")
        ],
        [
            InlineKeyboardButton(text="🏆 Reyting", callback_data="rating"),
            InlineKeyboardButton(text="📜 Tarix", callback_data="history")
        ],
        [
            InlineKeyboardButton(text="💬 Adminga murojaat", callback_data="support"),
            InlineKeyboardButton(text="📖 Qo'llanma", callback_data="guide")
        ]
    ])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="astats"),
            InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="ausers")
        ],
        [
            InlineKeyboardButton(text="➕ Stars qo'shish", callback_data="aadd"),
            InlineKeyboardButton(text="➖ Stars ayirish", callback_data="asub")
        ],
        [
            InlineKeyboardButton(text="🎉 Konkurs yaratish", callback_data="anewcontest"),
            InlineKeyboardButton(text="⚔️ Battle yaratish", callback_data="anewbattle")
        ],
        [
            InlineKeyboardButton(text="📦 Buyurtmalar", callback_data="aorders"),
            InlineKeyboardButton(text="📢 Reklama", callback_data="abroadcast")
        ],
        [
            InlineKeyboardButton(text="⚙️ Referal bonusi", callback_data="areward"),
            InlineKeyboardButton(text="🚫 Bloklash", callback_data="aban")
        ],
        [
            InlineKeyboardButton(text="🔓 Blokdan chiqarish", callback_data="aunban"),
            InlineKeyboardButton(text="📋 Kanallar", callback_data="achannels")
        ]
    ])


def gifts_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🎁 {x} Stars",
            callback_data=f"gift:{x}"
        )]
        for x in GIFTS
    ] + [[InlineKeyboardButton(
        text="❌ Bekor qilish",
        callback_data="home"
    )]])


async def subscribed(uid):
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, uid)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True


def subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📢 {ch}",
            url=f"https://t.me/{ch.lstrip('@')}"
        )] for ch in REQUIRED_CHANNELS
    ] + [[InlineKeyboardButton(
        text="✅ Tekshirish",
        callback_data="checksub"
    )]])


# =============== START ===============

async def welcome(message):
    await message.answer(
        "👋 <b>Botimizga xush kelibsiz!</b>\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_menu()
    )


@dp.message(CommandStart())
async def start(message: Message, command: CommandObject):
    ref = None

    if command.args and command.args.isdigit():
        candidate = int(command.args)
        if candidate != message.from_user.id:
            ref = candidate

    con = db()
    exists = con.execute(
        "SELECT id FROM users WHERE id=?",
        (message.from_user.id,)
    ).fetchone()
    con.close()

    register(message.from_user, ref)

    if banned(message.from_user.id):
        await message.answer("🚫 Hisobingiz bloklangan.")
        return

    if not exists and ref:
        if not REQUIRED_CHANNELS or await subscribed(message.from_user.id):
            con = db()
            inviter = con.execute(
                "SELECT id FROM users WHERE id=?", (ref,)
            ).fetchone()

            if inviter:
                reward = int(setting("ref_reward", REF_REWARD))
                con.execute("""
                    INSERT OR IGNORE INTO referrals(user_id,referrer,reward)
                    VALUES(?,?,?)
                """, (message.from_user.id, ref, reward))

                if con.execute(
                    "SELECT changes()"
                ).fetchone()[0]:
                    con.execute(
                        "UPDATE users SET balance=balance+? WHERE id=?",
                        (reward, ref)
                    )
                    con.execute("""
                        INSERT INTO transactions(user_id,amount,description)
                        VALUES(?,?,?)
                    """, (ref, reward, "Referal bonusi"))

            con.commit()
            con.close()

    if REQUIRED_CHANNELS and not await subscribed(message.from_user.id):
        await message.answer(
            "Botdan foydalanish uchun kanallarga obuna bo'ling:",
            reply_markup=subscription_keyboard()
        )
        return

    await welcome(message)


@dp.callback_query(F.data == "checksub")
async def check_sub(call: CallbackQuery):
    if await subscribed(call.from_user.id):
        await call.message.edit_text("✅ Obuna tasdiqlandi!")
        await welcome(call.message)
    else:
        await call.answer("Avval barcha kanallarga obuna bo'ling!", show_alert=True)


# =============== USER PANEL ===============

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.edit_text(
        "🏠 <b>Asosiy menyu</b>",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    uid = call.from_user.id
    con = db()
    refs = con.execute(
        "SELECT COUNT(*) n FROM referrals WHERE referrer=?", (uid,)
    ).fetchone()["n"]
    con.close()

    await call.message.edit_text(
        f"👤 <b>Profilingiz</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"⭐ Balans: {balance(uid)}\n"
        f"👥 Referallar: {refs}",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "ref")
async def referral(call: CallbackQuery):
    uid = call.from_user.id
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={uid}"

    con = db()
    count = con.execute(
        "SELECT COUNT(*) n FROM referrals WHERE referrer=?", (uid,)
    ).fetchone()["n"]
    con.close()

    reward = setting("ref_reward", REF_REWARD)

    await call.message.edit_text(
        "👥 <b>Referal tizimi</b>\n\n"
        f"🔗 Havolangiz:\n<code>{link}</code>\n\n"
        f"👤 Taklif qilinganlar: {count}\n"
        f"⭐ Har bir yangi referal uchun: {reward} bonus Stars\n\n"
        "Havolani do'stlaringizga yuboring!",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "gift")
async def gift(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 <b>Gift yechish</b>\n\n"
        f"Balansingiz: {balance(call.from_user.id)}\n"
        "Kerakli miqdorni tanlang:",
        reply_markup=gifts_keyboard()
    )


@dp.callback_query(F.data.startswith("gift:"))
async def gift_request(call: CallbackQuery):
    amount = int(call.data.split(":")[1])
    uid = call.from_user.id

    if amount not in GIFTS:
        await call.answer("Noto'g'ri tanlov!", show_alert=True)
        return

    if balance(uid) < amount:
        await call.answer("Balansingiz yetarli emas!", show_alert=True)
        return

    con = db()
    cur = con.execute(
        "INSERT INTO orders(user_id,amount) VALUES(?,?)",
        (uid, amount)
    )
    order_id = cur.lastrowid
    con.commit()
    con.close()

    await call.message.edit_text(
        f"✅ Buyurtma #{order_id} yuborildi.\n"
        "Admin tekshirganidan keyin javob beriladi.",
        reply_markup=main_menu()
    )

    await bot.send_message(
        ADMIN_ID,
        f"🎁 <b>Yangi gift buyurtmasi</b>\n"
        f"ID: {order_id}\n"
        f"Foydalanuvchi: <code>{uid}</code>\n"
        f"Miqdor: {amount}\n\n"
        f"/approve {order_id}\n/reject {order_id}"
    )


@dp.callback_query(F.data == "orders")
async def my_orders(call: CallbackQuery):
    con = db()
    rows = con.execute(
        "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (call.from_user.id,)
    ).fetchall()
    con.close()

    if not rows:
        text = "📦 Sizda hali buyurtmalar yo'q."
    else:
        text = "📦 <b>Buyurtmalaringiz</b>\n\n"
        for r in rows:
            text += (
                f"#{r['id']} — {r['amount']} Stars — "
                f"{r['status']}\n"
            )

    await call.message.edit_text(text, reply_markup=main_menu())


@dp.callback_query(F.data == "rating")
async def rating(call: CallbackQuery):
    con = db()
    rows = con.execute("""
        SELECT id,name,balance FROM users
        ORDER BY balance DESC LIMIT 10
    """).fetchall()
    con.close()

    text = "🏆 <b>TOP 10 reyting</b>\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {html.escape(r['name'] or str(r['id']))} — {r['balance']} ⭐\n"

    await call.message.edit_text(text, reply_markup=main_menu())


@dp.callback_query(F.data == "history")
async def history(call: CallbackQuery):
    con = db()
    rows = con.execute("""
        SELECT amount,description,created FROM transactions
        WHERE user_id=? ORDER BY id DESC LIMIT 15
    """, (call.from_user.id,)).fetchall()
    con.close()

    text = "📜 <b>Tranzaksiyalar tarixi</b>\n\n"
    if not rows:
        text += "Hozircha tarix mavjud emas."
    for r in rows:
        text += f"{r['amount']:+} ⭐ | {html.escape(r['description'])}\n"

    await call.message.edit_text(text, reply_markup=main_menu())


@dp.callback_query(F.data == "guide")
async def guide(call: CallbackQuery):
    await call.message.edit_text(
        "📖 <b>Qo'llanma</b>\n\n"
        "1. Referal havolangizni do'stlaringizga yuboring.\n"
        "2. Yangi foydalanuvchi orqali bonus oling.\n"
        "3. Konkurslarda qatnashing.\n"
        "4. Battle orqali ovoz yig'ing.\n"
        "5. Gift bo'limidan buyurtma yuboring.\n\n"
        "⚠️ Botdagi bonus Stars ichki hisob birligi hisoblanadi.",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "support")
async def support(call: CallbackQuery):
    await call.message.answer(
        "💬 Adminga xabar yuborish uchun matningizni yozing."
    )
    await call.answer()


@dp.message(F.text, ~F.text.startswith("/"))
async def support_message(message: Message):
    if is_admin(message.from_user.id):
        if message.reply_to_message:
            try:
                uid = int(message.reply_to_message.text.split("ID: ")[1].split()[0])
                await bot.send_message(uid, message.text)
                await message.answer("✅ Xabar yuborildi.")
            except Exception:
                pass
        return

    await bot.send_message(
        ADMIN_ID,
        f"💬 <b>Yangi murojaat</b>\n"
        f"ID: <code>{message.from_user.id}</code>\n"
        f"Ism: {html.escape(message.from_user.full_name)}\n\n"
        f"{html.escape(message.text)}"
    )
    await message.answer("✅ Xabaringiz adminga yuborildi.")


# =============== CONTEST / BATTLE ===============

def active_contest(kind=None):
    con = db()
    if kind:
        row = con.execute("""
            SELECT * FROM contests
            WHERE status='active' AND kind=?
            ORDER BY id DESC LIMIT 1
        """, (kind,)).fetchone()
    else:
        row = con.execute("""
            SELECT * FROM contests WHERE status='active'
            ORDER BY id DESC LIMIT 1
        """).fetchone()
    con.close()
    return row


async def show_competition(call, kind):
    contest = active_contest(kind)
    if not contest:
        await call.message.edit_text(
            "Hozircha faol tadbir yo'q.",
            reply_markup=main_menu()
        )
        return

    con = db()
    rows = con.execute("""
        SELECT p.user_id, u.name, COUNT(v.voter_id) votes
        FROM participants p
        JOIN users u ON u.id=p.user_id
        LEFT JOIN votes v ON v.contest_id=p.contest_id
          AND v.participant_id=p.user_id
        WHERE p.contest_id=?
        GROUP BY p.user_id ORDER BY votes DESC
    """, (contest["id"],)).fetchall()
    con.close()

    text = (
        f"{'⚔️' if kind == 'battle' else '🎉'} "
        f"<b>{html.escape(contest['title'])}</b>\n"
        f"🎁 Sovrin: {html.escape(contest['prize'])}\n\n"
    )

    for i, r in enumerate(rows, 1):
        text += f"{i}. {html.escape(r['name'] or str(r['user_id']))} — {r['votes']} ovoz\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Qatnashish", callback_data=f"join:{contest['id']}")],
        [InlineKeyboardButton(text="🔙 Menyu", callback_data="home")]
    ])

    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "contest")
async def contest_button(call: CallbackQuery):
    await show_competition(call, "contest")


@dp.callback_query(F.data == "battle")
async def battle_button(call: CallbackQuery):
    await show_competition(call, "battle")


@dp.callback_query(F.data.startswith("join:"))
async def join(call: CallbackQuery):
    cid = int(call.data.split(":")[1])
    con = db()
    contest = con.execute(
        "SELECT * FROM contests WHERE id=? AND status='active'",
        (cid,)
    ).fetchone()

    if not contest:
        con.close()
        await call.answer("Tadbir yopilgan!", show_alert=True)
        return

    con.execute(
        "INSERT OR IGNORE INTO participants(contest_id,user_id) VALUES(?,?)",
        (cid, call.from_user.id)
    )
    con.commit()
    con.close()

    await call.answer("Siz qatnashchilar ro'yxatidasiz!", show_alert=True)


@dp.message(Command("vote"))
async def vote(message: Message, command: CommandObject):
    contest = active_contest()
    if not contest:
        await message.answer("Faol konkurs yoki battle yo'q.")
        return

    if not command.args or not command.args.isdigit():
        await message.answer("Foydalanish: /vote USER_ID")
        return

    target = int(command.args)
    if target == message.from_user.id:
        await message.answer("O'zingizga ovoz bera olmaysiz.")
        return

    con = db()
    participant = con.execute("""
        SELECT 1 FROM participants WHERE contest_id=? AND user_id=?
    """, (contest["id"], target)).fetchone()

    if not participant:
        con.close()
        await message.answer("Bu foydalanuvchi qatnashchi emas.")
        return

    try:
        con.execute("""
            INSERT INTO votes(contest_id,voter_id,participant_id)
            VALUES(?,?,?)
        """, (contest["id"], message.from_user.id, target))
        con.commit()
        await message.answer("✅ Ovozingiz qabul qilindi!")
    except sqlite3.IntegrityError:
        await message.answer("Siz allaqachon ovoz bergansiz.")
    finally:
        con.close()


# =============== STARS PAYMENT ===============

@dp.message(Command("buy"))
async def buy(message: Message, command: CommandObject):
    if not command.args or not command.args.isdigit():
        await message.answer("Foydalanish: /buy 10")
        return

    amount = int(command.args)
    if not 1 <= amount <= 10000:
        await message.answer("1–10000 oralig'ida kiriting.")
        return

    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Stars xaridi",
        description=f"{amount} ta Telegram Stars",
        payload=f"purchase:{message.from_user.id}:{amount}",
        currency="XTR",
        prices=[LabeledPrice(label="Telegram Stars", amount=amount)]
    )


@dp.pre_checkout_query()
async def checkout(query):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def payment(message: Message):
    p = message.successful_payment
    parts = p.invoice_payload.split(":")
    if len(parts) != 3 or parts[0] != "purchase":
        return

    uid, amount = int(parts[1]), int(parts[2])
    if uid != message.from_user.id:
        return

    con = db()
    try:
        con.execute("""
            INSERT INTO payments(charge_id,user_id,amount)
            VALUES(?,?,?)
        """, (p.telegram_payment_charge_id, uid, amount))
        con.execute(
            "UPDATE users SET balance=balance+? WHERE id=?",
            (amount, uid)
        )
        con.execute("""
            INSERT INTO transactions(user_id,amount,description)
            VALUES(?,?,?)
        """, (uid, amount, "Telegram Stars xaridi"))
        con.commit()
        await message.answer(f"✅ {amount} bonus Stars hisobingizga qo'shildi.")
    except sqlite3.IntegrityError:
        await message.answer("Bu to'lov avval qayd etilgan.")
    finally:
        con.close()


# =============== ADMIN PANEL ===============

@dp.message(Command("admin"))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛠 <b>ADMIN PANEL</b>", reply_markup=admin_menu())


@dp.callback_query(F.data == "astats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    con = db()
    users = con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    refs = con.execute("SELECT COUNT(*) n FROM referrals").fetchone()["n"]
    votes = con.execute("SELECT COUNT(*) n FROM votes").fetchone()["n"]
    orders = con.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
    con.close()

    await call.message.answer(
        f"📊 <b>Statistika</b>\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"👤 Referallar: {refs}\n"
        f"🗳 Ovozlar: {votes}\n"
        f"📦 Buyurtmalar: {orders}"
    )


@dp.callback_query(F.data == "ausers")
async def admin_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    con = db()
    rows = con.execute(
        "SELECT id,name,balance FROM users ORDER BY joined DESC LIMIT 30"
    ).fetchall()
    con.close()

    text = "👥 <b>Oxirgi foydalanuvchilar</b>\n\n"
    for r in rows:
        text += f"{html.escape(r['name'] or '')} — <code>{r['id']}</code> — {r['balance']} ⭐\n"

    await call.message.answer(text)


@dp.callback_query(F.data == "aorders")
async def admin_orders(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    con = db()
    rows = con.execute(
        "SELECT * FROM orders WHERE status='pending' ORDER BY id"
    ).fetchall()
    con.close()

    if not rows:
        await call.message.answer("Kutilayotgan buyurtma yo'q.")
        return

    for r in rows:
        await call.message.answer(
            f"📦 Buyurtma #{r['id']}\n"
            f"ID: {r['user_id']}\n"
            f"Miqdor: {r['amount']}\n"
            f"/approve {r['id']} yoki /reject {r['id']}"
        )


@dp.message(Command("approve"))
async def approve(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    if not command.args or not command.args.isdigit():
        return

    oid = int(command.args)
    con = db()
    order = con.execute(
        "SELECT * FROM orders WHERE id=? AND status='pending'",
        (oid,)
    ).fetchone()

    if not order:
        con.close()
        await message.answer("Buyurtma topilmadi.")
        return

    if balance(order["user_id"]) < order["amount"]:
        con.close()
        await message.answer("Foydalanuvchi balansi yetarli emas.")
        return

    con.execute(
        "UPDATE users SET balance=balance-? WHERE id=?",
        (order["amount"], order["user_id"])
    )
    con.execute(
        "UPDATE orders SET status='approved' WHERE id=?", (oid,)
    )
    con.execute("""
        INSERT INTO transactions(user_id,amount,description)
        VALUES(?,?,?)
    """, (order["user_id"], -order["amount"], f"Gift #{oid}"))
    con.commit()
    con.close()

    await bot.send_message(
        order["user_id"],
        f"✅ Buyurtmangiz #{oid} tasdiqlandi."
    )
    await message.answer("Buyurtma tasdiqlandi.")


@dp.message(Command("reject"))
async def reject(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    if not command.args or not command.args.isdigit():
        return

    oid = int(command.args)
    con = db()
    order = con.execute(
        "SELECT * FROM orders WHERE id=? AND status='pending'",
        (oid,)
    ).fetchone()

    if not order:
        con.close()
        await message.answer("Buyurtma topilmadi.")
        return

    con.execute(
        "UPDATE orders SET status='rejected' WHERE id=?", (oid,)
    )
    con.commit()
    con.close()

    await bot.send_message(
        order["user_id"],
        f"❌ Buyurtma #{oid} rad etildi. Balansingiz saqlab qolindi."
    )
    await message.answer("Buyurtma rad etildi.")


# Admin matnli amallari:
/add USER_ID AMOUNT
/sub USER_ID AMOUNT
/ban USER_ID
/unban USER_ID
/reward AMOUNT
/newcontest NOMI | SOVRIN
/newbattle NOMI | SOVRIN
/close
/broadcast MATN
/channel @KANAL
/removechannel @KANAL


@dp.message(Command("add"))
async def admin_add(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    try:
        uid, amount = map(int, command.args.split())
        add_balance(uid, amount, "Admin tomonidan qo'shildi")
        await message.answer("✅ Balans oshirildi.")
        await bot.send_message(uid, f"⭐ Hisobingizga {amount} bonus Stars qo'shildi.")
    except Exception:
        await message.answer("/add USER_ID AMOUNT")


@dp.message(Command("sub"))
async def admin_sub(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    try:
        uid, amount = map(int, command.args.split())
        if amount <= 0 or balance(uid) < amount:
            await message.answer("Noto'g'ri miqdor yoki balans yetarli emas.")
            return
        add_balance(uid, -amount, "Admin tomonidan ayirildi")
        await message.answer("✅ Balans kamaytirildi.")
    except Exception:
        await message.answer("/sub USER_ID AMOUNT")


@dp.message(Command("ban"))
async def ban_user(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(command.args)
        con = db()
        con.execute("UPDATE users SET banned=1 WHERE id=?", (uid,))
        con.commit()
        con.close()
        await message.answer("🚫 Foydalanuvchi bloklandi.")
    except Exception:
        await message.answer("/ban USER_ID")


@dp.message(Command("unban"))
async def unban_user(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(command.args)
        con = db()
        con.execute("UPDATE users SET banned=0 WHERE id=?", (uid,))
        con.commit()
        con.close()
        await message.answer("✅ Blok olib tashlandi.")
    except Exception:
        await message.answer("/unban USER_ID")


@dp.message(Command("reward"))
async def reward(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    try:
        amount = int(command.args)
        if amount < 0:
            raise ValueError
        save_setting("ref_reward", amount)
        await message.answer(f"✅ Referal bonusi {amount} ga o'zgartirildi.")
    except Exception:
        await message.answer("/reward 2")


@dp.message(Command("newcontest"))
@dp.message(Command("newbattle"))
async def create_competition(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return

    kind = "battle" if message.text.startswith("/newbattle") else "contest"

    try:
        title, prize = command.args.split("|", 1)
        con = db()
        con.execute(
            "UPDATE contests SET status='closed' WHERE status='active' AND kind=?",
            (kind,)
        )
        con.execute(
            "INSERT INTO contests(title,prize,kind) VALUES(?,?,?)",
            (title.strip(), prize.strip(), kind)
        )
        con.commit()
        con.close()
        await message.answer("✅ Yangi tadbir yaratildi.")
    except Exception:
        await message.answer(
            "/newcontest Nomi | Sovrin\n/newbattle Nomi | Sovrin"
        )


@dp.message(Command("close"))
async def close_competition(message: Message):
    if not is_admin(message.from_user.id):
        return
    contest = active_contest()
    if not contest:
        await message.answer("Faol tadbir yo'q.")
        return

    con = db()
    winner = con.execute("""
        SELECT p.user_id, COUNT(v.voter_id) votes
        FROM participants p
        LEFT JOIN votes v ON v.contest_id=p.contest_id
          AND v.participant_id=p.user_id
        WHERE p.contest_id=?
        GROUP BY p.user_id ORDER BY votes DESC LIMIT 1
    """, (contest["id"],)).fetchone()

    con.execute(
        "UPDATE contests SET status='closed' WHERE id=?",
        (contest["id"],)
    )
    con.commit()
    con.close()

    if winner:
        await message.answer(
            f"🏆 G'olib: <code>{winner['user_id']}</code>\n"
            f"🗳 Ovozlar: {winner['votes']}\n"
            f"🎁 Sovrin: {html.escape(contest['prize'])}"
        )
    else:
        await message.answer("Tadbir yopildi, qatnashchilar yo'q.")


@dp.message(Command("broadcast"))
async def broadcast(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    if not command.args:
        await message.answer("/broadcast Xabar matni")
        return

    con = db()
    users = con.execute("SELECT id FROM users WHERE banned=0").fetchall()
    con.close()

    sent = 0
    for user in users:
        try:
            await bot.send_message(user["id"], command.args)
            sent += 1
        except Exception:
            pass

    await message.answer(f"✅ {sent} ta foydalanuvchiga yuborildi.")


@dp.message(Command("channel"))
async def add_channel(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    channel = (command.args or "").strip()
    if not channel.startswith("@"):
        await message.answer("/channel @kanal")
        return

    channels = REQUIRED_CHANNELS.copy()
    if channel not in channels:
        channels.append(channel)
    REQUIRED_CHANNELS.clear()
    REQUIRED_CHANNELS.extend(channels)
    await message.answer(
        "Kanal qo'shildi. Doimiy saqlash uchun Render Environment'dagi "
        "REQUIRED_CHANNELS qiymatini ham yangilang."
    )


@dp.message(Command("removechannel"))
async def remove_channel(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    channel = (command.args or "").strip()
    if channel in REQUIRED_CHANNELS:
        REQUIRED_CHANNELS.remove(channel)
    await message.answer("Kanal ro'yxatdan olib tashlandi.")


@dp.message(Command("channels"))
async def channels(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "Majburiy kanallar:\n" +
        ("\n".join(REQUIRED_CHANNELS) or "Hozircha yo'q")
    )


# =============== ADMIN INLINE CALLBACKS ===============

@dp.callback_query(F.data.in_({
    "aadd", "asub", "anewcontest", "anewbattle",
    "abroadcast", "areward", "aban", "aunban", "achannels"
}))
async def admin_help(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return

    instructions = {
        "aadd": "/add USER_ID AMOUNT",
        "asub": "/sub USER_ID AMOUNT",
        "anewcontest": "/newcontest Nomi | Sovrin",
        "anewbattle": "/newbattle Nomi | Sovrin",
        "abroadcast": "/broadcast Xabar",
        "areward": "/reward 2",
        "aban": "/ban USER_ID",
        "aunban": "/unban USER_ID",
        "achannels": "/channel @kanal yoki /removechannel @kanal"
    }
    await call.message.answer(instructions[call.data])


# =============== HEALTH SERVER ===============

async def health(request):
    return web.json_response({"status": "running"})


async def main():
    init_db()

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    logging.info("Bot ishga tushdi!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
