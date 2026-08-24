#!/usr/bin/env python3
"""
=============================================================================
🤖 KGS 100 Latest Batches Scraper & Telegram Bot Automation
=============================================================================
Description:
- Fetches the latest 100 batches/courses from Khan Global Studies (KGS).
- Scrapes all classroom subjects, lessons, video details, and PDF notes.
- Saves formatted and aggregated data into `kgs100.json` (and `public/kgs100.json`).
- Exposes data for API consumption and sends daily updates to Telegram at 5:00 AM IST.

Usage:
  python3 bot.py                     # Fetch 100 batches immediately and save kgs100.json
  python3 bot.py --now               # Same as above (one-shot run)
  python3 bot.py --telegram          # Fetch and immediately send file & report to Telegram
  python3 bot.py --schedule          # Run 24/7 background scheduler (auto 5:00 AM IST daily)
  python3 bot.py --count 50          # Fetch custom number of batches (e.g. 50, 100)
  python3 bot.py --poll              # Start Telegram Bot command polling (/start, /update, /stats, /getjson)
=============================================================================
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import mimetypes
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import logging

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("KGSBot")

# IST Timezone (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Environment Variables & Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TARGET_COUNT = int(os.environ.get("BATCH_COUNT", "100"))
DAILY_UPDATE_HOUR_IST = int(os.environ.get("UPDATE_HOUR_IST", "5"))   # 5 AM IST
DAILY_UPDATE_MINUTE_IST = int(os.environ.get("UPDATE_MINUTE_IST", "0"))

# API URLs
COURSES_LIST_URL = "https://sahuvijay143.github.io/kgs_batch_list/New_Sunny.json"
CLASSROOM_BASE_URL = "https://sahukgs.vercel.app/api/classroom"
LESSON_BASE_URL = "https://sahukgs.vercel.app/api/lesson"
TODAY_BASE_URL = "https://sahukgs.vercel.app/api/today"
VIDEO_BASE_URL = "https://sahukgs.vercel.app/api/video"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
}

def make_request(url: str, headers: dict = None, timeout: int = 12, retries: int = 2):
    """Safely fetch JSON data from a URL with retries."""
    req_headers = DEFAULT_HEADERS.copy()
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers)
    
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    raw_data = response.read().decode('utf-8')
                    return json.loads(raw_data)
        except Exception as e:
            if attempt == retries:
                logger.debug(f"Failed to fetch {url}: {e}")
                return None
            time.sleep(0.5 * (attempt + 1))
    return None

def fetch_lesson_details(subject_id: int):
    """Fetch lesson details including videos and notes for a subject."""
    url = f"{LESSON_BASE_URL}/{subject_id}"
    data = make_request(url, timeout=10)
    
    if not data or not isinstance(data, dict):
        return {"videos": [], "notes": [], "teacher": None}
    
    videos = []
    notes = []
    
    # Process Videos
    raw_videos = data.get("videos", [])
    if isinstance(raw_videos, list):
        for v in raw_videos:
            if not isinstance(v, dict):
                continue
            videos.append({
                "id": v.get("id"),
                "name": v.get("name") or v.get("title") or "Class Lecture",
                "thumb": v.get("thumb") or "https://i.postimg.cc/jd5wqHJ3/logo.png",
                "published_at": v.get("published_at") or v.get("created_at"),
                "duration": v.get("duration"),
                "video_url": v.get("video_url"),
                "pdfs": v.get("pdfs", []) if isinstance(v.get("pdfs"), list) else [],
            })
            
    # Process Notes / PDFs
    raw_notes = data.get("notes", [])
    if isinstance(raw_notes, list):
        for n in raw_notes:
            if not isinstance(n, dict):
                continue
            notes.append({
                "id": n.get("id"),
                "name": n.get("name") or n.get("title") or "Classroom PDF Note",
                "pdf_url": n.get("video_url") or n.get("pdf_url") or n.get("url"),
                "published_at": n.get("published_at") or n.get("created_at"),
                "thumb": n.get("thumb") or "https://i.postimg.cc/jd5wqHJ3/logo.png",
            })
            
    return {
        "videos": videos,
        "notes": notes,
        "teacher": data.get("teacher"),
        "raw_name": data.get("name"),
    }

def fetch_course_full_data(course_raw: dict):
    """Fetch all subjects, lessons, videos, notes, and live classes for a single course."""
    course_id = course_raw.get("id")
    if not course_id:
        return None

    # Base Course Information
    course_info = {
        "id": course_id,
        "title": course_raw.get("title") or course_raw.get("name") or "KGS Preparation Batch",
        "category_id": course_raw.get("category_id"),
        "category_name": course_raw.get("category_name") or f"Category #{course_raw.get('category_id', 0)}",
        "start_at": course_raw.get("start_at"),
        "end_at": course_raw.get("end_at"),
        "price": course_raw.get("price", "Free"),
        "thumb": course_raw.get("image_thumb") or course_raw.get("image_large") or "https://i.postimg.cc/jd5wqHJ3/logo.png",
        "image_large": course_raw.get("image_large") or "https://i.postimg.cc/jd5wqHJ3/logo.png",
        "description": course_raw.get("description") or f"Official Khan Global Studies batch: {course_raw.get('title')}",
        "subjects": [],
        "live_classes": [],
        "stats": {
            "total_subjects": 0,
            "total_videos": 0,
            "total_notes": 0,
        }
    }

    # 1. Fetch Today / Live Classes
    today_url = f"{TODAY_BASE_URL}/{course_id}"
    today_data = make_request(today_url, timeout=8)
    if isinstance(today_data, list):
        course_info["live_classes"] = [
            {
                "id": tc.get("id"),
                "name": tc.get("name") or tc.get("title") or "Live Class",
                "thumb": tc.get("thumb") or "https://i.postimg.cc/jd5wqHJ3/logo.png",
                "published_at": tc.get("published_at") or tc.get("created_at"),
                "type": tc.get("type", "live"),
                "video_url": tc.get("video_url"),
            }
            for tc in today_data if isinstance(tc, dict)
        ]

    # 2. Fetch Classroom Subjects
    classroom_url = f"{CLASSROOM_BASE_URL}/{course_id}"
    classroom_data = make_request(classroom_url, timeout=10)
    
    subjects_list = []
    if isinstance(classroom_data, list):
        subjects_list = classroom_data
    elif isinstance(classroom_data, dict) and "classroom" in classroom_data:
        subjects_list = classroom_data.get("classroom", [])

    total_course_videos = 0
    total_course_notes = 0
    formatted_subjects = []

    # Fetch lessons for each subject concurrently if multiple subjects exist
    if subjects_list:
        with ThreadPoolExecutor(max_workers=8) as sub_executor:
            future_to_subject = {
                sub_executor.submit(fetch_lesson_details, sub.get("id")): sub
                for sub in subjects_list if isinstance(sub, dict) and sub.get("id")
            }
            
            for future in as_completed(future_to_subject):
                sub = future_to_subject[future]
                sub_id = sub.get("id")
                sub_name = sub.get("name") or "Subject"
                try:
                    lesson_res = future.result()
                    vids = lesson_res.get("videos", [])
                    nts = lesson_res.get("notes", [])
                    tchr = lesson_res.get("teacher") or sub.get("teacher")
                    
                    total_course_videos += len(vids)
                    total_course_notes += len(nts)
                    
                    formatted_subjects.append({
                        "id": sub_id,
                        "name": sub_name,
                        "teacher": tchr,
                        "videos_count": len(vids),
                        "notes_count": len(nts),
                        "videos": vids,
                        "notes": nts,
                    })
                except Exception as ex:
                    logger.debug(f"Error reading subject {sub_id}: {ex}")
                    formatted_subjects.append({
                        "id": sub_id,
                        "name": sub_name,
                        "teacher": sub.get("teacher"),
                        "videos_count": 0,
                        "notes_count": 0,
                        "videos": [],
                        "notes": [],
                    })

    # Sort subjects by id to maintain deterministic order
    formatted_subjects.sort(key=lambda s: s["id"])
    course_info["subjects"] = formatted_subjects
    course_info["stats"]["total_subjects"] = len(formatted_subjects)
    course_info["stats"]["total_videos"] = total_course_videos
    course_info["stats"]["total_notes"] = total_course_notes

    return course_info

def scrape_kgs_batches(limit: int = 100, max_threads: int = 12):
    """
    Main function to fetch all latest `limit` courses and compile `kgs100.json`.
    """
    start_time = time.time()
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    logger.info(f"🚀 Starting KGS Batches scrape for latest {limit} courses at {now_ist}...")

    # 1. Fetch Master Course List
    raw_courses = make_request(COURSES_LIST_URL, timeout=15)
    if not raw_courses or not isinstance(raw_courses, list):
        logger.error("❌ Failed to fetch master course list from KGS API.")
        return None

    total_available = len(raw_courses)
    target_batches = raw_courses[:limit]
    logger.info(f"📦 Total courses found: {total_available}. Scraping top {len(target_batches)} latest batches...")

    all_courses_data = []
    completed_count = 0
    grand_videos = 0
    grand_notes = 0
    grand_subjects = 0

    # 2. Fetch full data for each course using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        future_to_course = {
            executor.submit(fetch_course_full_data, c): c
            for c in target_batches
        }

        for future in as_completed(future_to_course):
            c_info = future_to_course[future]
            try:
                data = future.result()
                if data:
                    all_courses_data.append(data)
                    grand_videos += data["stats"]["total_videos"]
                    grand_notes += data["stats"]["total_notes"]
                    grand_subjects += data["stats"]["total_subjects"]
            except Exception as e:
                logger.error(f"Error scraping batch {c_info.get('id')}: {e}")

            completed_count += 1
            if completed_count % 10 == 0 or completed_count == len(target_batches):
                logger.info(f"⚡ Progress: {completed_count}/{len(target_batches)} batches processed...")

    # Sort final list by ID descending (latest first)
    all_courses_data.sort(key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else 0, reverse=True)

    elapsed = round(time.time() - start_time, 2)
    logger.info(f"✅ Scraping completed in {elapsed}s!")
    logger.info(f"📊 Summary -> Batches: {len(all_courses_data)} | Subjects: {grand_subjects} | Videos: {grand_videos} | Notes: {grand_notes}")

    # 3. Create Result Object
    result_payload = {
        "status": True,
        "metadata": {
            "title": f"Khan Global Studies (KGS) Top {len(all_courses_data)} Batches Database",
            "generated_at": now_ist,
            "timestamp": int(time.time()),
            "total_courses": len(all_courses_data),
            "total_subjects": grand_subjects,
            "total_videos": grand_videos,
            "total_notes": grand_notes,
            "execution_time_seconds": elapsed,
            "api_version": "2.0",
            "powered_by": "STUDYAPKMOD & KGS Portal",
            "logo": "https://i.postimg.cc/jd5wqHJ3/logo.png"
        },
        "courses": all_courses_data
    }

    # 4. Save to files (`kgs100.json` and `public/kgs100.json`)
    save_paths = ["./kgs100.json", "./public/kgs100.json"]
    for path in save_paths:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result_payload, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 Saved updated dataset to: {path}")
        except Exception as e:
            logger.error(f"Failed to write file {path}: {e}")

    return result_payload

def send_telegram_message(text: str, token: str = None, chat_id: str = None):
    """Send HTML-formatted text notification to Telegram."""
    bot_token = token or TELEGRAM_BOT_TOKEN
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not bot_token or not target_chat:
        logger.warning("⚠️ Telegram Bot Token or Chat ID not configured. Skipping Telegram notification.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    
    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json", "User-Agent": "KGS-Bot/2.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as res:
            res_data = json.loads(res.read().decode('utf-8'))
            if res_data.get("ok"):
                logger.info(f"📨 Telegram message sent successfully to {target_chat}!")
                return True
            else:
                logger.error(f"Telegram API Error: {res_data}")
                return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False

def send_telegram_document(file_path: str, caption: str = "", token: str = None, chat_id: str = None):
    """Send a file (kgs100.json) directly as document to Telegram using multipart/form-data."""
    bot_token = token or TELEGRAM_BOT_TOKEN
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not bot_token or not target_chat:
        logger.warning("⚠️ Telegram Bot Token or Chat ID not configured. Skipping document upload.")
        return False

    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    boundary = "----WebKitFormBoundaryKGSBot" + str(int(time.time()))
    
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        file_name = os.path.basename(file_path)
        body = []

        # chat_id field
        body.append(f"--{boundary}".encode('utf-8'))
        body.append(f'Content-Disposition: form-data; name="chat_id"'.encode('utf-8'))
        body.append(b'')
        body.append(str(target_chat).encode('utf-8'))

        # caption field
        if caption:
            body.append(f"--{boundary}".encode('utf-8'))
            body.append(f'Content-Disposition: form-data; name="caption"'.encode('utf-8'))
            body.append(b'')
            body.append(caption.encode('utf-8'))

            body.append(f"--{boundary}".encode('utf-8'))
            body.append(f'Content-Disposition: form-data; name="parse_mode"'.encode('utf-8'))
            body.append(b'')
            body.append(b'HTML')

        # document file field
        body.append(f"--{boundary}".encode('utf-8'))
        body.append(f'Content-Disposition: form-data; name="document"; filename="{file_name}"'.encode('utf-8'))
        body.append(f'Content-Type: application/json'.encode('utf-8'))
        body.append(b'')
        body.append(file_bytes)

        body.append(f"--{boundary}--".encode('utf-8'))
        body.append(b'')

        payload_bytes = b'\r\n'.join(body)

        req = urllib.request.Request(
            url,
            data=payload_bytes,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(payload_bytes)),
                "User-Agent": "KGS-Bot/2.0"
            }
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            res_data = json.loads(res.read().decode('utf-8'))
            if res_data.get("ok"):
                logger.info(f"📁 Document {file_name} sent successfully to Telegram ({target_chat})!")
                return True
            else:
                logger.error(f"Telegram sendDocument Error: {res_data}")
                return False
    except Exception as e:
        logger.error(f"Failed to send Telegram document: {e}")
        return False

def format_telegram_report(metadata: dict, top_courses: list) -> str:
    """Format a clean, readable HTML report message for Telegram."""
    gen_time = metadata.get("generated_at", "Just now")
    tot_courses = metadata.get("total_courses", 0)
    tot_subs = metadata.get("total_subjects", 0)
    tot_vids = metadata.get("total_videos", 0)
    tot_notes = metadata.get("total_notes", 0)
    exec_time = metadata.get("execution_time_seconds", 0)

    msg = (
        f"🌟 <b>STUDYAPKMOD - KGS 100 Latest Batches Update</b> 🌟\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>Updated At:</b> <code>{gen_time}</code>\n"
        f"⏱ <b>Fetch Time:</b> <code>{exec_time}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📚 <b>Total Batches:</b> <code>{tot_courses}</code>\n"
        f"📖 <b>Total Subjects:</b> <code>{tot_subs}</code>\n"
        f"🎥 <b>Total Video Lectures:</b> <code>{tot_vids}</code>\n"
        f"📄 <b>Total PDF Notes:</b> <code>{tot_notes}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 <b>Latest 5 Added Batches:</b>\n"
    )

    for i, c in enumerate(top_courses[:5], 1):
        cid = c.get("id")
        title = c.get("title", "Batch")
        vcount = c.get("stats", {}).get("total_videos", 0)
        ncount = c.get("stats", {}).get("total_notes", 0)
        msg += f"<b>{i}.</b> [{cid}] <b>{title}</b>\n   └ 🎥 {vcount} Videos | 📄 {ncount} Notes\n"

    msg += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>API Endpoint:</b> <code>/api/kgs100</code>\n"
        f"🔗 <b>JSON URL:</b> <code>/kgs100.json</code>\n"
        f"⚡ <i>Auto-updated every day at 5:00 AM IST.</i>"
    )
    return msg

def run_update_pipeline(count: int = 100, send_telegram: bool = True):
    """Execute complete scrape + save + telegram notification routine."""
    logger.info(f"🔄 Executing KGS Batches Update Pipeline (Target: {count} courses)...")
    data = scrape_kgs_batches(limit=count)
    if not data:
        logger.error("Pipeline failed: Unable to scrape courses.")
        if send_telegram and TELEGRAM_BOT_TOKEN:
            send_telegram_message("❌ <b>Alert:</b> Failed to update KGS 100 Batches JSON. Check server logs.")
        return False

    meta = data.get("metadata", {})
    courses = data.get("courses", [])
    report_text = format_telegram_report(meta, courses)

    if send_telegram and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        logger.info("📤 Sending Telegram summary and kgs100.json document...")
        send_telegram_message(report_text)
        send_telegram_document("./kgs100.json", caption=f"📄 <b>kgs100.json</b> - {meta.get('generated_at')}")

    return True

def run_daily_scheduler(target_hour: int = 5, target_minute: int = 0, count: int = 100):
    """
    Background loop that wakes up every morning at 5:00 AM IST to run the update pipeline.
    """
    logger.info(f"⏰ Scheduler started! Waiting for daily run at {target_hour:02d}:{target_minute:02d} AM IST...")
    
    # Run once at startup if kgs100.json doesn't exist yet
    if not os.path.exists("./kgs100.json"):
        logger.info("Initial run: kgs100.json not found on disk, running initial scrape...")
        run_update_pipeline(count=count, send_telegram=False)

    last_run_day = None

    while True:
        try:
            now_ist = datetime.now(IST)
            current_day = now_ist.strftime("%Y-%m-%d")

            # Check if it's the target time and hasn't run today yet
            if (now_ist.hour == target_hour and 
                now_ist.minute == target_minute and 
                last_run_day != current_day):
                
                logger.info(f"🔔 Target time reached ({now_ist.strftime('%H:%M:%S IST')})! Triggering daily 5:00 AM update...")
                run_update_pipeline(count=count, send_telegram=True)
                last_run_day = current_day
                time.sleep(65)  # Sleep past the current minute
            
            time.sleep(30)
        except KeyboardInterrupt:
            logger.info("🛑 Scheduler stopped by user.")
            break
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
            time.sleep(60)

def run_telegram_polling():
    """
    Polls Telegram for commands like /start, /update, /stats, /getjson, /search
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ Cannot start Telegram polling: TELEGRAM_BOT_TOKEN is missing.")
        return

    logger.info("🤖 Starting Telegram Bot Long-Polling listener...")
    offset = 0

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
            req = urllib.request.Request(url, headers={"User-Agent": "KGS-Bot/2.0"})
            with urllib.request.urlopen(req, timeout=25) as response:
                result = json.loads(response.read().decode('utf-8'))
                
            updates = result.get("result", [])
            for upd in updates:
                offset = upd.get("update_id", 0) + 1
                msg = upd.get("message", {})
                text = (msg.get("text") or "").strip()
                chat = msg.get("chat", {})
                chat_id = chat.get("id")

                if not text or not chat_id:
                    continue

                logger.info(f"📩 Telegram Command received from {chat_id}: {text}")

                if text.startswith("/start") or text.startswith("/help"):
                    welcome = (
                        f"👋 <b>Welcome to KGS 100 Batches Bot!</b>\n\n"
                        f"Commands available:\n"
                        f"🔹 <code>/update</code> - Trigger immediate scrape & update kgs100.json\n"
                        f"🔹 <code>/getjson</code> - Get the latest kgs100.json file\n"
                        f"🔹 <code>/stats</code> - Show database statistics\n"
                        f"🔹 <code>/search &lt;query&gt;</code> - Search batches by keyword\n"
                        f"🔹 <code>/status</code> - Check bot and API status\n\n"
                        f"⏰ <i>Auto-update runs every morning at 5:00 AM IST.</i>"
                    )
                    send_telegram_message(welcome, chat_id=chat_id)

                elif text.startswith("/update"):
                    send_telegram_message("⏳ <b>Scraping latest 100 KGS batches... Please wait.</b>", chat_id=chat_id)
                    run_update_pipeline(count=TARGET_COUNT, send_telegram=False)
                    if os.path.exists("./kgs100.json"):
                        with open("./kgs100.json", "r", encoding="utf-8") as f:
                            d = json.load(f)
                        meta = d.get("metadata", {})
                        courses = d.get("courses", [])
                        send_telegram_message(format_telegram_report(meta, courses), chat_id=chat_id)
                        send_telegram_document("./kgs100.json", caption="✅ Latest kgs100.json database", chat_id=chat_id)
                    else:
                        send_telegram_message("❌ Failed to generate kgs100.json.", chat_id=chat_id)

                elif text.startswith("/getjson"):
                    if os.path.exists("./kgs100.json"):
                        send_telegram_document("./kgs100.json", caption="📄 <b>kgs100.json database</b>", chat_id=chat_id)
                    else:
                        send_telegram_message("⚠️ kgs100.json is not generated yet. Send <code>/update</code> to generate.", chat_id=chat_id)

                elif text.startswith("/stats") or text.startswith("/status"):
                    if os.path.exists("./kgs100.json"):
                        with open("./kgs100.json", "r", encoding="utf-8") as f:
                            d = json.load(f)
                        meta = d.get("metadata", {})
                        stat_msg = (
                            f"📊 <b>KGS Database Status</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"📅 Last Updated: <code>{meta.get('generated_at')}</code>\n"
                            f"📚 Batches: <b>{meta.get('total_courses')}</b>\n"
                            f"📖 Subjects: <b>{meta.get('total_subjects')}</b>\n"
                            f"🎥 Video Lectures: <b>{meta.get('total_videos')}</b>\n"
                            f"📄 PDF Notes: <b>{meta.get('total_notes')}</b>\n"
                            f"⏱ Generation Time: <code>{meta.get('execution_time_seconds')}s</code>"
                        )
                        send_telegram_message(stat_msg, chat_id=chat_id)
                    else:
                        send_telegram_message("⚠️ Database file not found yet. Send <code>/update</code>.", chat_id=chat_id)

                elif text.startswith("/search"):
                    query = text.replace("/search", "").strip().lower()
                    if not query:
                        send_telegram_message("⚠️ Please provide a query: <code>/search upsc</code>", chat_id=chat_id)
                        continue

                    if not os.path.exists("./kgs100.json"):
                        send_telegram_message("⚠️ Database file not found yet. Send <code>/update</code> first.", chat_id=chat_id)
                        continue

                    with open("./kgs100.json", "r", encoding="utf-8") as f:
                        d = json.load(f)
                    matches = [c for c in d.get("courses", []) if query in c.get("title", "").lower()]

                    if not matches:
                        send_telegram_message(f"🔍 No batches found matching '<b>{query}</b>'.", chat_id=chat_id)
                    else:
                        reply = f"🔍 <b>Found {len(matches)} batches for '{query}':</b>\n\n"
                        for c in matches[:8]:
                            reply += f"• [{c.get('id')}] <b>{c.get('title')}</b>\n  └ 🎥 {c.get('stats', {}).get('total_videos', 0)} Videos | 📄 {c.get('stats', {}).get('total_notes', 0)} Notes\n"
                        send_telegram_message(reply, chat_id=chat_id)

        except KeyboardInterrupt:
            logger.info("🛑 Telegram polling stopped.")
            break
        except Exception as err:
            logger.error(f"Polling loop exception: {err}")
            time.sleep(3)

def main():
    parser = argparse.ArgumentParser(description="KGS 100 Batches Scraper & Telegram Bot")
    parser.add_argument("--now", action="store_true", help="Run scrape immediately and save kgs100.json")
    parser.add_argument("--telegram", action="store_true", help="Run scrape and upload to Telegram")
    parser.add_argument("--schedule", action="store_true", help="Start background daily 5:00 AM IST scheduler")
    parser.add_argument("--poll", action="store_true", help="Start Telegram Bot command polling (/update, /stats, /getjson)")
    parser.add_argument("--count", type=int, default=TARGET_COUNT, help="Number of latest batches to scrape (default: 100)")
    parser.add_argument("--hour", type=int, default=DAILY_UPDATE_HOUR_IST, help="Daily update hour in IST (default: 5)")
    parser.add_argument("--minute", type=int, default=DAILY_UPDATE_MINUTE_IST, help="Daily update minute in IST (default: 0)")

    args = parser.parse_args()

    # Print banner
    print("=" * 60)
    print("🤖 STUDYAPKMOD - KGS 100 Batches Bot & API Engine")
    print("=" * 60)

    if args.poll:
        run_telegram_polling()
    elif args.schedule:
        run_daily_scheduler(target_hour=args.hour, target_minute=args.minute, count=args.count)
    elif args.telegram:
        run_update_pipeline(count=args.count, send_telegram=True)
    else:
        # Default behavior: run scrape immediately
        run_update_pipeline(count=args.count, send_telegram=False)

if __name__ == "__main__":
    main()
