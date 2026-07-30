import os
import sys
import logging
import requests
from telebot import TeleBot, types

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
ADMIN_ID = os.getenv("ADMIN_ID")  # Optional Telegram numeric User ID for authorization security

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN environment variable is not set!")
    print("Please set BOT_TOKEN in Railway or your environment variables.")
    sys.exit(1)

bot = TeleBot(BOT_TOKEN)


def is_admin(message):
    """Check if sender is authorized admin if ADMIN_ID is set."""
    if not ADMIN_ID:
        return True
    return str(message.from_user.id) == str(ADMIN_ID)


def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_stats = types.KeyboardButton("📊 Visitor Stats")
    btn_visitors = types.KeyboardButton("👥 Recent Visitors")
    btn_help = types.KeyboardButton("❓ Help")
    markup.add(btn_stats, btn_visitors, btn_help)
    return markup


@bot.message_handler(commands=['start'])
def send_welcome(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied: You are not authorized to control this admin panel.")
        return

    text = (
        "🚀 *Next Toppers Admin Control Bot*\n\n"
        "Welcome! You can monitor and control your application directly from Telegram.\n\n"
        "*Available Commands:*\n"
        "• 📊 /stats - Live visitor statistics\n"
        "• 👥 /visitors - View recent visitors list\n"
        "• 🚫 `/block <user_id>` - Block a specific user\n"
        "• ✅ `/unblock <user_id>` - Unblock a user\n"
        "• ❓ /help - Usage guide\n\n"
        f"🔗 *Connected App URL:* `{APP_URL}`"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_admin_keyboard())


@bot.message_handler(commands=['stats'])
@bot.message_handler(func=lambda msg: msg.text == "📊 Visitor Stats")
def get_stats(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    try:
        res = requests.get(f"{APP_URL}/api/admin/visitors", timeout=10)
        data = res.json()
        visitors = data.get("visitors", [])

        total = len(visitors)
        blocked = sum(1 for v in visitors if v.get("blocked"))
        desktop = sum(1 for v in visitors if "Desktop" in v.get("deviceType", ""))
        mobile = sum(1 for v in visitors if "Mobile" in v.get("deviceType", ""))
        devtools_open = sum(1 for v in visitors if v.get("devtoolsStatus") == "open")

        text = (
            "📊 *Next Toppers Analytics Summary*\n\n"
            f"👤 *Total Tracked Visitors:* `{total}`\n"
            f"📱 *Mobile Users:* `{mobile}`\n"
            f"💻 *Desktop Users:* `{desktop}`\n"
            f"🔍 *DevTools Detected:* `{devtools_open}`\n"
            f"🚫 *Blocked Users:* `{blocked}`\n"
        )
        bot.reply_to(message, text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error fetching stats: {e}")
        bot.reply_to(message, f"❌ Failed to connect to server at `{APP_URL}`.\nError: `{e}`", parse_mode="Markdown")


@bot.message_handler(commands=['visitors'])
@bot.message_handler(func=lambda msg: msg.text == "👥 Recent Visitors")
def get_recent_visitors(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    try:
        res = requests.get(f"{APP_URL}/api/admin/visitors", timeout=10)
        data = res.json()
        visitors = data.get("visitors", [])

        if not visitors:
            bot.reply_to(message, "ℹ️ No visitor data found yet.")
            return

        # Get latest 10 visitors sorted by timestamp
        recent = sorted(visitors, key=lambda x: x.get("timestamp", ""), reverse=True)[:10]

        msg_lines = ["👥 *Recent 10 Visitors:*\n"]
        for idx, v in enumerate(recent, 1):
            uid = v.get("userId", "Unknown")
            dev = v.get("deviceType", "Unknown")
            os_name = v.get("os", "")
            browser = v.get("browser", "")
            status = "🚫 BLOCKED" if v.get("blocked") else "✅ ACTIVE"
            dt_status = "⚠️ DevTools Open" if v.get("devtoolsStatus") == "open" else "DevTools Closed"

            line = f"*{idx}. ID:* `{uid}`\n   Device: {dev} ({os_name}, {browser})\n   Status: {status} | {dt_status}\n"
            msg_lines.append(line)

        bot.reply_to(message, "\n".join(msg_lines), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error fetching visitors: {e}")
        bot.reply_to(message, f"❌ Error fetching visitor details from `{APP_URL}`.", parse_mode="Markdown")


@bot.message_handler(commands=['block'])
def block_user(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ Usage: `/block <user_id>`", parse_mode="Markdown")
        return

    target_id = args[1]
    try:
        res = requests.post(f"{APP_URL}/api/admin/block", json={"userId": target_id, "blocked": True}, timeout=10)
        if res.status_code == 200 and res.json().get("success"):
            bot.reply_to(message, f"🚫 User `{target_id}` has been successfully **BLOCKED**.", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ User `{target_id}` not found or error occurred.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error connecting to server: `{e}`", parse_mode="Markdown")


@bot.message_handler(commands=['unblock'])
def unblock_user(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ Usage: `/unblock <user_id>`", parse_mode="Markdown")
        return

    target_id = args[1]
    try:
        res = requests.post(f"{APP_URL}/api/admin/block", json={"userId": target_id, "blocked": False}, timeout=10)
        if res.status_code == 200 and res.json().get("success"):
            bot.reply_to(message, f"✅ User `{target_id}` has been successfully **UNBLOCKED**.", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ User `{target_id}` not found or error occurred.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error connecting to server: `{e}`", parse_mode="Markdown")


@bot.message_handler(commands=['help'])
@bot.message_handler(func=lambda msg: msg.text == "❓ Help")
def show_help(message):
    help_text = (
        "📖 *Admin Bot Help Guide*\n\n"
        "• `/stats` - View total visitors, mobile/desktop breakdown & devtools detection.\n"
        "• `/visitors` - List latest 10 visitor sessions.\n"
        "• `/block <user_id>` - Block a user from accessing app features.\n"
        "• `/unblock <user_id>` - Unblock a user.\n\n"
        "⚙️ *Railway Environment Variables:*\n"
        "`BOT_TOKEN`: Telegram Bot Token from @BotFather\n"
        "`APP_URL`: Domain URL of your deployed app (e.g. https://your-app.up.railway.app)\n"
        "`ADMIN_ID`: (Optional) Numerical Telegram User ID for security restriction\n"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")


if __name__ == "__main__":
    logging.info("🤖 Starting Admin Telegram Bot...")
    bot.infinity_polling(skip_pending=True)
