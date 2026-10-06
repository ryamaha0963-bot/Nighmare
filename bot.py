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

# ---- MULTIPLE ADMINS ----
ADMIN_IDS = [
    int(x.strip())
    for x in os.environ.get("ADMIN_ID", "0").split(",")
    if x.strip().isdigit()
]

TOOLS = {
    "tg_info":       {"name": "✈️ TG Info",         "url": "https://tg-to-info.asurpapa.workers.dev/api?key=OSINTBOT&query={q}",       "prompt": "Telegram username ya ID bhej"},
    "num_info":      {"name": "📱 Number Info",     "url": "https://num-to-info.asurpapa.workers.dev/api?key=OSINTBOT&number={q}",     "prompt": "10 digit mobile number bhej"},
    "aadhar_info":   {"name": "🆔 Aadhaar Info",    "url": "https://aadhaar.asurpapa.workers.dev/api?key=OSINTBOT&aadhaar={q}",        "prompt": "12 digit Aadhaar number bhej"},
    "aadhar_family": {"name": "👨‍👩‍👧 Aadhaar Family", "url": "https://aadhaar-family.asurpapa.workers.dev/api?key=OSINTBOT&aadhaar={q}", "prompt": "Aadhaar number bhej"},
}

HIDE_KEYS = {"credit", "developer", "footer", "contact", "powered_by"}

# ============ WELCOME TEXT ============
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
user_state = {}
user_results = {}
known_users = set()
verified_users = set()


def clean_response(data):
    if isinstance(data, dict):
        return {k: clean_response(v) for k, v in data.items() if k.lower() not in HIDE_KEYS}
    if isinstance(data, list):
        return [clean_response(i) for i in data]
    return data


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
    buttons = [
        [InlineKeyboardButton("📢 Channel Join Kar", url=CHANNEL_LINK)],
        [InlineKeyboardButton("👥 Group Join Kar", url=GROUP_LINK)],
        [InlineKeyboardButton("✅ Verify Kar", callback_data="verify_join")],
    ]
    return InlineKeyboardMarkup(buttons)


# ============ MENUS ============
def main_menu():
    buttons = []
    row = []
    for key, cfg in TOOLS.items():
        row.append(InlineKeyboardButton(cfg["name"], callback_data=f"tool:{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def result_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Naya Search", callback_data="new_search"),
            InlineKeyboardButton("📜 Mere Results", callback_data="my_results"),
        ],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="back")],
    ])


# ============ BOT COMMANDS SETUP ============
async def set_commands(app):
    commands = [
        BotCommand("start",     "🚀 Bot Start Kare"),
        BotCommand("tools",     "🧰 Saare OSINT Tools Dekhe"),
        BotCommand("search",    "🔍 Direct Search Kare"),
        BotCommand("myid",      "🆔 Apna Telegram ID Dekhe"),
        BotCommand("stats",     "📊 Bot Statistics Dekhe"),
        BotCommand("help",      "❓ Help & Guide"),
        BotCommand("about",     "ℹ️ Bot Ke Baare Me"),
        BotCommand("broadcast", "📢 [Admin] Broadcast Message"),
    ]
    await app.bot.set_my_commands(commands)


# ============ HANDLERS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_state.pop(chat_id, None)

    if chat_id not in verified_users:
        joined = await is_user_joined(context, user.id)
        if not joined:
            await update.message.reply_text(
                "🚫 *Pehle Join Karo!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Bot use karne ke liye pehle niche diye gaye\n"
                "Channel aur Group ko join karo.\n\n"
                "✅ Join karne ke baad *Verify* pe click karo.",
                reply_markup=join_menu(),
                parse_mode="Markdown",
            )
            return
        verified_users.add(chat_id)

    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=main_menu(),
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


async def tools_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧰 *Available OSINT Tools*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Neeche se koi bhi tool select kar 👇",
        reply_markup=main_menu(),
        parse_mode="Markdown",
    )


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 *Direct Search*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Pehle tool select kar, phir query bhej 👇",
        reply_markup=main_menu(),
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ *HELP & GUIDE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 *Kaise Use Kare:*\n"
        "1️⃣ `/start` bhej\n"
        "2️⃣ Tool select kar\n"
        "3️⃣ Query bhej (number, username, aadhaar)\n"
        "4️⃣ Result milega\n\n"
        "📌 *Commands:*\n"
        "• `/start` — Bot start\n"
        "• `/tools` — Tools list\n"
        "• `/search` — Direct search\n"
        "• `/myid` — Apna ID\n"
        "• `/stats` — Bot stats\n"
        "• `/about` — Bot info\n\n"
        "⚠️ *Note:* Sirf public-source intelligence\n"
        "ke liye use karo. Illegal activity strictly\n"
        "prohibited hai."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                WELCOME_TEXT + "\n\n✅ *Verify ho gaya!*\n\n📌 Neeche se tool select kar 👇",
                reply_markup=main_menu(),
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

    if chat_id not in verified_users:
        joined = await is_user_joined(context, user.id)
        if not joined:
            await q.edit_message_text(
                "🚫 *Pehle Join Karo!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Bot use karne ke liye pehle join karo.\n"
                "✅ Join ke baad *Verify* pe click karo.",
                reply_markup=join_menu(),
                parse_mode="Markdown",
            )
            return
        verified_users.add(chat_id)

    if data == "back":
        user_state.pop(chat_id, None)
        await q.edit_message_text(
            WELCOME_TEXT + "\n\n📌 Neeche se tool select kar 👇",
            reply_markup=main_menu(),
            parse_mode="Markdown",
        )
        return

    if data == "new_search":
        user_state.pop(chat_id, None)
        await q.edit_message_text(
            "🔍 *Naya Search*\n\nTool select kar 👇",
            reply_markup=main_menu(),
            parse_mode="Markdown",
        )
        return

    if data == "my_results":
        results = user_results.get(chat_id, [])
        if not results:
            await q.edit_message_text(
                "📭 Abhi tak koi result save nahi hua.\nPehle koi search kar.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Main Menu", callback_data="back")]]
                ),
            )
            return

        buttons = []
        for i, r in enumerate(results, 1):
            label = f"{i}. {r['tool']} — {r['query']}"
            buttons.append([InlineKeyboardButton(label[:60], callback_data=f"view:{i-1}")])
        buttons.append([InlineKeyboardButton("🏠 Main Menu", callback_data="back")])

        await q.edit_message_text(
            f"📜 *Saved Results* ({len(results)})\n\nKoi ek peh click kar 👇",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )
        return

    if data.startswith("view:"):
        idx = int(data.split(":")[1])
        results = user_results.get(chat_id, [])
        if idx >= len(results):
            await q.answer("Result nahi mila", show_alert=True)
            return
        r = results[idx]
        text = (
            f"📌 *{r['tool']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔍 Query: `{r['query']}`\n\n"
            f"```\n{r['result'][:3500]}\n```"
        )
        await q.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Naya Search", callback_data="new_search")],
                [InlineKeyboardButton("⬅️ Results List", callback_data="my_results")],
            ]),
            parse_mode="Markdown",
        )
        return

    if data.startswith("tool:"):
        tool_key = data.split(":", 1)[1]
        cfg = TOOLS.get(tool_key)
        if not cfg:
            await q.edit_message_text("❌ Tool nahi mila")
            return
        user_state[chat_id] = tool_key
        text = (
            f"📌 *{cfg['name']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"➡️ {cfg['prompt']}"
        )
        await q.edit_message_text(text, parse_mode="Markdown")
        return


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id not in verified_users:
        joined = await is_user_joined(context, user.id)
        if not joined:
            await update.message.reply_text(
                "🚫 *Pehle Join Karo!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Bot use karne ke liye pehle join karo.\n"
                "✅ Join ke baad *Verify* pe click karo.",
                reply_markup=join_menu(),
                parse_mode="Markdown",
            )
            return
        verified_users.add(chat_id)

    tool_key = user_state.get(chat_id)

    if not tool_key:
        await update.message.reply_text(
            "👉 Pehle /start karke tool select kar bhai.",
            reply_markup=main_menu(),
        )
        return

    cfg = TOOLS[tool_key]
    q = update.message.text.strip()
    url = cfg["url"].format(q=q)

    msg = await update.message.reply_text("⏳ Searching...")

    try:
        r = requests.get(url, timeout=30)

        try:
            data = r.json()
            cleaned = clean_response(data)
            pretty = json.dumps(cleaned, indent=2, ensure_ascii=False)
        except Exception:
            pretty = r.text

        if len(pretty) > 3800:
            pretty = pretty[:3800] + "\n\n...(truncated)"

        user_results.setdefault(chat_id, []).append({
            "tool": cfg["name"],
            "query": q,
            "result": pretty,
        })
        user_results[chat_id] = user_results[chat_id][-20:]

        text = (
            f"✅ *{cfg['name']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔍 Query: `{q}`\n\n"
            f"```\n{pretty}\n```"
        )
        await msg.edit_text(text, reply_markup=result_menu(), parse_mode="Markdown")

        log_text = (
            f"🔎 N E W   S E A R C H\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {user.first_name or ''} {user.last_name or ''}\n"
            f"🆔 {user.id}\n"
            f"🔗 @{user.username or 'no_username'}\n\n"
            f"📌 Tool: {cfg['name']}\n"
            f"🔍 Query: {q}\n"
            f"🕐 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}\n\n"
            f"📊 RESULT:\n"
            f"{pretty[:3500]}"
        )
        await log_to_channel(context, log_text)

    except requests.exceptions.Timeout:
        await msg.edit_text(
            "❌ *API timeout* ho gayi, dobara try kar.",
            reply_markup=result_menu(),
            parse_mode="Markdown",
        )
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")

    user_state.pop(chat_id, None)


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Tera ID: `{update.effective_chat.id}`",
        parse_mode="Markdown",
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 *Bot Stats*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total Users: *{len(known_users)}*\n"
        f"🔍 Active Sessions: *{len(user_results)}*",
        parse_mode="Markdown",
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Tu admin nahi hai.")
        return

    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "📢 *Broadcast Use Karne Ka Tarika:*\n\n"
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
    status = await update.message.reply_text("📢 Broadcast shuru ho gaya...")

    for uid in list(known_users):
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
        f"👥 Total: *{len(known_users)}*",
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
        print("⚠️ LOG_CHANNEL_ID set nahi hai — channel logging off")
    if not ADMIN_IDS or ADMIN_IDS == [0]:
        print("⚠️ ADMIN_ID set nahi hai — broadcast band rahega")
    else:
        print(f"✅ Admins: {ADMIN_IDS}")

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tools", tools_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🔥 INSOMNIAC X-TRACE Bot chalu ho raha hai...")
    app.run_polling()
