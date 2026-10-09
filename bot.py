import os
import json
import asyncio
import requests
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    ChatJoinRequest,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ChatJoinRequestHandler,
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
verified_users = set()
dm_users = set()
group_request_users = set()
channel_request_users = set()

# Broadcast state
broadcast_data = {
    "active": False,
    "sent": 0,
    "failed": 0,
    "total": 0,
}

USERS_FILE = "bot_users.json"


# ============ PERSISTENCE ============
def load_users():
    """Load users from JSON file"""
    global known_users, verified_users, dm_users
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                data = json.load(f)
                known_users = set(data.get("known_users", []))
                verified_users = set(data.get("verified_users", []))
                dm_users = set(data.get("dm_users", []))
                print(f"✅ Loaded: {len(dm_users)} DM users, {len(verified_users)} verified, {len(known_users)} known")
        else:
            print("📂 No users file found, starting fresh")
    except Exception as e:
        print(f"⚠️ Load users error: {e}")


def save_users():
    """Save users to JSON file"""
    try:
        with open(USERS_FILE, "w") as f:
            json.dump({
                "known_users": list(known_users),
                "verified_users": list(verified_users),
                "dm_users": list(dm_users),
            }, f, indent=2)
    except Exception as e:
        print(f"⚠️ Save users error: {e}")


# ============ HELPERS ============
def clean_response(data):
    if isinstance(data, dict):
        return {k: clean_response(v) for k, v in data.items() if k.lower() not in HIDE_KEYS}
    if isinstance(data, list):
        return [clean_response(i) for i in data]
    return data


def pretty_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False)


def is_admin(user_id):
    """Check if user is admin"""
    if not ADMIN_IDS:
        return True  # No admins set = everyone is admin (dev mode)
    return user_id in ADMIN_IDS


async def log_to_channel(context, text):
    if LOG_CHANNEL_ID == 0:
        return
    try:
        if len(text) > 4000:
            text = text[:4000] + "\n\n...(truncated)"
        await context.bot.send_message(LOG_CHANNEL_ID, text, parse_mode=None)
    except Exception as e:
        print(f"Log channel error: {e}")


# ============ FORCE JOIN CHECK ============
async def is_user_joined(context, user_id):
    group_ok = (GROUP_ID == 0)
    channel_ok = (CHANNEL_ID == 0)

    # ---- GROUP CHECK ----
    if GROUP_ID != 0:
        if user_id in group_request_users:
            group_ok = True
        else:
            try:
                member = await context.bot.get_chat_member(GROUP_ID, user_id)
                if member.status in ("member", "administrator", "creator", "restricted"):
                    group_ok = True
                elif member.status == "left":
                    group_request_users.discard(user_id)
                    group_ok = False
                else:
                    group_ok = False
            except Exception as e:
                print(f"Group check error: {e}")
                group_ok = user_id in group_request_users

    # ---- CHANNEL CHECK ----
    if CHANNEL_ID != 0:
        if user_id in channel_request_users:
            channel_ok = True
        else:
            try:
                member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
                if member.status in ("member", "administrator", "creator", "restricted"):
                    channel_ok = True
                elif member.status == "left":
                    channel_request_users.discard(user_id)
                    channel_ok = False
                else:
                    channel_ok = False
            except Exception as e:
                print(f"Channel check error: {e}")
                channel_ok = user_id in channel_request_users

    return group_ok and channel_ok


def join_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Channel Join Kar", url=CHANNEL_LINK)],
        [InlineKeyboardButton("👥 Group Join Kar", url=GROUP_LINK)],
        [InlineKeyboardButton("✅ Verify Kar", callback_data="verify_join")],
    ])


async def send_join_msg(update: Update):
    text = (
        "🚫 *Pehle Join Karo!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Bot use karne ke liye pehle ye karo:\n\n"
        "1️⃣ *Channel* join kar (request bhej)\n"
        "2️⃣ *Group* join kar (request bhej)\n"
        "3️⃣ Phir *Verify Kar* button dabaye\n\n"
        "⚠️ Join request bhejna zaroori hai!\n"
        "Request approve hone ke baad bot start hoga."
    )
    await update.message.reply_text(
        text,
        reply_markup=join_menu(),
        parse_mode="Markdown",
    )


# ============ BOT COMMANDS SETUP ============
async def set_commands(app):
    commands = [
        BotCommand("start",            "🚀 Bot Start Kare"),
        BotCommand("join",             "🔗 Group & Channel Join Kare"),
        BotCommand("verify",           "✅ Join Verify Kare"),
        BotCommand("tools",            "🧰 Saare OSINT Tools Dekhe"),
        BotCommand("tg",               "✈️ TG Info Search"),
        BotCommand("num",              "📱 Number Info Search"),
        BotCommand("aadhar",           "🆔 Aadhaar Info Search"),
        BotCommand("family",           "👨‍👩‍👧 Aadhaar Family Search"),
        BotCommand("myid",             "🆔 Apna Telegram ID"),
        BotCommand("stats",            "📊 Bot Statistics"),
        BotCommand("help",             "❓ Help & Guide"),
        BotCommand("about",            "ℹ️ Bot Ke Baare Me"),
        BotCommand("broadcast",        "📢 [Admin] Broadcast Bhejo"),
        BotCommand("broadcast_stats",  "📊 [Admin] Broadcast Stats"),
        BotCommand("broadcast_cancel", "❌ [Admin] Broadcast Cancel"),
        BotCommand("broadcast_users",  "📋 [Admin] User List"),
    ]
    await app.bot.set_my_commands(commands)


# ============ JOIN REQUEST HANDLERS ============
async def group_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req: ChatJoinRequest = update.chat_join_request
    user = req.from_user
    user_id = user.id

    group_request_users.add(user_id)
    print(f"✅ Group join request: {user_id} ({user.full_name})")

    await log_to_channel(
        context,
        f"📥 GROUP JOIN REQUEST\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user_id}\n"
        f"🔗 @{user.username or 'no_username'}\n\n"
        f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
    )

    try:
        await req.approve()
        print(f"✅ Auto-approved group request: {user_id}")
    except Exception as e:
        print(f"⚠️ Auto-approve failed (manual approval needed): {e}")


async def channel_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req: ChatJoinRequest = update.chat_join_request
    user = req.from_user
    user_id = user.id

    channel_request_users.add(user_id)
    print(f"✅ Channel join request: {user_id} ({user.full_name})")

    await log_to_channel(
        context,
        f"📥 CHANNEL JOIN REQUEST\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user_id}\n"
        f"🔗 @{user.username or 'no_username'}\n\n"
        f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
    )

    try:
        await req.approve()
        print(f"✅ Auto-approved channel request: {user_id}")
    except Exception as e:
        print(f"⚠️ Auto-approve failed: {e}")


# ============ BASIC COMMANDS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    chat_type = update.effective_chat.type

    if chat_type in ("group", "supergroup"):
        bot_username = context.bot.username
        await update.message.reply_text(
            f"👋 *{user.first_name}*, group me search nahi hota!\n\n"
            f"👇 Bot ko DM me start kar:\n➡️ @{bot_username}",
            parse_mode="Markdown",
        )
        return

    dm_users.add(chat_id)
    save_users()

    if chat_id not in verified_users:
        joined = await is_user_joined(context, user.id)
        if not joined:
            await send_join_msg(update)
            return
        verified_users.add(chat_id)
        save_users()

    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")
    await update.message.reply_text(
        "📋 *Available Commands:*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔍 *Search:*\n"
        "`/tg <username>` — TG Info\n"
        "`/num <number>` — Number Info\n"
        "`/aadhar <number>` — Aadhaar\n"
        "`/family <number>` — Family\n\n"
        "⚙️ *Other:*\n"
        "`/tools` `/join` `/verify`\n"
        "`/myid` `/stats` `/help` `/about`",
        parse_mode="Markdown",
    )

    if user.id not in known_users:
        known_users.add(user.id)
        save_users()
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
        "3️⃣ *Verify Kar* button dabaye\n\n"
        "⚠️ Join *request* bhejna zaroori hai!"
    )
    await update.message.reply_text(text, reply_markup=join_menu(), parse_mode="Markdown")


async def verify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    joined = await is_user_joined(context, user.id)
    if joined:
        verified_users.add(chat_id)
        dm_users.add(chat_id)
        save_users()
        await update.message.reply_text(
            "✅ *Verify Ho Gaya!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Ab tu bot use kar sakta hai.\n\n"
            "`/tools` bhejke tools dekh ya seedha search:\n"
            "`/tg <username>`\n"
            "`/num <number>`",
            parse_mode="Markdown",
        )
        if user.id not in known_users:
            known_users.add(user.id)
            save_users()
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
            "Pehle join *request* bhej, fir verify.",
            reply_markup=join_menu(),
            parse_mode="Markdown",
        )


async def tools_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        await update.message.reply_text(f"👇 DM me start kar: @{context.bot.username}")
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id not in verified_users:
        joined = await is_user_joined(context, user.id)
        if not joined:
            await send_join_msg(update)
            return
        verified_users.add(chat_id)
        dm_users.add(chat_id)
        save_users()

    text = (
        "🧰 *Available OSINT Tools*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "✈️ `/tg <username>`\n_Example:_ `/tg @hellisheavenn`\n\n"
        "📱 `/num <10 digit>`\n_Example:_ `/num 9876543210`\n\n"
        "🆔 `/aadhar <12 digit>`\n_Example:_ `/aadhar 123456789012`\n\n"
        "👨‍👩‍👧 `/family <aadhaar>`\n_Example:_ `/family 123456789012`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return
    text = (
        "❓ *HELP*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ `/start` bhej DM me\n"
        "2️⃣ Channel + Group join *request* bhej\n"
        "3️⃣ *Verify Kar* button dabaye\n"
        "4️⃣ Search command bhej\n\n"
        "📌 *Search:*\n"
        "`/tg @username`\n`/num 9876543210`\n"
        "`/aadhar 123456789012`\n`/family 123456789012`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return
    text = (
        "ℹ️ *ABOUT INSOMNIAC X-TRACE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🕵️ OSINT bot jo public sources se\n"
        "intelligence gather karta hai.\n\n"
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
        f"💬 DM Users: *{len(dm_users)}*\n"
        f"📥 Group Requests: *{len(group_request_users)}*\n"
        f"📥 Channel Requests: *{len(channel_request_users)}*",
        parse_mode="Markdown",
    )


# ============ CALLBACK (VERIFY BUTTON) ============
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
            dm_users.add(chat_id)
            save_users()
            await q.edit_message_text(
                "✅ *Verify Ho Gaya!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Ab tu bot use kar sakta hai.\n\n"
                "`/tools` bhejke tools dekh ya seedha search:\n"
                "`/tg <username>`\n"
                "`/num <number>`\n"
                "`/aadhar <number>`\n"
                "`/family <number>`",
                parse_mode="Markdown",
            )
            if user.id not in known_users:
                known_users.add(user.id)
                save_users()
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
            group_ok = (GROUP_ID == 0) or (user.id in group_request_users)
            channel_ok = (CHANNEL_ID == 0) or (user.id in channel_request_users)

            if not group_ok and GROUP_ID != 0:
                try:
                    m = await context.bot.get_chat_member(GROUP_ID, user.id)
                    if m.status in ("member", "administrator", "creator", "restricted"):
                        group_ok = True
                except Exception:
                    pass

            if not channel_ok and CHANNEL_ID != 0:
                try:
                    m = await context.bot.get_chat_member(CHANNEL_ID, user.id)
                    if m.status in ("member", "administrator", "creator", "restricted"):
                        channel_ok = True
                except Exception:
                    pass

            missing = []
            if not group_ok:
                missing.append("👥 Group")
            if not channel_ok:
                missing.append("📢 Channel")

            await q.answer(
                f"❌ Pehle join request bhej:\n" + "\n".join(missing),
                show_alert=True,
            )
        return


# ============ SEARCH ============
async def search_tool(update: Update, context: ContextTypes.DEFAULT_TYPE, tool_key: str):
    chat_type = update.effective_chat.type
    if chat_type in ("group", "supergroup"):
        await update.message.reply_text(
            f"👋 Group me search nahi hota!\n"
            f"👇 DM me start kar: @{context.bot.username}",
        )
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    cfg = TOOLS[tool_key]

    if chat_id not in verified_users:
        joined = await is_user_joined(context, user.id)
        if not joined:
            await send_join_msg(update)
            return
        verified_users.add(chat_id)
        dm_users.add(chat_id)
        save_users()

    if not context.args:
        await update.message.reply_text(
            f"⚠️ *Query Missing!*\n\n*Use:* `/{tool_key} <{cfg['prompt']}>`",
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
            "tool": cfg["name"], "query": q_text, "result": pretty,
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
            f"🔁 Aur: `/{tool_key} <query>`"
        )
        await msg.edit_text(text, parse_mode="Markdown")

        await log_to_channel(
            context,
            f"🔎 NEW SEARCH\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 {user.first_name or ''}\n"
            f"🆔 {user.id}\n"
            f"🔗 @{user.username or 'no_username'}\n\n"
            f"🧰 Tool: {cfg['name']}\n"
            f"🔍 Query: {q_text}\n"
            f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}\n\n"
            f"📊 RESULT:\n{pretty[:3500]}",
        )
    except requests.exceptions.Timeout:
        await msg.edit_text(f"❌ Timeout. Try: `/{tool_key} {q_text}`")
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`")


async def tg_cmd(update, context): await search_tool(update, context, "tg")
async def num_cmd(update, context): await search_tool(update, context, "num")
async def aadhar_cmd(update, context): await search_tool(update, context, "aadhar")
async def family_cmd(update, context): await search_tool(update, context, "family")


# ============ BROADCAST SYSTEM ============
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all DM users"""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("🚫 Tu admin nahi hai.")
        return

    if broadcast_data["active"]:
        await update.message.reply_text("⚠️ Ek broadcast already chal raha hai. Ruko.")
        return

    # Get message
    if update.message.reply_to_message:
        broadcast_msg = update.message.reply_to_message
    elif context.args:
        broadcast_msg = await update.message.reply_text(" ".join(context.args))
    else:
        await update.message.reply_text(
            "📢 *Broadcast Use Karne Ka Tarika:*\n\n"
            "1️⃣ `/broadcast <message>` — Text bhej\n"
            "2️⃣ Kisi message ko *reply* karke `/broadcast` — Copy bhej\n\n"
            "📊 `/broadcast_stats` — Broadcast stats\n"
            "❌ `/broadcast_cancel` — Cancel karo\n"
            "📋 `/broadcast_users` — User list",
            parse_mode="Markdown",
        )
        return

    total = len(dm_users)

    if total == 0:
        await update.message.reply_text("❌ Koi user nahi hai abhi jisko bhej sake.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Haan, Bhej De", callback_data="bc_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="bc_cancel"),
        ]
    ])

    context.user_data["pending_broadcast"] = {
        "chat_id": broadcast_msg.chat_id,
        "message_id": broadcast_msg.message_id,
    }

    await update.message.reply_text(
        f"📢 *Broadcast Confirm Karo*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 *Total Users:* `{total}`\n"
        f"📨 *Mode:* {'Reply Copy' if update.message.reply_to_message else 'Text'}\n\n"
        f"⚠️ Ye message sabko jayega. Confirm?",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually execute broadcast"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.answer("🚫 Tu admin nahi hai.", show_alert=True)
        return

    if query.data == "bc_cancel":
        await query.edit_message_text("❌ Broadcast cancel kar diya.")
        context.user_data.pop("pending_broadcast", None)
        return

    if query.data != "bc_confirm":
        return

    pending = context.user_data.pop("pending_broadcast", None)
    if not pending:
        await query.edit_message_text("❌ Kuch gadbad ho gayi. Dobara try kar.")
        return

    if broadcast_data["active"]:
        await query.edit_message_text("⚠️ Broadcast already running hai.")
        return

    broadcast_data["active"] = True
    broadcast_data["sent"] = 0
    broadcast_data["failed"] = 0
    broadcast_data["total"] = len(dm_users)

    status_msg = await query.edit_message_text(
        f"📢 *Broadcast Shuru...*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📤 Sent: `0`\n"
        f"❌ Failed: `0`\n"
        f"👥 Total: `{broadcast_data['total']}`\n\n"
        f"⏳ _Please wait..._",
        parse_mode="Markdown",
    )

    failed_users = []

    for i, uid in enumerate(list(dm_users), 1):
        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=pending["chat_id"],
                message_id=pending["message_id"],
            )
            broadcast_data["sent"] += 1
        except Exception as e:
            broadcast_data["failed"] += 1
            failed_users.append(uid)
            print(f"Broadcast failed for {uid}: {e}")

        # Update status every 10 users
        if i % 10 == 0 or i == broadcast_data["total"]:
            try:
                await context.bot.edit_message_text(
                    chat_id=status_msg.chat_id,
                    message_id=status_msg.message_id,
                    text=(
                        f"📢 *Broadcast Chal Raha Hai...*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📤 Sent: `{broadcast_data['sent']}`\n"
                        f"❌ Failed: `{broadcast_data['failed']}`\n"
                        f"👥 Total: `{broadcast_data['total']}`\n"
                        f"📊 Progress: `{i}/{broadcast_data['total']}`\n\n"
                        f"⏳ _Please wait..._"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        await asyncio.sleep(0.05)

    # Clean failed users
    for uid in failed_users:
        dm_users.discard(uid)
        verified_users.discard(uid)
    save_users()

    sent_count = broadcast_data["sent"]
    failed_count = broadcast_data["failed"]
    total_count = broadcast_data["total"]

    try:
        await context.bot.edit_message_text(
            chat_id=status_msg.chat_id,
            message_id=status_msg.message_id,
            text=(
                f"✅ *Broadcast Complete!*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📤 Sent: `{sent_count}`\n"
                f"❌ Failed: `{failed_count}`\n"
                f"👥 Total: `{total_count}`\n"
                f"🧹 Cleaned: `{len(failed_users)}` dead users\n\n"
                f"🎯 _Broadcast successfully complete!_"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass

    broadcast_data["active"] = False

    await log_to_channel(
        context,
        f"📢 BROADCAST COMPLETE\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Admin: {user_id}\n"
        f"📤 Sent: {sent_count}\n"
        f"❌ Failed: {failed_count}\n"
        f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
    )


async def broadcast_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show broadcast stats"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Tu admin nahi hai.")
        return

    await update.message.reply_text(
        f"📊 *Broadcast Statistics*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 DM Users: `{len(dm_users)}`\n"
        f"✅ Verified: `{len(verified_users)}`\n"
        f"🆕 Known Users: `{len(known_users)}`\n\n"
        f"📢 *Status:* {'🟢 Active' if broadcast_data['active'] else '🔴 Idle'}\n\n"
        f"💡 `/broadcast <msg>` — Broadcast bhej\n"
        f"💡 `/broadcast_cancel` — Cancel karo",
        parse_mode="Markdown",
    )


async def broadcast_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel running broadcast"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Tu admin nahi hai.")
        return

    if not broadcast_data["active"]:
        await update.message.reply_text("❌ Koi broadcast nahi chal raha.")
        return

    broadcast_data["active"] = False
    await update.message.reply_text(
        f"❌ *Broadcast Cancel Kar Diya*\n\n"
        f"📤 Sent: `{broadcast_data['sent']}`\n"
        f"❌ Failed: `{broadcast_data['failed']}`",
        parse_mode="Markdown",
    )


async def broadcast_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export user list for admin"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Tu admin nahi hai.")
        return

    if not dm_users:
        await update.message.reply_text("❌ Koi user nahi hai abhi.")
        return

    users_text = "📋 *User List (DM Users)*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, uid in enumerate(list(dm_users)[:50], 1):
        users_text += f"{i}. `{uid}`\n"

    if len(dm_users) > 50:
        users_text += f"\n...aur {len(dm_users) - 50} users"

    await update.message.reply_text(users_text, parse_mode="Markdown")


# ============ UNKNOWN ============
async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Commands use kar:\n`/tools` `/help`\n`/tg @username`\n`/num 9876543210`",
        parse_mode="Markdown",
    )


# ============ POST INIT ============
async def post_init(app):
    load_users()
    await set_commands(app)


# ============ MAIN ============
if __name__ == "__main__":
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN set nahi hai")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    # Basic commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("verify", verify_cmd))
    app.add_handler(CommandHandler("tools", tools_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))

    # Search commands
    app.add_handler(CommandHandler("tg", tg_cmd))
    app.add_handler(CommandHandler("num", num_cmd))
    app.add_handler(CommandHandler("aadhar", aadhar_cmd))
    app.add_handler(CommandHandler("family", family_cmd))

    # Broadcast commands
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("broadcast_stats", broadcast_stats_cmd))
    app.add_handler(CommandHandler("broadcast_cancel", broadcast_cancel_cmd))
    app.add_handler(CommandHandler("broadcast_users", broadcast_users_cmd))

    # Join request handlers
    app.add_handler(ChatJoinRequestHandler(group_join_request))
    app.add_handler(ChatJoinRequestHandler(channel_join_request))

    # Callbacks
    app.add_handler(CallbackQueryHandler(execute_broadcast, pattern="^bc_"))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^verify_join$"))

    # Unknown
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_handler))

    print("🔮 INSOMNIAC X-TRACE Bot chalu ho raha hai...")
    app.run_polling()
