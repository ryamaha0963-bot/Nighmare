import os
import json
import html
import asyncio
from datetime import datetime
from urllib.parse import quote

import requests
import phonenumbers
from phonenumbers import geocoder, carrier
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
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


def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧰 Tools Hub", callback_data="tools"),
            InlineKeyboardButton("👤 My Profile", callback_data="profile"),
        ],
        [
            InlineKeyboardButton("📜 My Results", callback_data="my_results"),
            InlineKeyboardButton("ℹ️ About", callback_data="about"),
        ],
        [InlineKeyboardButton("🆘 Support", url=os.environ.get("SUPPORT_URL", "https://t.me/"))],
    ])


def tools_menu():
    rows = []
    row = []
    for key, cfg in TOOLS.items():
        row.append(InlineKeyboardButton(cfg["name"], callback_data=f"tool:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Home", callback_data="back")])
    return InlineKeyboardMarkup(rows)


def result_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔎 New Search", callback_data="tools"),
            InlineKeyboardButton("📜 My Results", callback_data="my_results"),
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="back")],
    ])


def home_text(user):
    name = esc(user.first_name or "there")
    return (
        f"✨ <b>{BOT_NAME} • PREMIUM HUB</b>\n"
        f"{ACCENT}\n\n"
        f"👋 Welcome, <b>{name}</b>\n"
        "Your clean, fast workspace for public information tools.\n\n"
        "╭─ <b>QUICK ACCESS</b>\n"
        "│ 🧰 Tools Hub — browse available tools\n"
        "│ 👤 My Profile — account overview\n"
        "│ 📜 My Results — recent searches\n"
        "╰──────────────────\n\n"
        "👇 <i>Choose an option below to continue.</i>"
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
    await update.message.reply_text(
        home_text(user),
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML,
    )
    if user and user.id not in known_users:
        known_users.add(user.id)
        save_known_users()
        await log_to_channel(
            context,
            f"NEW USER\nName: {user.full_name}\nID: {user.id}\n"
            f"Username: @{user.username or 'none'}\n"
            f"Time: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    user = query.from_user

    if data in ("back", "home"):
        user_state.pop(chat_id, None)
        await query.edit_message_text(
            home_text(user), reply_markup=main_menu(), parse_mode=ParseMode.HTML
        )
        return

    if data == "tools":
        user_state.pop(chat_id, None)
        await query.edit_message_text(
            f"🧰 <b>TOOLS HUB</b>\n{ACCENT}\n\nChoose a tool to continue.",
            reply_markup=tools_menu(),
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "profile":
        results = user_results.get(chat_id, [])
        username = f"@{esc(user.username)}" if user.username else "Not set"
        text = (
            f"👤 <b>MY PROFILE</b>\n{ACCENT}\n\n"
            f"🪪 Name: <b>{esc(user.full_name)}</b>\n"
            f"🆔 Telegram ID: <code>{user.id}</code>\n"
            f"🔗 Username: {username}\n"
            f"📊 Saved results: <b>{len(results)}</b>\n\n"
            "<i>Your recent results are stored in this bot session.</i>"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📜 My Results", callback_data="my_results")],
                [InlineKeyboardButton("⬅️ Home", callback_data="back")],
            ]),
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "about":
        await query.edit_message_text(
            f"💎 <b>ABOUT {BOT_NAME}</b>\n{ACCENT}\n\n"
            "A streamlined Telegram tools interface with fast navigation, "
            "readable results, and a compact history menu.\n\n"
            "🔐 Use tools only for information you are authorized to access.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧰 Open Tools", callback_data="tools")],
                [InlineKeyboardButton("⬅️ Home", callback_data="back")],
            ]),
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "my_results":
        results = user_results.get(chat_id, [])
        if not results:
            await query.edit_message_text(
                "📭 <b>No saved results yet</b>\n\nRun a tool first, and your latest results will appear here.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧰 Open Tools", callback_data="tools")],
                    [InlineKeyboardButton("⬅️ Home", callback_data="back")],
                ]),
                parse_mode=ParseMode.HTML,
            )
            return

        rows = []
        for index, item in enumerate(results, 1):
            label = f"{index}. {item['tool']} • {item['query']}"[:60]
            rows.append([InlineKeyboardButton(label, callback_data=f"view:{index-1}")])
        rows.append([InlineKeyboardButton("⬅️ Home", callback_data="back")])
        await query.edit_message_text(
            f"📜 <b>MY RESULTS</b> · {len(results)} saved\n{ACCENT}\n\nSelect a result:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith("view:"):
        try:
            index = int(data.split(":", 1)[1])
            item = user_results.get(chat_id, [])[index]
        except (ValueError, IndexError):
            await query.answer("Result not found", show_alert=True)
            return
        output = esc(item["result"][:3000])
        text = (
            f"📌 <b>{esc(item['tool'])}</b>\n{ACCENT}\n\n"
            f"🔎 Query: <code>{esc(item['query'])}</code>\n\n"
            f"<pre>{output}</pre>"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 New Search", callback_data="tools")],
                [InlineKeyboardButton("⬅️ Results List", callback_data="my_results")],
            ]),
            parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith("tool:"):
        tool_key = data.split(":", 1)[1]
        cfg = TOOLS.get(tool_key)
        if not cfg:
            await query.edit_message_text(
                "That tool is not available.", reply_markup=tools_menu()
            )
            return
        user_state[chat_id] = tool_key
        await query.edit_message_text(
            f"{cfg['name']}\n{ACCENT}\n\n"
            f"{esc(cfg['description'])}\n\n"
            f"➡️ {esc(cfg['prompt'])}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Tools Hub", callback_data="tools")],
                [InlineKeyboardButton("🏠 Home", callback_data="back")],
            ]),
            parse_mode=ParseMode.HTML,
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    tool_key = user_state.get(chat_id)

    if not tool_key:
        await update.message.reply_text(
            "👇 Open the tools hub first.",
            reply_markup=main_menu(),
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
                reply_markup=result_menu(),
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
            reply_markup=result_menu(),
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
            reply_markup=result_menu(),
            parse_mode=ParseMode.HTML,
        )
    except requests.exceptions.RequestException:
        await loading.edit_text(
            "⚠️ <b>Service temporarily unavailable</b>\nPlease try again later.",
            reply_markup=result_menu(),
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        await loading.edit_text(
            "⚠️ <b>Something went wrong.</b>\nPlease try again.",
            reply_markup=result_menu(),
            parse_mode=ParseMode.HTML,
        )
    finally:
        user_state.pop(chat_id, None)


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Your Telegram ID: <code>{update.effective_chat.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 <b>{BOT_NAME} STATS</b>\n{ACCENT}\n\n"
        f"👥 Users seen this run: <b>{len(known_users)}</b>\n"
        f"📚 Chats with saved results: <b>{len(user_results)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or ADMIN_ID == 0 or user.id != ADMIN_ID:
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


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in your environment.")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print(f"{BOT_NAME} premium bot is starting…")
    app.run_polling()


if __name__ == "__main__":
    main()
