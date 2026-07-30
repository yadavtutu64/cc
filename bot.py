import os
import sys
import time
import logging
import subprocess
import requests
from telebot import TeleBot, types

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
ADMIN_ID = os.getenv("ADMIN_ID")  # Optional Telegram numeric User ID for security restriction

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN environment variable is not set!")
    print("Please set BOT_TOKEN in Railway or your environment variables.")
    sys.exit(1)

bot = TeleBot(BOT_TOKEN)

# Process tracking dictionary: { filename: { process, log_path, pid, start_time } }
RUNNING_PROCESSES = {}
LOGS_DIR = os.path.join(os.getcwd(), "bot_logs")
os.makedirs(LOGS_DIR, exist_ok=True)


def is_admin(message):
    """Check if sender is authorized admin if ADMIN_ID is set."""
    if not ADMIN_ID:
        return True
    return str(message.from_user.id) == str(ADMIN_ID)


def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_stats = types.KeyboardButton("📊 Visitor Stats")
    btn_visitors = types.KeyboardButton("👥 Recent Visitors")
    btn_files = types.KeyboardButton("📁 List Files")
    btn_status = types.KeyboardButton("⚡ Running Tasks")
    btn_help = types.KeyboardButton("❓ Help")
    markup.add(btn_stats, btn_visitors, btn_files, btn_status, btn_help)
    return markup


@bot.message_handler(commands=['start'])
def send_welcome(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied: You are not authorized to control this admin panel.")
        return

    text = (
        "🚀 *Next Toppers Python & Admin Bot Control*\n\n"
        "Welcome! You can upload `.py` files and execute them directly.\n\n"
        "📥 *How to upload & run a script:*\n"
        "1. Simply upload any `.py` file to this chat.\n"
        "2. Send `/python filename.py` to execute it.\n\n"
        "*Available Commands:*\n"
        "• `/python <file.py>` - Run a Python script\n"
        "• `/stop <file.py>` - Stop a running script\n"
        "• `/logs <file.py>` - View logs for a script\n"
        "• 📁 /files - List all `.py` files\n"
        "• ⚡ /status - Active running processes\n"
        "• 📊 /stats - Live visitor statistics\n"
        "• 👥 /visitors - View recent visitors\n"
        "• 🚫 `/block <user_id>` - Block a user\n"
        "• ✅ `/unblock <user_id>` - Unblock a user\n"
        "• ❓ /help - Complete guide"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_admin_keyboard())


@bot.message_handler(content_types=['document'])
def handle_file_upload(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    doc = message.document
    file_name = doc.file_name

    if not file_name:
        bot.reply_to(message, "⚠️ Invalid document received.")
        return

    if not file_name.endswith('.py') and not file_name.endswith('.txt'):
        bot.reply_to(message, f"⚠️ Please upload a `.py` Python file. Received: `{file_name}`", parse_mode="Markdown")
        return

    try:
        status_msg = bot.reply_to(message, f"⏳ Downloading `{file_name}`...", parse_mode="Markdown")
        file_info = bot.get_file(doc.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        save_path = os.path.join(os.getcwd(), file_name)
        with open(save_path, 'wb') as f:
            f.write(downloaded_file)

        reply_text = (
            f"✅ *Python File Saved Successfully!*\n\n"
            f"📄 *File Name:* `{file_name}`\n"
            f"📦 *Size:* `{len(downloaded_file)} bytes`\n"
            f"📂 *Location:* `{save_path}`\n\n"
            f"🚀 *To execute this file now, send:*\n"
            f"`/python {file_name}`"
        )
        bot.edit_message_text(reply_text, message.chat.id, status_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error saving uploaded file: {e}")
        bot.reply_to(message, f"❌ Failed to save file: `{e}`", parse_mode="Markdown")


@bot.message_handler(commands=['python', 'run'])
def run_python_script(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "⚠️ *Usage:* `/python <filename.py>`\n\n*Example:* `/python bot.py` or `/python script.py`", parse_mode="Markdown")
        return

    file_name = args[1].strip()
    if not file_name.endswith('.py'):
        file_name += '.py'

    file_path = os.path.join(os.getcwd(), file_name)

    if not os.path.exists(file_path):
        bot.reply_to(message, f"❌ File `{file_name}` not found in directory.\nPlease upload `{file_name}` first or check `/files`.", parse_mode="Markdown")
        return

    # Check if script is already running
    if file_name in RUNNING_PROCESSES:
        proc_info = RUNNING_PROCESSES[file_name]
        proc = proc_info.get("process")
        if proc and proc.poll() is None:
            bot.reply_to(message, f"⚠️ Script `{file_name}` is already running (PID: `{proc.pid}`).\nStopping old instance...", parse_mode="Markdown")
            try:
                proc.terminate()
                time.sleep(1)
            except Exception:
                pass

    log_path = os.path.join(LOGS_DIR, f"{file_name}.log")

    try:
        log_file = open(log_path, "w", encoding="utf-8")
        python_bin = sys.executable or "python3"

        # Spawn Python Process
        proc = subprocess.Popen(
            [python_bin, "-u", file_path],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd()
        )

        RUNNING_PROCESSES[file_name] = {
            "process": proc,
            "log_path": log_path,
            "pid": proc.pid,
            "start_time": time.time()
        }

        # Wait 2 seconds to check status
        time.sleep(2)
        poll_status = proc.poll()

        if poll_status is None:
            output_snippet = ""
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    output_snippet = f.read()[-600:]

            msg = (
                f"🚀 *Python Script Started!*\n\n"
                f"📄 *File:* `{file_name}`\n"
                f"🆔 *PID:* `{proc.pid}`\n"
                f"⚡ *Status:* Running in Background\n\n"
                f"📋 *Output Log:* \n```\n{output_snippet.strip() or 'Script running...'}\n```\n\n"
                f"💡 Commands:\n"
                f"• `/logs {file_name}` - View live logs\n"
                f"• `/stop {file_name}` - Terminate script"
            )
            bot.reply_to(message, msg, parse_mode="Markdown")
        else:
            output_snippet = ""
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    output_snippet = f.read()[-2000:]

            status_txt = "✅ Executed Successfully" if poll_status == 0 else f"❌ Failed (Exit code {poll_status})"
            msg = (
                f"*{status_txt}*\n\n"
                f"📄 *File:* `{file_name}`\n\n"
                f"📋 *Output Log:*\n```\n{output_snippet.strip() or 'No output produced.'}\n```"
            )
            bot.reply_to(message, msg, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Failed to execute Python script {file_name}: {e}")
        bot.reply_to(message, f"❌ Failed to run `{file_name}`:\n`{e}`", parse_mode="Markdown")


@bot.message_handler(commands=['stop', 'kill'])
def stop_python_script(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "⚠️ Usage: `/stop <filename.py>`", parse_mode="Markdown")
        return

    file_name = args[1].strip()
    if not file_name.endswith('.py'):
        file_name += '.py'

    if file_name not in RUNNING_PROCESSES:
        bot.reply_to(message, f"ℹ️ Script `{file_name}` is not currently running.", parse_mode="Markdown")
        return

    proc_info = RUNNING_PROCESSES[file_name]
    proc = proc_info.get("process")

    try:
        if proc and proc.poll() is None:
            proc.terminate()
            time.sleep(1)
            if proc.poll() is None:
                proc.kill()
            del RUNNING_PROCESSES[file_name]
            bot.reply_to(message, f"🛑 Script `{file_name}` (PID `{proc.pid}`) has been stopped.", parse_mode="Markdown")
        else:
            del RUNNING_PROCESSES[file_name]
            bot.reply_to(message, f"ℹ️ Script `{file_name}` was already stopped.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error stopping process: `{e}`", parse_mode="Markdown")


@bot.message_handler(commands=['logs'])
def view_logs(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "⚠️ Usage: `/logs <filename.py>`", parse_mode="Markdown")
        return

    file_name = args[1].strip()
    if not file_name.endswith('.py'):
        file_name += '.py'

    log_path = os.path.join(LOGS_DIR, f"{file_name}.log")
    if not os.path.exists(log_path):
        bot.reply_to(message, f"ℹ️ No log file found for `{file_name}`.", parse_mode="Markdown")
        return

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            logs = f.read()[-3000:]  # get last 3000 chars

        if not logs.strip():
            logs = "Log file is empty."

        bot.reply_to(message, f"📋 *Logs for `{file_name}`:*\n\n```\n{logs}\n```", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error reading log file: `{e}`", parse_mode="Markdown")


@bot.message_handler(commands=['files', 'ls'])
@bot.message_handler(func=lambda msg: msg.text == "📁 List Files")
def list_files(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    py_files = [f for f in os.listdir(os.getcwd()) if f.endswith('.py')]

    if not py_files:
        bot.reply_to(message, "📂 No `.py` files found in root directory.", parse_mode="Markdown")
        return

    lines = ["📁 *Available Python Files:*\n"]
    for idx, name in enumerate(py_files, 1):
        running = "⚡ (RUNNING)" if name in RUNNING_PROCESSES and RUNNING_PROCESSES[name]["process"].poll() is None else ""
        lines.append(f"{idx}. `{name}` {running}")

    lines.append("\n💡 *To run a file:* `/python filename.py`")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=['status'])
@bot.message_handler(func=lambda msg: msg.text == "⚡ Running Tasks")
def status_running(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔ Access Denied.")
        return

    active = []
    for name, info in list(RUNNING_PROCESSES.items()):
        proc = info["process"]
        if proc.poll() is None:
            uptime = int(time.time() - info["start_time"])
            active.append(f"• `{name}` | PID: `{proc.pid}` | Uptime: `{uptime}s`")
        else:
            del RUNNING_PROCESSES[name]

    if not active:
        bot.reply_to(message, "ℹ️ No background Python processes currently running.", parse_mode="Markdown")
        return

    msg = "⚡ *Active Running Processes:*\n\n" + "\n".join(active)
    bot.reply_to(message, msg, parse_mode="Markdown")


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
        "📖 *Admin & Python Bot Help Guide*\n\n"
        "📥 *Executing Custom Scripts:*\n"
        "1. Upload any `.py` file to this chat.\n"
        "2. Send `/python <file.py>` to run it.\n"
        "3. Use `/logs <file.py>` to check logs.\n"
        "4. Use `/stop <file.py>` to stop execution.\n\n"
        "📊 *App Analytics & Security:*\n"
        "• `/stats` - Total visitors, mobile/desktop stats & devtools alert.\n"
        "• `/visitors` - List recent 10 visitors.\n"
        "• `/block <user_id>` - Block malicious user.\n"
        "• `/unblock <user_id>` - Unblock user.\n\n"
        "⚙️ *Railway Environment Variables:*\n"
        "`BOT_TOKEN`: Telegram Bot Token from @BotFather\n"
        "`APP_URL`: Railway app URL (e.g. https://your-app.up.railway.app)\n"
        "`ADMIN_ID`: (Optional) Your Telegram numeric ID for protection\n"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")


if __name__ == "__main__":
    logging.info("🤖 Starting Admin Telegram Bot with Python Execution Engine...")
    bot.infinity_polling(skip_pending=True)
