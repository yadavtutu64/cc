#!/usr/bin/env python3
"""
ToppersWisdom Batch & HTML Exporter Telegram Bot
------------------------------------------------
Commands:
  /start or /help  - Show help & instructions
  /batchid         - Get list of all available Batches/Courses with their IDs
  /batchidhtml <id> - Fetch all topics, classes, videos & PDFs for a batch ID and generate/send an HTML file

You can also run this script directly from terminal:
  python bot.py --list
  python bot.py --html <batch_id>
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
from typing import Dict, List, Any, Optional

# Global API Configuration
USER_ID = "69facf90491695c542780262"
BASE_URL = "https://node.topperswisdom.com/api"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

def http_get(url: str) -> Any:
    """Helper to perform HTTP GET request with timeouts and headers."""
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode('utf-8')
            return json.loads(data)
    except Exception as e:
        print(f"[Error] HTTP GET failed for {url}: {e}")
        return None

def get_batches() -> List[Dict[str, Any]]:
    """Fetch active courses/batches."""
    url = f"{BASE_URL}/courses/active?userId={USER_ID}"
    res = http_get(url)
    if not res:
        return []
    
    courses = []
    if isinstance(res, list):
        courses = res
    elif isinstance(res, dict):
        courses = res.get("data") or res.get("courses") or []
    
    normalized = []
    for c in courses:
        cid = str(c.get("id") or c.get("_id") or c.get("courseId") or "")
        title = c.get("title") or c.get("name") or c.get("courseName") or "Untitled Batch"
        price = c.get("price") or c.get("discountPrice") or 0
        banner = c.get("banner") or c.get("image") or ""
        if cid:
            normalized.append({
                "id": cid,
                "title": title,
                "price": price,
                "banner": banner,
                "raw": c
            })
    return normalized

def get_topics(batch_id: str) -> List[Dict[str, Any]]:
    """Fetch topics for a batch ID."""
    url = f"{BASE_URL}/topic-and-section?courseId={batch_id}&userId={USER_ID}"
    res = http_get(url)
    if not res:
        return []
    
    topics = []
    if isinstance(res, list):
        topics = res
    elif isinstance(res, dict):
        data = res.get("data")
        if isinstance(data, list):
            topics = data
        elif isinstance(data, dict):
            topics = data.get("topics") or data.get("sections") or []
        elif "topics" in res and isinstance(res["topics"], list):
            topics = res["topics"]
        elif "sections" in res and isinstance(res["sections"], list):
            for sec in res["sections"]:
                if isinstance(sec, dict) and "topics" in sec:
                    topics.extend(sec["topics"])
    
    normalized = []
    for t in topics:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or t.get("_id") or t.get("topicId") or "")
        name = t.get("name") or t.get("topicName") or t.get("title") or "Untitled Topic"
        if tid:
            normalized.append({
                "id": tid,
                "name": name,
                "raw": t
            })
    return normalized

def get_classes(batch_id: str, topic_id: str) -> List[Dict[str, Any]]:
    """Fetch video classes for a topic inside a batch."""
    url = f"{BASE_URL}/topics/{topic_id}/classes?courseId={batch_id}&userId={USER_ID}"
    res = http_get(url)
    if not res:
        return []
    
    classes = []
    if isinstance(res, list):
        classes = res
    elif isinstance(res, dict):
        data = res.get("data")
        if isinstance(data, list):
            classes = data
        elif isinstance(data, dict):
            classes = data.get("classes") or data.get("data") or []
        elif "classes" in res and isinstance(res["classes"], list):
            classes = res["classes"]
    
    normalized = []
    for cls in classes:
        if not isinstance(cls, dict):
            continue
        clid = str(cls.get("id") or cls.get("_id") or cls.get("classId") or "")
        title = cls.get("title") or cls.get("name") or cls.get("className") or "Untitled Class"
        link = cls.get("link") or cls.get("class_link") or cls.get("video_url") or cls.get("url") or ""
        teacher = cls.get("teacherName") or cls.get("teacher_name") or "Toppers Faculty"
        
        # Extract PDFs
        pdfs = []
        raw_pdf = cls.get("classPdf") or cls.get("class_pdf") or cls.get("pdf")
        if isinstance(raw_pdf, list):
            for item in raw_pdf:
                if isinstance(item, dict):
                    pdfs.append({"title": item.get("title", "Class PDF"), "url": item.get("url", "")})
                elif isinstance(item, str):
                    pdfs.append({"title": "Class PDF", "url": item})
        elif isinstance(raw_pdf, str) and raw_pdf.strip():
            pdfs.append({"title": "Class PDF", "url": raw_pdf})
        elif cls.get("pdf_link") or cls.get("pdfUrl"):
            pdfs.append({"title": "Class PDF", "url": cls.get("pdf_link") or cls.get("pdfUrl")})

        normalized.append({
            "id": clid,
            "title": title,
            "link": link,
            "teacher": teacher,
            "pdfs": pdfs,
            "raw": cls
        })
    return normalized

from concurrent.futures import ThreadPoolExecutor

def generate_batch_html(batch_id: str) -> tuple[str, str, int]:
    """
    Fetch all details for a batch and generate a beautiful standalone HTML file.
    Returns (filename, batch_title, total_videos)
    """
    batches = get_batches()
    batch_info = next((b for b in batches if b["id"] == batch_id), None)
    batch_title = batch_info["title"] if batch_info else f"Batch {batch_id}"

    topics = get_topics(batch_id)
    
    all_content = []
    total_videos = 0

    # Parallel fetch classes for each topic
    def fetch_topic_classes(topic):
        classes = get_classes(batch_id, topic["id"])
        return {
            "topic": topic,
            "classes": classes
        }

    with ThreadPoolExecutor(max_workers=10) as executor:
        all_content = list(executor.map(fetch_topic_classes, topics))

    for item in all_content:
        total_videos += len(item["classes"])

    # Generate Responsive Dark/Light Styled HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{batch_title} - Classes & Materials</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{
            background-color: #0f172a;
            color: #f8fafc;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        .glass-card {{
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
    </style>
</head>
<body class="min-h-screen p-4 md:p-8">
    <div class="max-w-5xl mx-auto space-y-8">
        <!-- Header -->
        <header class="glass-card p-6 md:p-8 rounded-3xl shadow-2xl border-b border-blue-500/20">
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <span class="px-3 py-1 text-xs font-bold uppercase tracking-wider bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded-full">
                        Batch Export ID: {batch_id}
                    </span>
                    <h1 class="text-2xl md:text-3xl font-extrabold text-white mt-2">
                        {batch_title}
                    </h1>
                </div>
                <div class="flex items-center gap-4 text-sm font-semibold text-slate-400">
                    <span class="px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-700">
                        📚 {len(topics)} Topics
                    </span>
                    <span class="px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-700">
                        🎬 {total_videos} Videos
                    </span>
                </div>
            </div>
        </header>

        <!-- Topics & Classes -->
        <main class="space-y-6">
"""

    for idx, item in enumerate(all_content, 1):
        top = item["topic"]
        cls_list = item["classes"]
        
        html_content += f"""
            <section class="glass-card rounded-2xl p-6 space-y-4">
                <div class="flex items-center justify-between border-b border-slate-700/60 pb-3">
                    <h2 class="text-lg font-bold text-blue-400 flex items-center gap-2">
                        <span>#{idx}</span>
                        <span>{top['name']}</span>
                    </h2>
                    <span class="text-xs bg-slate-800 px-2.5 py-1 rounded-lg text-slate-400 border border-slate-700">
                        {len(cls_list)} Classes
                    </span>
                </div>
                <div class="grid grid-cols-1 gap-3">
"""
        if not cls_list:
            html_content += """
                    <p class="text-xs text-slate-500 italic p-3">No classes available in this topic.</p>
"""
        else:
            for c_idx, cls in enumerate(cls_list, 1):
                video_url = cls['link']
                html_content += f"""
                    <div class="p-4 rounded-xl bg-slate-900/80 border border-slate-800 hover:border-blue-500/40 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4">
                        <div class="space-y-1">
                            <div class="text-sm font-semibold text-slate-200">
                                {c_idx}. {cls['title']}
                            </div>
                            <div class="text-xs text-slate-400 flex items-center gap-3">
                                <span>👨‍🏫 {cls['teacher']}</span>
                            </div>
                        </div>

                        <div class="flex items-center gap-2 flex-wrap">
"""
                if video_url:
                    html_content += f"""
                            <a href="{video_url}" target="_blank" class="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition-all flex items-center gap-1 shadow-md shadow-blue-600/20">
                                ▶ Watch Video
                            </a>
"""
                for pdf in cls['pdfs']:
                    if pdf['url']:
                        html_content += f"""
                            <a href="{pdf['url']}" target="_blank" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition-all flex items-center gap-1 shadow-md shadow-emerald-600/20">
                                📄 {pdf['title']}
                            </a>
"""
                html_content += """
                        </div>
                    </div>
"""
        html_content += """
                </div>
            </section>
"""

    html_content += f"""
        </main>
        
        <footer class="text-center text-xs text-slate-500 py-6 border-t border-slate-800">
            Exported via ToppersWisdom Bot &bull; {time.strftime('%Y-%m-%d %H:%M:%S')}
        </footer>
    </div>
</body>
</html>
"""

    filename = f"batch_{batch_id}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    return filename, batch_title, total_videos

# TELEGRAM BOT HANDLERS USING TELEBOT (pyTelegramBotAPI) OR TELEGRAM HTTP API
def send_telegram_message(chat_id: int | str, text: str, parse_mode: str = "HTML"):
    """Send text message to Telegram Chat."""
    if not BOT_TOKEN:
        print("[Warning] BOT_TOKEN is not set!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers=HEADERS, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[Error] Failed to send telegram message: {e}")

def send_telegram_document(chat_id: int | str, file_path: str, caption: str = ""):
    """Send file document to Telegram Chat using multipart/form-data."""
    if not BOT_TOKEN or not os.path.exists(file_path):
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    
    with open(file_path, "rb") as f:
        file_content = f.read()

    filename = os.path.basename(file_path)

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f'Content-Type: text/html\r\n\r\n'
    ).encode('utf-8') + file_content + f"\r\n--{boundary}--\r\n".encode('utf-8')

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    }

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"[Success] HTML Document sent to {chat_id}")
    except Exception as e:
        print(f"[Error] Failed to send document: {e}")

def run_bot():
    """Poll Telegram API for updates and handle commands."""
    if not BOT_TOKEN:
        print("=====================================================")
        print("⚠️ BOT_TOKEN variable missing!")
        print("Set your bot token in env or bot.py:")
        print("   export BOT_TOKEN='your_telegram_bot_token'")
        print("   python bot.py")
        print("=====================================================")
        return

    print("🤖 ToppersWisdom Telegram Bot Started! Listening for messages...")
    offset = 0

    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
            res = http_get(url)
            if res and res.get("ok"):
                updates = res.get("result", [])
                for update in updates:
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    text = message.get("text", "").strip()
                    chat_id = message.get("chat", {}).get("id")

                    if not chat_id or not text:
                        continue

                    print(f"Received command: '{text}' from chat_id: {chat_id}")

                    # /start or /help
                    if text.startswith("/start") or text.startswith("/help"):
                        msg = (
                            "✨ <b>Welcome to ToppersWisdom Batch Bot!</b>\n\n"
                            "Available Commands:\n"
                            "🔹 <code>/batchid</code> - Get list of all available Batches & Batch IDs\n"
                            "🔹 <code>/batchidhtml &lt;batch_id&gt;</code> - Generate & Download HTML file with topics, videos & PDFs\n\n"
                            "<i>Example:</i> <code>/batchidhtml 6752f9b12a80c5f49d2ed123</code>"
                        )
                        send_telegram_message(chat_id, msg)

                    # /batchid
                    elif text.startswith("/batchid") and not text.startswith("/batchidhtml"):
                        send_telegram_message(chat_id, "⏳ Fetching active batches list...")
                        batches = get_batches()
                        if not batches:
                            send_telegram_message(chat_id, "❌ No active batches found.")
                        else:
                            msg = f"<b>📦 Available Batches ({len(batches)}):</b>\n\n"
                            for b in batches:
                                msg += (
                                    f"🎓 <b>{b['title']}</b>\n"
                                    f"🔑 ID: <code>{b['id']}</code>\n"
                                    f"👉 Export HTML: <code>/batchidhtml_{b['id']}</code>\n\n"
                                )
                            send_telegram_message(chat_id, msg)

                    # /batchidhtml or /batchidhtml_<id> or /batchidhtml <id>
                    elif text.startswith("/batchidhtml"):
                        parts = text.split()
                        batch_id = ""
                        if "_" in text:
                            batch_id = text.split("_")[-1].strip()
                        elif len(parts) > 1:
                            batch_id = parts[1].strip()

                        if not batch_id:
                            send_telegram_message(chat_id, "⚠️ Please provide a batch ID.\nUsage: <code>/batchidhtml &lt;batch_id&gt;</code>")
                            continue

                        send_telegram_message(chat_id, f"⚡ Fetching topics and generating HTML for batch ID <code>{batch_id}</code>...")
                        try:
                            filename, title, count = generate_batch_html(batch_id)
                            caption = f"✅ <b>{title}</b>\n🎬 Total Classes: {count}\n📂 File: {filename}"
                            send_telegram_document(chat_id, filename, caption)
                        except Exception as e:
                            send_telegram_message(chat_id, f"❌ Failed to generate HTML: {str(e)}")

        except Exception as e:
            print(f"Polling loop error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    if "--list" in sys.argv:
        print("Fetching batches...")
        batches = get_batches()
        for b in batches:
            print(f"ID: {b['id']} | Title: {b['title']}")
    elif "--html" in sys.argv:
        idx = sys.argv.index("--html")
        if idx + 1 < len(sys.argv):
            bid = sys.argv[idx + 1]
            fn, title, cnt = generate_batch_html(bid)
            print(f"Generated {fn} for '{title}' ({cnt} classes)")
        else:
            print("Please specify a batch ID.")
    else:
        run_bot()
