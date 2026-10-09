import os
import json
import html
import asyncio
from datetime import datetime
from urllib.parse import quote

import requests
import phonenumbers
from phonenumbers import geocoder, carrier
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand,
    BotCommandScopeDefault, BotCommandScopeChat,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "0"))
# Supports one or more Telegram user IDs, comma-separated in Railway Variables.
ADMIN_IDS = {
    int(item.strip())
    for item in os.environ.get("ADMIN_ID", "").split(",")
    if item.strip().isdigit()
}
FORCE_JOIN_CHANNEL = os.environ.get("FORCE_JOIN_CHANNEL", os.environ.get("CHANNEL_ID", "")).strip()  # @channelusername or -100...
FORCE_JOIN_URL = os.environ.get("FORCE_JOIN_URL", os.environ.get("CHANNEL_LINK", "")).strip()
FORCE_JOIN_GROUP = os.environ.get("FORCE_JOIN_GROUP", os.environ.get("GROUP_ID", "")).strip()
FORCE_JOIN_GROUP_URL = os.environ.get("FORCE_JOIN_GROUP_URL", os.environ.get("GROUP_LINK", "")).strip()
BOT_NAME = os.environ.get("BOT_NAME", "NEXUS")
ACCENT = "━━━━━━━━━━━━━━━━━━━━"
USERS_FILE = os.environ.get("USERS_FILE", "known_users.json")

# Only public/general-purpose lookups are included in this UI build.
# Private-person lookup endpoints (Aadhaar/family, phone owner, call tracking,
# PAN, vehicle-to-person/number) are intentionally not wired into this version.
TOOLS = {
    "num_info": {
        "name": "📱 Number Info",
        "description": "Basic phone-number format and numbering metadata (no owner lookup)",
        "prompt": "Phone number country code ke saath bhejo (example: +919876543210)",
        "type": "local_number_info",
    },
    "ifsc_info": {
        "name": "🏦 IFSC Bank Finder",
        "description": "Bank branch details using a public IFSC code",
        "prompt": "IFSC code bhejo (example: SBIN0001234)",
        "url": "https://ifsc.asurpapa.workers.dev/api?key=OSINTBOT&ifsc={q}",
    },
    "tg_info": {
        "name": "✈️ Public Telegram Info",
        "description": "Public username or Telegram ID lookup",
        "prompt": "Public Telegram username ya ID bhejo",
        "url": "https://tg-to-info.asurpapa.workers.dev/api?key=OSINTBOT&query={q}",
    },
}

user_state = {}
user_results = {}


def load_known_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as file:
            return {int(value) for value in json.load(file)}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return set()


known_users = load_known_users()


def save_known_users():
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as file:
            json.dump(sorted(known_users), file)
    except OSError as exc:
        print(f"Could not save user list: {exc}")


HIDE_KEYS = {"credit", "developer", "footer", "contact", "powered_by"}


def esc(value):
    return html.escape(str(value), quote=False)


def clean_response(data):
    if isinstance(data, dict):
        return {k: clean_response(v) for k, v in data.items()
                if k.lower() not in HIDE_KEYS}
    if isinstance(data, list):
        return [clean_response(item) for item in data]
    return data


def command_help():
    return (
        f"✨ <b>{BOT_NAME}</b>\n{ACCENT}\n\n"
        "Available commands:\n"
        "/start — Start the bot\n"
        "/num — Phone number metadata\n"
        "/info — Public Telegram info\n"
        "/ifsc — Find bank branch by IFSC\n"
        "/cancel — Cancel current search\n"
    )


USER_COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("num", "Phone number metadata"),
    BotCommand("info", "Public Telegram info"),
    BotCommand("ifsc", "Find bank branch by IFSC"),
    BotCommand("cancel", "Cancel current search"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand("verify", "Verify channel membership"),
    BotCommand("myid", "Show Telegram ID"),
    BotCommand("stats", "Bot statistics"),
    BotCommand("broadcast", "Broadcast a message to users"),
]

def force_join_keyboard():
    buttons = []
    if FORCE_JOIN_CHANNEL and FORCE_JOIN_URL:
        buttons.append([InlineKeyboardButton("📢 Join / Request Channel", url=FORCE_JOIN_URL)])
    if FORCE_JOIN_GROUP and FORCE_JOIN_GROUP_URL:
        buttons.append([InlineKeyboardButton("👥 Join / Request Group", url=FORCE_JOIN_GROUP_URL)])
    buttons.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify_join")])
    return InlineKeyboardMarkup(buttons)


async def is_member(bot, user_id):
    """Require membership in every configured channel/group."""
    required_chats = [chat_id for chat_id in (FORCE_JOIN_CHANNEL, FORCE_JOIN_GROUP) if chat_id]
    for chat_id in required_chats:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except Exception as exc:
            print(f"Force-join verification error for {chat_id}: {exc}")
            return False
    return True


async def send_force_join(update_or_query, user):
    text = (
        f"🔒 <b>{BOT_NAME} • CHANNEL VERIFICATION</b>\n{ACCENT}\n\n"
        "Bot use karne se pehle neeche diye gaye <b>channel aur group</b> join karo.\n"
        "Agar join request bheji hai, admin ke approve karne ka wait karo.\n"
        "Approval ke baad <b>Verify Membership</b> dabao.\n\n"
        "Commands unlock hone ke baad: /num, /info, /ifsc"
    )
    if hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        await update_or_query.callback_query.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=force_join_keyboard()
        )
    elif hasattr(update_or_query, "effective_message") and update_or_query.effective_message:
        await update_or_query.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=force_join_keyboard()
        )
    else:
        await update_or_query.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=force_join_keyboard()
        )


async def verify_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not FORCE_JOIN_CHANNEL and not FORCE_JOIN_GROUP:
        await query.answer("Force-join configure nahi hai.", show_alert=True)
        return
    if await is_member(context.bot, user.id):
        await query.answer("Channel verified!")
        await query.edit_message_text(
            "✅ Channel aur group verified!\n\nCommands: /num, /info, /ifsc\n/start se bot shuru karo."
        )
    else:
        await query.answer("Membership abhi confirm nahi hui. Join request approve hone ke baad Verify dabao.", show_alert=True)


def home_text(user):
    name = esc(user.first_name or "there")
    return (
        f"✨ <b>{BOT_NAME}</b>\n{ACCENT}\n\n"
        f"👋 Welcome, <b>{name}</b>\n\n"
        "Use these commands:\n"
        "/num — Phone number metadata\n"
        "/info — Public Telegram info\n"
        "/ifsc — IFSC bank branch lookup"
    )


async def log_to_channel(context, message):
    if not LOG_CHANNEL_ID:
        return
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=message[:4000],
            parse_mode=None,
        )
    except Exception as exc:
        print(f"Log channel error: {exc}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_state.pop(chat_id, None)
    if (FORCE_JOIN_CHANNEL or FORCE_JOIN_GROUP) and not await is_member(context.bot, user.id):
        await send_force_join(update, user)
        return
    await update.message.reply_text(home_text(user), parse_mode=ParseMode.HTML)
    if user and user.id not in known_users:
        known_users.add(user.id)
        save_known_users()
        await log_to_channel(
            context,
            f"NEW USER\nName: {user.full_name}\nID: {user.id}\n"
            f"Username: @{user.username or 'none'}\n"
            f"Time: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
        )


async def verify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not FORCE_JOIN_CHANNEL and not FORCE_JOIN_GROUP:
        await update.message.reply_text("⚠️ Force-join is not configured by admin.")
    elif await is_member(context.bot, user.id):
        await update.message.reply_text("✅ Channel aur group verified!\n\nCommands: /num, /info, /ifsc\n/start se bot shuru karo.")
    else:
        await send_force_join(update, user)


async def require_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if (FORCE_JOIN_CHANNEL or FORCE_JOIN_GROUP) and user and not await is_member(context.bot, user.id):
        await send_force_join(update, user)
        return False
    return True


async def choose_tool(update: Update, context: ContextTypes.DEFAULT_TYPE, tool_key: str):
    user = update.effective_user
    if not await require_membership(update, context):
        return
    cfg = TOOLS[tool_key]
    user_state[update.effective_chat.id] = tool_key
    await update.message.reply_text(
        f"{cfg['name']}\n{ACCENT}\n\n{esc(cfg['description'])}\n\n"
        f"➡️ {esc(cfg['prompt'])}\n\nSend /cancel to stop.",
        parse_mode=ParseMode.HTML,
    )


async def numinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await choose_tool(update, context, "num_info")


async def ifsc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await choose_tool(update, context, "ifsc_info")


async def tginfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await choose_tool(update, context, "tg_info")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_membership(update, context):
        return
    user_state.pop(update.effective_chat.id, None)
    await update.message.reply_text("Cancelled. Use /num, /info, or /ifsc to start again.")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    tool_key = user_state.get(chat_id)

    if (FORCE_JOIN_CHANNEL or FORCE_JOIN_GROUP) and not await is_member(context.bot, user.id):
        user_state.pop(chat_id, None)
        await send_force_join(update, user)
        return

    if not tool_key:
        await update.message.reply_text(
            "Command choose karo: /num, /info, ya /ifsc.",
        )
        return

    cfg = TOOLS[tool_key]
    query_text = (update.message.text or "").strip()
    if not query_text or len(query_text) > 200:
        await update.message.reply_text("Please send a valid query (maximum 200 characters).")
        return

    if tool_key == "num_info":
        try:
            parsed = phonenumbers.parse(query_text, None)
            result = {
                "input": query_text,
                "international_format": phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
                ),
                "national_format": phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.NATIONAL
                ),
                "region": geocoder.description_for_number(parsed, "en") or "Unknown",
                "carrier_metadata": carrier.name_for_number(parsed, "en") or "Unknown",
                "possible_number": phonenumbers.is_possible_number(parsed),
                "valid_numbering_format": phonenumbers.is_valid_number(parsed),
                "note": "This does not identify the subscriber or confirm that the number is active.",
            }
            pretty = json.dumps(result, indent=2, ensure_ascii=False)
            user_results.setdefault(chat_id, []).append({
                "tool": cfg["name"],
                "query": query_text,
                "result": pretty,
            })
            user_results[chat_id] = user_results[chat_id][-10:]
            await update.message.reply_text(
                f"✅ <b>RESULT READY</b>\\n{ACCENT}\\n\\n"
                f"🧰 Tool: <b>{esc(cfg['name'])}</b>\\n"
                f"<pre>{esc(pretty[:3000])}</pre>",
                parse_mode=ParseMode.HTML,
            )
        except phonenumbers.NumberParseException:
            await update.message.reply_text(
                "⚠️ Number samajh nahi aaya. Country code ke saath bhejo, jaise +919876543210."
            )
        finally:
            user_state.pop(chat_id, None)
        return

    # URL-encode query input before inserting it into the configured endpoint.
    url = cfg["url"].format(q=quote(query_text, safe=""))
    loading = await update.message.reply_text(
        "⏳ <b>Processing your request…</b>\n<i>Please wait a moment.</i>",
        parse_mode=ParseMode.HTML,
    )

    try:
        response = await asyncio.to_thread(requests.get, url, timeout=20)
        response.raise_for_status()
        try:
            data = response.json()
            pretty = json.dumps(clean_response(data), indent=2, ensure_ascii=False)
        except (ValueError, json.JSONDecodeError):
            pretty = response.text

        pretty = pretty[:3000]
        user_results.setdefault(chat_id, []).append({
            "tool": cfg["name"],
            "query": query_text,
            "result": pretty,
        })
        user_results[chat_id] = user_results[chat_id][-10:]

        await loading.edit_text(
            f"✅ <b>RESULT READY</b>\n{ACCENT}\n\n"
            f"🧰 Tool: <b>{esc(cfg['name'])}</b>\n"
            f"🔎 Query: <code>{esc(query_text)}</code>\n\n"
            f"<pre>{esc(pretty)}</pre>",
            parse_mode=ParseMode.HTML,
        )
        await log_to_channel(
            context,
            f"SEARCH\nUser: {user.full_name if user else 'Unknown'}\n"
            f"User ID: {user.id if user else 'Unknown'}\n"
            f"Tool: {cfg['name']}\nQuery: {query_text}\n"
            f"Time: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
        )
    except requests.exceptions.Timeout:
        await loading.edit_text(
            "⌛ <b>Request timed out</b>\nPlease try again in a little while.",
            parse_mode=ParseMode.HTML,
        )
    except requests.exceptions.RequestException:
        await loading.edit_text(
            "⚠️ <b>Service temporarily unavailable</b>\nPlease try again later.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        await loading.edit_text(
            "⚠️ <b>Something went wrong.</b>\nPlease try again.",
            parse_mode=ParseMode.HTML,
        )
    finally:
        user_state.pop(chat_id, None)


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.reply_text(
        f"🆔 Your Telegram ID: <code>{update.effective_chat.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.reply_text(
        f"📊 <b>{BOT_NAME} STATS</b>\n{ACCENT}\n\n"
        f"👥 Users seen this run: <b>{len(known_users)}</b>\n"
        f"📚 Chats with saved results: <b>{len(user_results)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ This command is available to the bot admin only.")
        return

    message = " ".join(context.args).strip()
    if not message:
        await update.message.reply_text(
            "📣 <b>Broadcast</b>\\n\\nUse: <code>/broadcast Your message here</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    recipients = list(known_users)
    status = await update.message.reply_text(
        f"📣 Sending broadcast to <b>{len(recipients)}</b> saved users…",
        parse_mode=ParseMode.HTML,
    )
    sent = failed = 0
    for chat_id in recipients:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as exc:
            failed += 1
            print(f"Broadcast failed for {chat_id}: {exc}")

    await status.edit_text(
        f"✅ <b>Broadcast finished</b>\\n{ACCENT}\\n\\n"
        f"📨 Sent: <b>{sent}</b>\\n⚠️ Failed: <b>{failed}</b>",
        parse_mode=ParseMode.HTML,
    )


async def setup_command_scopes(app):
    # Regular users see only user commands; each configured admin sees the full list.
    await app.bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in ADMIN_IDS:
        try:
            await app.bot.set_my_commands(
                ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception as exc:
            print(f"Could not set admin command menu for {admin_id}: {exc}")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in your environment.")

    app = ApplicationBuilder().token(token).post_init(setup_command_scopes).build()
    app.add_handler(CallbackQueryHandler(verify_join_callback, pattern=r"^verify_join$"))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify_cmd))
    app.add_handler(CommandHandler("num", numinfo_cmd))
    app.add_handler(CommandHandler("numinfo", numinfo_cmd))
    app.add_handler(CommandHandler("info", tginfo_cmd))
    app.add_handler(CommandHandler("tginfo", tginfo_cmd))
    app.add_handler(CommandHandler("ifsc", ifsc_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print(f"{BOT_NAME} command-based bot is starting…")
    app.run_polling()


if __name__ == "__main__":
    main()
