
import logging
import re
import sqlite3
import time
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters
)

TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"
ADMINS = {123456789}  # ADMIN TELEGRAM ID

logging.basicConfig(level=logging.INFO)

# ---------------- DB ----------------
db = sqlite3.connect("bot.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS chats(
    chat_id INTEGER PRIMARY KEY,
    village TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS users(
    tg_id INTEGER PRIMARY KEY,
    name TEXT,
    phone TEXT,
    role TEXT DEFAULT 'passenger',
    balance INTEGER DEFAULT 0,
    taken INTEGER DEFAULT 0,
    spent INTEGER DEFAULT 0
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS ads(
    msg_id INTEGER,
    chat_id INTEGER,
    tg_id INTEGER,
    seats INTEGER,
    created INTEGER
)""")

db.commit()

# ---------------- DATA ----------------
VILLAGES = [
    "qizilqosh","ishtxon","andoq","chaqar","moybuloq","payshanba",
    "sebustin","shor","kadan","andoq bozori","mayiz bozori","juma bozori"
]

RETURN_WORDS = [
    "qishloq","uyga","qaytaman","qaytamiz","qishloqqa","uyga ketaman","qishloq tomonga"
]

# ---------------- HELPERS ----------------
def normalize(t):
    return re.sub(r"[^a-zа-я0-9 ]","",t.lower())

def detect_village(text):
    t = normalize(text)
    for v in VILLAGES:
        if v in t:
            return v.title()
    return None

def get_chat_village(chat):
    cur.execute("SELECT village FROM chats WHERE chat_id=?",(chat.id,))
    r = cur.fetchone()
    if r:
        return r[0]
    for src in [chat.title or "", chat.description or ""]:
        v = detect_village(src)
        if v:
            cur.execute("INSERT OR REPLACE INTO chats VALUES(?,?)",(chat.id,v))
            db.commit()
            return v
    cur.execute("INSERT OR REPLACE INTO chats VALUES(?,?)",(chat.id,"Qizilqosh"))
    db.commit()
    return "Qizilqosh"

def is_passenger(text, base):
    t = normalize(text)
    if any(w in t for w in ["boraman","ketaman","taxi kerak","olib keting"]):
        return True
    if base.lower() in t and any(w in t for w in RETURN_WORDS):
        return True
    return False

def is_taxi(text):
    t = normalize(text)
    if any(w in t for w in ["olib ketaman","joy bor","yoʻlovchi olaman","boʻsh joy"]):
        return True
    if re.search(r"\d{2}:\d{2}",t) or re.search(r"\+?998\d{9}",t):
        return True
    return False

def seats_from_text(text):
    m = re.search(r"(\d+)\s*(kishi|joy)",text.lower())
    return int(m.group(1)) if m else 4

# ---------------- HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    cur.execute("INSERT OR IGNORE INTO users(tg_id,name,role) VALUES(?,?,?)",
                (u.id,u.full_name,"taxi"))
    db.commit()
    await update.message.reply_text("🚖 Taxi sifatida ro‘yxatdan o‘tdingiz")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT balance,taken,spent FROM users WHERE tg_id=?",(update.effective_user.id,))
    r = cur.fetchone()
    if not r:
        await update.message.reply_text("Ro‘yxatdan o‘tilmagan")
        return
    await update.message.reply_text(
        f"💰 Balans: {r[0]} so‘m\n🚕 Olingan: {r[1]}\n💸 Jami: {r[2]}"
    )

async def topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        return
    uid = int(context.args[0])
    sm = int(context.args[1])
    cur.execute("UPDATE users SET balance=balance+? WHERE tg_id=?",(sm,uid))
    db.commit()
    await update.message.reply_text("✅ To‘ldirildi")

async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    base = get_chat_village(msg.chat)
    text = msg.text

    if is_passenger(text, base):
        frm = detect_village(text) or "Noma’lum"
        to = base
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🧍‍♂️ MEN OLIB KETAMAN",callback_data="take:"+str(msg.from_user.id))]])
        await msg.reply_text(f"🚕 YO‘LOVCHI\n{frm} → {to}",reply_markup=kb)

    elif is_taxi(text):
        cur.execute("SELECT balance FROM users WHERE tg_id=?",(msg.from_user.id,))
        r = cur.fetchone()
        if not r or r[0] < 1000:
            return
        seats = seats_from_text(text)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚕 MEN KETAMAN",callback_data=f"go:{msg.from_user.id}")]])
        await msg.reply_text(
            f"🚖 TAXI\n{base} → ?\n🚕 Bo‘sh joylar: {seats} ta",
            reply_markup=kb
        )
        cur.execute("INSERT INTO ads VALUES(?,?,?,?,?)",
                    (msg.message_id,msg.chat.id,msg.from_user.id,seats,int(time.time())))
        db.commit()

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, uid = q.data.split(":")
    uid = int(uid)

    if action == "go":
        cur.execute("SELECT balance FROM users WHERE tg_id=?",(q.from_user.id,))
        if cur.fetchone()[0] < 1000:
            return
        cur.execute("UPDATE users SET balance=balance-1000, taken=taken+1, spent=spent+1000 WHERE tg_id=?",
                    (q.from_user.id,))
        db.commit()
        await context.bot.send_message(uid,"🚕 Taxi siz bilan bog‘lanmoqda")
        await q.edit_message_reply_markup(None)

    if action == "take":
        await context.bot.send_message(uid,"🧍‍♂️ Yo‘lovchi siz bilan bog‘lanmoqda")
        await q.edit_message_reply_markup(None)

# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("balans",balance))
    app.add_handler(CommandHandler("toldir",topup))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, group_message))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()

if __name__ == "__main__":
    main()
