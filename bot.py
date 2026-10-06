import os
import json
import requests
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============ CONFIG ============
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "0"))

GROUP_LINK   = os.environ.get("GROUP_LINK", "https://t.me/+xxxxxxxxxx")
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/+yyyyyyyyyy")
GROUP_ID     = int(os.environ.get("GROUP_ID", "0"))
CHANNEL_ID   = int(os.environ.get("CHANNEL_ID", "0"))

ADMIN_IDS = [
    int(x.strip())
    for x in os.environ.get("ADMIN_ID", "0").split(",")
    if x.strip().isdigit()
]

TOOLS = {
    "tg":     {"name": "✈️ TG Info",         "url": "https://tg-to-info.asurpapa.workers.dev/api?key=OSINTBOT&query={q}",       "prompt": "Telegram username ya ID"},
    "num":    {"name": "📱 Number Info",     "url": "https://num-to-info.asurpapa.workers.dev/api?key=OSINTBOT&number={q}",     "prompt": "10 digit mobile number"},
    "aadhar": {"name": "🆔 Aadhaar Info",    "url": "https://aadhaar.asurpapa.workers.dev/api?key=OSINTBOT&aadhaar={q}",        "prompt": "12 digit Aadhaar number"},
    "family": {"name": "👨‍👩‍👧 Aadhaar Family", "url": "https://aadhaar-family.asurpapa.workers.dev/api?key=OSINTBOT&aadhaar={q}", "prompt": "Aadhaar number"},
}

HIDE_KEYS = {"credit", "developer", "footer", "contact", "powered_by"}

WELCOME_TEXT = (
    "🕵️ *WELCOME TO INSOMNIAC X-TRACE*\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "_Your gateway to OSINT & public-source intelligence._\n\n"
    "🔎 Username & handle discovery\n"
    "🌐 Public profile lookup\n"
    "🧩 Digital footprint analysis\n"
    "📡 Cross-platform searching\n"
    "🗂️ Open-source intelligence tools\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "⚡ _Search smart. Stay anonymous. Think deeper._"
)

# ============ STORAGE ============
user_results = {}
known_users = set()
verified_users = set()   # chat_id jinhone verify kiya
dm_users = set()         # jinhone DM me /start kiya


def clean_response(data):
    if isinstance(data, dict):
        return {k: clean_response(v) for k, v in data.items() if k.lower() not in HIDE_KEYS}
    if isinstance(data, list):
        return [clean_response(i) for i in data]
    return data


def pretty_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False)


async def log_to_channel(context, text):
    if LOG_CHANNEL_ID == 0:
        return
    try:
        if len(text) > 4000:
            text = text[:4000] + "\n\n...(truncated)"
        await context.bot.send_message(LOG_CHANNEL_ID, text, parse_mode=None)
    except Exception as e:
        print(f"Log channel error: {e}")


# ============ FORCE JOIN ============
async def is_user_joined(context, user_id):
    try:
        if GROUP_ID != 0:
            member = await context.bot.get_chat_member(GROUP_ID, user_id)
            if member.status in ("left", "kicked"):
                return False
        if CHANNEL_ID != 0:
            member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
            if member.status in ("left", "kicked"):
                return False
        return True
    except Exception as e:
        print(f"Join check error: {e}")
        return True


def join_menu():
    """Sirf join + verify buttons"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Channel Join Kar", url=CHANNEL_LINK)],
        [InlineKeyboardButton("👥 Group Join Kar", url=GROUP_LINK)],
        [InlineKeyboardButton("✅ Verify Kar", callback_data="verify_join")],
    ])


async def send_join_msg(update: Update):
    text = (
        "🚫 *Pehle Join Karo!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Bot use karne ke liye pehle ye join karo:\n\n"
        "1️⃣ Channel join kar\n"
        "2️⃣ Group join kar\n"
        "3️⃣ Phir *Verify* button dabaye\n\n"
        "✅ Verify hone ke baad bot start ho jayega."
    )
    await update.message.reply_text(
        text,
        reply_markup=join_menu(),
        parse_mode="Markdown",
    )


async def send_join_msg_callback(q):
    """Callback query ke liye join msg (edit karke)"""
    text = (
        "🚫 *Pehle Join Karo!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Bot use karne ke liye pehle ye join karo:\n\n"
        "1️⃣ Channel join kar\n"
        "2️⃣ Group join kar\n"
        "3️⃣ Phir *Verify* button dabaye\n\n"
        "✅ Verify hone ke baad bot start ho jayega."
    )
    await q.edit_message_text(
        text,
        reply_markup=join_menu(),
        parse_mode="Markdown",
    )


# ============ BOT COMMANDS SETUP ============
async def set_commands(app):
    commands = [
        BotCommand("start",     "🚀 Bot Start Kare"),
        BotCommand("join",      "🔗 Group & Channel Join Kare"),
        BotCommand("verify",    "✅ Join Verify Kare"),
        BotCommand("tools",     "🧰 Saare OSINT Tools Dekhe"),
        BotCommand("tg",        "✈️ TG Info Search"),
        BotCommand("num",       "📱 Number Info Search"),
        BotCommand("aadhar",    "🆔 Aadhaar Info Search"),
        BotCommand("family",    "👨‍👩‍👧 Aadhaar Family Search"),
        BotCommand("myid",      "🆔 Apna Telegram ID"),
        BotCommand("stats",     "📊 Bot Statistics"),
        BotCommand("help",      "❓ Help & Guide"),
        BotCommand("about",     "ℹ️ Bot Ke Baare Me"),
        BotCommand("broadcast", "📢 [Admin] Broadcast"),
    ]
    await app.bot.set_my_commands(commands)


# ============ BASIC COMMANDS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    chat_type = update.effective_chat.type

    # ---- GROUP/SUPERGROUP me start bheja toh DM me bhej ----
    if chat_type in ("group", "supergroup"):
        bot_username = context.bot.username
        await update.message.reply_text(
            f"👋 *{user.first_name}*, group me search nahi hota!\n\n"
            f"👇 Pehle bot ko DM me start kar:\n"
            f"➡️ @{bot_username}\n\n"
            f"Wahan pe search kar sakta hai.",
            parse_mode="Markdown",
        )
        return

    # ---- DM me hai ----
    dm_users.add(chat_id)

    # Force join check
    if chat_id not in verified_users:
        joined = await is_user_joined(context, user.id)
        if not joined:
            await send_join_msg(update)
            return
        verified_users.add(chat_id)

    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")

    await update.message.reply_text(
        "📋 *Available Commands:*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔍 *Search Commands:*\n"
        "`/tg <username>` — TG Info\n"
        "`/num <number>` — Number Info\n"
        "`/aadhar <number>` — Aadhaar Info\n"
        "`/family <number>` — Aadhaar Family\n\n"
        "⚙️ *Other Commands:*\n"
        "`/tools` — Tools list\n"
        "`/join` — Group/Channel links\n"
        "`/verify` — Join verify\n"
        "`/myid` — Apna ID\n"
        "`/stats` — Bot stats\n"
        "`/help` — Help\n"
        "`/about` — About bot",
        parse_mode="Markdown",
    )

    if user.id not in known_users:
        known_users.add(user.id)
        await log_to_channel(
            context,
            f"🆕 NAYA USER AAYA\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 {user.first_name or ''} {user.last_name or ''}\n"
            f"🆔 {user.id}\n"
            f"🔗 @{user.username or 'no_username'}\n\n"
            f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
        )


async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return
    text = (
        "🔗 *Join Links*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ Channel join kar\n"
        "2️⃣ Group join kar\n"
        "3️⃣ Phir *Verify* button dabaye"
    )
    await update.message.reply_text(
        text,
        reply_markup=join_menu(),
        parse_mode="Markdown",
    )


async def verify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    joined = await is_user_joined(context, user.id)
    if joined:
        verified_users.add(chat_id)
        await update.message.reply_text(
            "✅ *Verify Ho Gaya!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Ab tu bot use kar sakta hai.\n\n"
            "`/tools` bhejke tools dekh ya\n"
            "seedha search command bhej:\n\n"
            "`/tg <username>`\n"
            "`/num <number>`\n"
            "`/aadhar <number>`\n"
            "`/family <number>`",
            parse_mode="Markdown",
        )
        if user.id not in known_users:
            known_users.add(user.id)
            await log_to_channel(
                context,
                f"🆕 NAYA USER AAYA\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 {user.first_name or ''} {user.last_name or ''}\n"
                f"🆔 {user.id}\n"
                f"🔗 @{user.username or 'no_username'}\n\n"
                f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
            )
    else:
        await update.message.reply_text(
            "❌ *Abhi Join Nahi Kiya!*\n\n"
            "Pehle dono join kar, fir `/verify` bhej.",
            reply_markup=join_menu(),
            parse_mode="Markdown",
        )


async def tools_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        bot_username = context.bot.username
        await update.message.reply_text(
            f"👇 Pehle bot ko DM me start kar: @{bot_username}",
        )
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id not in verified_users:
        joined = await is_user_joined(context, user.id)
        if not joined:
            await send_join_msg(update)
            return
        verified_users.add(chat_id)

    text = (
        "🧰 *Available OSINT Tools*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "✈️ *TG Info*\n"
        "`/tg <username ya ID>`\n"
        "_Example:_ `/tg @hellisheavenn`\n\n"
        "📱 *Number Info*\n"
        "`/num <10 digit number>`\n"
        "_Example:_ `/num 9876543210`\n\n"
        "🆔 *Aadhaar Info*\n"
        "`/aadhar <12 digit number>`\n"
        "_Example:_ `/aadhar 123456789012`\n\n"
        "👨‍👩‍👧 *Aadhaar Family*\n"
        "`/family <aadhaar number>`\n"
        "_Example:_ `/family 123456789012`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return
    text = (
        "❓ *HELP & GUIDE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 *Kaise Use Kare:*\n"
        "1️⃣ `/start` bhej DM me\n"
        "2️⃣ Channel + Group join kar\n"
        "3️⃣ *Verify* button dabaye\n"
        "4️⃣ Search command bhej\n\n"
        "📌 *Search Commands:*\n"
        "• `/tg @username` — TG info\n"
        "• `/num 9876543210` — Number\n"
        "• `/aadhar 123456789012` — Aadhaar\n"
        "• `/family 123456789012` — Family\n\n"
        "📌 *Other:*\n"
        "• `/tools` — Tools list\n"
        "• `/join` — Join links\n"
        "• `/verify` — Verify\n"
        "• `/myid` — Apna ID\n"
        "• `/stats` — Stats\n"
        "• `/about` — About"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return
    text = (
        "ℹ️ *ABOUT INSOMNIAC X-TRACE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🕵️ Ek advanced OSINT bot jo public sources\n"
        "se intelligence gather karta hai.\n\n"
        "🔎 Username discovery\n"
        "🌐 Profile lookup\n"
        "🧩 Digital footprint\n"
        "📡 Cross-platform search\n\n"
        "⚡ _Search smart. Stay anonymous. Think deeper._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Tera ID: `{update.effective_chat.id}`",
        parse_mode="Markdown",
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return
    await update.message.reply_text(
        f"📊 *Bot Stats*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total Users: *{len(known_users)}*\n"
        f"✅ Verified: *{len(verified_users)}*\n"
        f"💬 DM Users: *{len(dm_users)}*",
        parse_mode="Markdown",
    )


# ============ CALLBACK HANDLER (VERIFY BUTTON) ============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    chat_id = q.message.chat_id
    user = q.from_user

    if data == "verify_join":
        joined = await is_user_joined(context, user.id)
        if joined:
            verified_users.add(chat_id)
            await q.edit_message_text(
                "✅ *Verify Ho Gaya!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Ab tu bot use kar sakta hai.\n\n"
                "`/tools` bhejke tools dekh ya\n"
                "seedha search command bhej:\n\n"
                "`/tg <username>`\n"
                "`/num <number>`\n"
                "`/aadhar <number>`\n"
                "`/family <number>`",
                parse_mode="Markdown",
            )
            if user.id not in known_users:
                known_users.add(user.id)
                await log_to_channel(
                    context,
                    f"🆕 NAYA USER AAYA\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 {user.first_name or ''} {user.last_name or ''}\n"
                    f"🆔 {user.id}\n"
                    f"🔗 @{user.username or 'no_username'}\n\n"
                    f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
                )
        else:
            await q.answer("❌ Pehle dono join karo!", show_alert=True)
        return


# ============ SEARCH COMMANDS ============
async def search_tool(update: Update, context: ContextTypes.DEFAULT_TYPE, tool_key: str):
    chat_type = update.effective_chat.type

    # ---- GROUP me search nahi hoga ----
    if chat_type in ("group", "supergroup"):
        bot_username = context.bot.username
        await update.message.reply_text(
            f"👋 Group me search nahi hota!\n\n"
            f"👇 Pehle bot ko DM me start kar:\n"
            f"➡️ @{bot_username}\n\n"
            f"Wahan pe search kar sakta hai.",
        )
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    cfg = TOOLS[tool_key]

    # ---- Force join check ----
    if chat_id not in verified_users:
        joined = await is_user_joined(context, user.id)
        if not joined:
            await send_join_msg(update)
            return
        verified_users.add(chat_id)

    # ---- Query check ----
    if not context.args:
        await update.message.reply_text(
            f"⚠️ *Query Missing!*\n\n"
            f"*Use:* `/{tool_key} <{cfg['prompt']}>`",
            parse_mode="Markdown",
        )
        return

    q_text = " ".join(context.args).strip()
    url = cfg["url"].format(q=q_text)

    msg = await update.message.reply_text("⏳ Searching...")

    try:
        r = requests.get(url, timeout=30)

        try:
            data = r.json()
            cleaned = clean_response(data)
            pretty = pretty_json(cleaned)
        except Exception:
            pretty = r.text

        if len(pretty) > 3500:
            pretty = pretty[:3500] + "\n\n...(truncated)"

        user_results.setdefault(chat_id, []).append({
            "tool": cfg["name"],
            "query": q_text,
            "result": pretty,
        })
        user_results[chat_id] = user_results[chat_id][-20:]

        text = (
            f"✅ *Result Mil Gaya!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🧰 *Tool:* {cfg['name']}\n"
            f"🔍 *Query:* `{q_text}`\n"
            f"🕐 *Time:* {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *RESULT:*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"```json\n{pretty}\n```\n\n"
            f"🔁 Aur search: `/{tool_key} <nayi query>`"
        )
        await msg.edit_text(text, parse_mode="Markdown")

        log_text = (
            f"🔎 N E W   S E A R C H\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {user.first_name or ''} {user.last_name or ''}\n"
            f"🆔 {user.id}\n"
            f"🔗 @{user.username or 'no_username'}\n\n"
            f"📌 Tool: {cfg['name']}\n"
            f"🔍 Query: {q_text}\n"
            f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}\n\n"
            f"📊 RESULT:\n"
            f"{pretty[:3500]}"
        )
        await log_to_channel(context, log_text)

    except requests.exceptions.Timeout:
        await msg.edit_text(
            f"❌ *API timeout*, dobara try kar:\n`/{tool_key} {q_text}`"
        )
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`")


async def tg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await search_tool(update, context, "tg")


async def num_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await search_tool(update, context, "num")


async def aadhar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await search_tool(update, context, "aadhar")


async def family_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await search_tool(update, context, "family")


# ============ BROADCAST ============
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Tu admin nahi hai.")
        return

    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "📢 *Broadcast Use:*\n\n"
            "`/broadcast <message>`\n\n"
            "Ya reply karke `/broadcast` bhej.",
            parse_mode="Markdown",
        )
        return

    if update.message.reply_to_message:
        broadcast_msg = update.message.reply_to_message
    else:
        text = " ".join(context.args)
        broadcast_msg = await update.message.reply_text(text)

    sent = 0
    failed = 0
    status = await update.message.reply_text("📢 Broadcast shuru...")

    # Sirf DM users ko bhejo
    for uid in list(dm_users):
        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=broadcast_msg.chat_id,
                message_id=broadcast_msg.message_id,
            )
            sent += 1
        except Exception:
            failed += 1

    await status.edit_text(
        f"✅ *Broadcast Complete!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📤 Sent: *{sent}*\n"
        f"❌ Failed: *{failed}*\n"
        f"👥 Total: *{len(dm_users)}*",
        parse_mode="Markdown",
    )


# ============ GROUP MESSAGE HANDLER ============
async def group_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group me koi bhi message aaye toh DM me bhej"""
    chat_type = update.effective_chat.type
    if chat_type not in ("group", "supergroup"):
        return

    # Agar message command nahi hai toh bhi reply
    if update.message.text and not update.message.text.startswith("/"):
        bot_username = context.bot.username
        user = update.effective_user
        # Sirf tab reply karo jab bot mention ho ya koi random text ho
        await update.message.reply_text(
            f"👋 *{user.first_name}*, bot group me kaam nahi karta!\n\n"
            f"👇 DM me start kar:\n➡️ @{bot_username}",
            parse_mode="Markdown",
        )


# ============ UNKNOWN DM MESSAGE ============
async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ *Commands use kar:*\n\n"
        "`/tools` — tools list\n"
        "`/help` — help\n"
        "`/tg @username` — TG info\n"
        "`/num 9876543210` — number\n"
        "`/aadhar 123456789012` — aadhaar\n"
        "`/family 123456789012` — family",
        parse_mode="Markdown",
    )


# ============ POST INIT ============
async def post_init(app):
    await set_commands(app)


# ============ MAIN ============
if __name__ == "__main__":
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN set nahi hai")
        exit(1)
    if LOG_CHANNEL_ID == 0:
        print("⚠️ LOG_CHANNEL_ID set nahi hai")
    if not ADMIN_IDS or ADMIN_IDS == [0]:
        print("⚠️ ADMIN_ID set nahi hai — broadcast band")
    else:
        print(f"✅ Admins: {ADMIN_IDS}")

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("verify", verify_cmd))
    app.add_handler(CommandHandler("tools", tools_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    # Search commands
    app.add_handler(CommandHandler("tg", tg_cmd))
    app.add_handler(CommandHandler("num", num_cmd))
    app.add_handler(CommandHandler("aadhar", aadhar_cmd))
    app.add_handler(CommandHandler("family", family_cmd))

    # Verify button callback
    app.add_handler(CallbackQueryHandler(button_handler))

    # Unknown text messages (DM)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_handler))

    print("🔥 INSOMNIAC X-TRACE Bot chalu ho raha hai...")
    app.run_polling()
