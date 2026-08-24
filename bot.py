#!/usr/bin/env python3
"""
=============================================================================
⚡ STUDYAPKMOD - KGS 100 CYBER TERMINAL BOT & LIVE SYNC ENGINE ⚡
=============================================================================
Description:
- Hacker / Matrix themed Telegram Bot UI for /start, /sync, /update, /stats, /getjson
- Fetches the latest 100 batches/courses from Khan Global Studies (KGS).
- Live progress updates on Telegram showing each course + its completed subjects & total stats.
- Generates `kgs100.json` (and `public/kgs100.json`) for instant API access (/api/kgs100).
- Scheduled daily sync at 5:00 AM IST.
=============================================================================
"""

import os
import sys
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
import threading
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

def safe_int_env(key: str, default: int) -> int:
    val = os.environ.get(key, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

# Environment Variables & Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8865625183:AAGA6gzI40j-AZxJLTFzyRGdiZqbmA2YsJc").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "6684860996").strip()
TARGET_COUNT = safe_int_env("BATCH_COUNT", 100)
DAILY_UPDATE_HOUR_IST = safe_int_env("UPDATE_HOUR_IST", 5)   # 5 AM IST
DAILY_UPDATE_MINUTE_IST = safe_int_env("UPDATE_MINUTE_IST", 0)

# Global Sync Lock & State
SYNC_LOCK = threading.Lock()
IS_SYNCING = False

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
            time.sleep(0.4 * (attempt + 1))
    return None

def send_telegram_message(text: str, token: str = None, chat_id: str = None) -> int:
    """Send HTML-formatted text notification to Telegram and return message_id."""
    bot_token = token or TELEGRAM_BOT_TOKEN
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not bot_token or not target_chat:
        logger.warning("⚠️ Telegram Bot Token or Chat ID not configured.")
        return 0

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
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
                return res_data.get("result", {}).get("message_id", 0)
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
    return 0

def edit_telegram_message(message_id: int, text: str, token: str = None, chat_id: str = None) -> bool:
    """Edit existing Telegram message to show live dynamic progress."""
    bot_token = token or TELEGRAM_BOT_TOKEN
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not bot_token or not target_chat or not message_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {
        "chat_id": target_chat,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json", "User-Agent": "KGS-Bot/2.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            res_data = json.loads(res.read().decode('utf-8'))
            return bool(res_data.get("ok"))
    except Exception as e:
        # Rate limit or identical content error (safe to ignore)
        logger.debug(f"editMessageText ignored error: {e}")
        return False

def send_telegram_document(file_path: str, caption: str = "", token: str = None, chat_id: str = None):
    """Send a file (kgs100.json) directly as document to Telegram using multipart/form-data."""
    bot_token = token or TELEGRAM_BOT_TOKEN
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not bot_token or not target_chat:
        return False

    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    boundary = "----WebKitFormBoundaryKGSHack" + str(int(time.time()))
    
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        file_name = os.path.basename(file_path)
        body = []

        # chat_id
        body.append(f"--{boundary}".encode('utf-8'))
        body.append(f'Content-Disposition: form-data; name="chat_id"'.encode('utf-8'))
        body.append(b'')
        body.append(str(target_chat).encode('utf-8'))

        # caption
        if caption:
            body.append(f"--{boundary}".encode('utf-8'))
            body.append(f'Content-Disposition: form-data; name="caption"'.encode('utf-8'))
            body.append(b'')
            body.append(caption.encode('utf-8'))

            body.append(f"--{boundary}".encode('utf-8'))
            body.append(f'Content-Disposition: form-data; name="parse_mode"'.encode('utf-8'))
            body.append(b'')
            body.append(b'HTML')

        # document file
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
            return bool(res_data.get("ok"))
    except Exception as e:
        logger.error(f"Failed to send Telegram document: {e}")
        return False

def fetch_single_video_details(video_id: int):
    """Fetch resolved video stream URL and direct properties from KGS Video API."""
    if not video_id:
        return None
    url = f"{VIDEO_BASE_URL}/{video_id}"
    data = make_request(url, timeout=5, retries=1)
    if isinstance(data, dict):
        return {
            "video_url": data.get("video_url") or data.get("url") or "",
            "hd_video_url": data.get("hd_video_url") or "",
            "extra_pdfs": data.get("pdfs", []) if isinstance(data.get("pdfs"), list) else []
        }
    return None

def fetch_lesson_details(subject_id: int, resolve_videos: bool = True):
    """Fetch lesson details including videos and notes for a subject with resolved video URLs."""
    url = f"{LESSON_BASE_URL}/{subject_id}"
    data = make_request(url, timeout=10)
    
    if not data or not isinstance(data, dict):
        return {"videos": [], "notes": [], "teacher": None}
    
    videos = []
    notes = []
    
    # Process Videos
    raw_videos = data.get("videos", [])
    if isinstance(raw_videos, list):
        # Concurrently resolve direct stream video_url for each video item
        resolved_map = {}
        vids_to_fetch = [
            v.get("id") for v in raw_videos
            if isinstance(v, dict) and v.get("id") and not v.get("video_url")
        ]
        
        if resolve_videos and vids_to_fetch:
            with ThreadPoolExecutor(max_workers=min(12, len(vids_to_fetch))) as vid_exec:
                future_to_vid = {
                    vid_exec.submit(fetch_single_video_details, vid_id): vid_id
                    for vid_id in vids_to_fetch
                }
                for f in as_completed(future_to_vid):
                    vid_id = future_to_vid[f]
                    try:
                        res = f.result()
                        if res:
                            resolved_map[vid_id] = res
                    except Exception:
                        pass

        for v in raw_videos:
            if not isinstance(v, dict):
                continue
            vid_id = v.get("id")
            resolved_info = resolved_map.get(vid_id, {})
            actual_video_url = v.get("video_url") or resolved_info.get("video_url") or ""
            hd_video_url = v.get("hd_video_url") or resolved_info.get("hd_video_url") or ""
            
            # If still missing, provide direct video resolver fallback URL
            if not actual_video_url and vid_id:
                actual_video_url = f"https://studyapkmodkgs.vercel.app/api/video-details/{vid_id}"

            pdfs = v.get("pdfs", []) if isinstance(v.get("pdfs"), list) else []
            if resolved_info.get("extra_pdfs"):
                for ep in resolved_info.get("extra_pdfs"):
                    if ep not in pdfs:
                        pdfs.append(ep)

            videos.append({
                "id": vid_id,
                "name": v.get("name") or v.get("title") or "Class Lecture",
                "thumb": v.get("thumb") or "https://i.postimg.cc/jd5wqHJ3/logo.png",
                "published_at": v.get("published_at") or v.get("created_at"),
                "duration": v.get("duration"),
                "video_url": actual_video_url,
                "hd_video_url": hd_video_url,
                "video_details_url": f"https://studyapkmodkgs.vercel.app/api/video-details/{vid_id}" if vid_id else "",
                "pdfs": pdfs,
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

def fetch_course_full_data(course_raw: dict, on_subject_progress=None):
    """Fetch all subjects, lessons, videos, notes, and live classes for a single course."""
    course_id = course_raw.get("id")
    if not course_id:
        return None

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

    # 1. Live Classes
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

    # 2. Classroom Subjects
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

                    if on_subject_progress:
                        on_subject_progress(course_id, course_info["title"], sub_name, len(vids), len(nts))
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

    formatted_subjects.sort(key=lambda s: s["id"])
    course_info["subjects"] = formatted_subjects
    course_info["stats"]["total_subjects"] = len(formatted_subjects)
    course_info["stats"]["total_videos"] = total_course_videos
    course_info["stats"]["total_notes"] = total_course_notes

    return course_info

def build_cyber_progress_ui(completed_courses: int, total_courses: int, total_subs: int, total_vids: int, total_notes: int, latest_logs: list, start_time: float) -> str:
    """Build Hacker/Matrix styled Terminal Live Progress Interface for Telegram."""
    pct = int((completed_courses / max(total_courses, 1)) * 100)
    bars_count = 14
    filled = int((pct / 100) * bars_count)
    bar_visual = "█" * filled + "░" * (bars_count - filled)
    elapsed = int(time.time() - start_time)

    lines = [
        "╔══════════════════════════════════════╗",
        f"║  ⚡ <b>KGS CYBER TERMINAL :: {total_courses} BATCHES</b> ║",
        "╚══════════════════════════════════════╝",
        f"<b>[PROG]</b> <code>[{bar_visual}] {pct}% ({completed_courses}/{total_courses})</code>",
        f"<b>[STAT]</b> 📚 Batches: <code>{completed_courses}</code> | ⏱ Elapsed: <code>{elapsed}s</code>",
        f"<b>[DATA]</b> 📖 Subs: <code>{total_subs}</code> | 🎥 Vids: <code>{total_vids}</code> | 📄 Notes: <code>{total_notes}</code>",
        "──────────────────────────────────────",
        "<b>[LIVE FEED :: RECENT COMPLETED SUBJECTS]</b>"
    ]

    if not latest_logs:
        lines.append("<code>>>> Initializing socket connection & course index...</code>")
    else:
        for log in latest_logs[-5:]:
            lines.append(f"<code>{log}</code>")

    lines.append("──────────────────────────────────────")
    lines.append("<code>>>> STATUS: INFILTRATING & AGGREGATING RAW DATA...</code>")
    return "\n".join(lines)

def scrape_kgs_batches(limit: int = 100, max_threads: int = None, live_chat_id: str = None, live_msg_id: int = None):
    """
    Main function to fetch all latest `limit` courses and compile `kgs100.json` / `kgs1000.json` with live Telegram terminal updates.
    """
    global IS_SYNCING
    if max_threads is None:
        max_threads = 20 if limit >= 500 else 12

    start_time = time.time()
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    logger.info(f"🚀 Starting KGS Batches scrape for latest {limit} courses at {now_ist}...")

    # 1. Fetch Master Course List
    raw_courses = make_request(COURSES_LIST_URL, timeout=15)
    if not raw_courses or not isinstance(raw_courses, list):
        logger.error("❌ Failed to fetch master course list from KGS API.")
        return None

    target_batches = raw_courses[:limit]
    total_target = len(target_batches)
    logger.info(f"📦 Scraping top {total_target} latest batches (Workers: {max_threads})...")

    all_courses_data = []
    completed_count = 0
    grand_videos = 0
    grand_notes = 0
    grand_subjects = 0
    
    recent_logs = []
    lock = threading.Lock()
    last_edit_time = [0.0]

    def on_subject_done(cid, ctitle, sub_name, vcount, ncount):
        nonlocal grand_videos, grand_notes
        with lock:
            short_course = (ctitle[:18] + '..') if len(ctitle) > 18 else ctitle
            short_sub = (sub_name[:15] + '..') if len(sub_name) > 15 else sub_name
            log_str = f"✔ [{cid}] {short_course} > {short_sub} (+{vcount}V, +{ncount}N)"
            recent_logs.append(log_str)
            if len(recent_logs) > 12:
                recent_logs.pop(0)

            # Throttle Telegram message edits to avoid rate-limits (edit every ~2.5 seconds)
            now = time.time()
            if live_chat_id and live_msg_id and (now - last_edit_time[0] >= 2.5):
                last_edit_time[0] = now
                ui_text = build_cyber_progress_ui(
                    completed_count, total_target, grand_subjects, grand_videos, grand_notes, recent_logs, start_time
                )
                edit_telegram_message(live_msg_id, ui_text, chat_id=live_chat_id)

    # 2. Fetch full data concurrently
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        future_to_course = {
            executor.submit(fetch_course_full_data, c, on_subject_done): c
            for c in target_batches
        }

        for future in as_completed(future_to_course):
            c_info = future_to_course[future]
            try:
                data = future.result()
                if data:
                    all_courses_data.append(data)
                    with lock:
                        grand_videos += data["stats"]["total_videos"]
                        grand_notes += data["stats"]["total_notes"]
                        grand_subjects += data["stats"]["total_subjects"]
            except Exception as e:
                logger.error(f"Error scraping batch {c_info.get('id')}: {e}")

            with lock:
                completed_count += 1

            now = time.time()
            if live_chat_id and live_msg_id and (now - last_edit_time[0] >= 2.2 or completed_count == total_target):
                last_edit_time[0] = now
                ui_text = build_cyber_progress_ui(
                    completed_count, total_target, grand_subjects, grand_videos, grand_notes, recent_logs, start_time
                )
                edit_telegram_message(live_msg_id, ui_text, chat_id=live_chat_id)

    # Sort final list by ID descending (latest first)
    all_courses_data.sort(key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else 0, reverse=True)

    elapsed = round(time.time() - start_time, 2)
    logger.info(f"✅ Scraping completed in {elapsed}s! Batches: {len(all_courses_data)} | Subs: {grand_subjects} | Vids: {grand_videos} | Notes: {grand_notes}")

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
            "powered_by": "STUDYAPKMOD & KGS Hacker Bot",
            "logo": "https://i.postimg.cc/jd5wqHJ3/logo.png"
        },
        "courses": all_courses_data
    }

    # 4. Save to files (`kgs100.json` or `kgs1000.json`)
    file_prefix = f"kgs{limit}" if limit in [100, 500, 1000] else f"kgs_{limit}"
    save_paths = [f"./{file_prefix}.json", f"./public/{file_prefix}.json"]
    
    # If scraping 1000, also save/update standard files if helpful
    if limit >= 1000:
        save_paths.extend(["./kgs1000.json", "./public/kgs1000.json"])
    elif limit == 100:
        save_paths.extend(["./kgs100.json", "./public/kgs100.json"])

    # Remove duplicates
    save_paths = list(set(save_paths))

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

def format_hacker_start_ui() -> str:
    """Matrix / Cyberpunk Hacker themed /start command interface."""
    return (
        "<code>╔══════════════════════════════════════╗\n"
        "║  ☠ STUDYAPKMOD :: KGS CYBER BOT v2.5 ║\n"
        "║  STATUS: ONLINE | ENCRYPTION: ACTIVE ║\n"
        "╚══════════════════════════════════════╝</code>\n\n"
        "🟢 <b>[SYSTEM AUTHORIZED] - ROOT ACCESS GRANTED</b>\n"
        "<i>Autonomous scraper & API sync engine for Khan Global Studies batches.</i>\n\n"
        "⚡ <b>CYBER COMMAND INTERFACE:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 <code>/kgs&lt;count&gt;</code> - <b>Dynamic Batch Scraper (e.g. <code>/kgs100</code>, <code>/kgs250</code>, <code>/kgs500</code>, <code>/kgs1000</code>)</b>\n"
        "📡 <code>/sync</code>    - <b>Trigger 100 Course Sync + LIVE Matrix Feed</b>\n"
        "🎬 <code>/video &lt;id&gt;</code> - <b>Direct Stream Video URL &amp; PDF Extractor</b> (e.g. <code>/video 561922</code>)\n"
        "⚡ <code>/update</code>  - Fast background database refresh\n"
        "📁 <code>/getjson &lt;count&gt;</code> - Download <code>kgs&lt;count&gt;.json</code> database\n"
        "📊 <code>/stats &lt;count&gt;</code>   - Display indexed batches, vids & notes\n"
        "🔍 <code>/search &lt;query&gt;</code> - Deep search courses by keyword\n"
        "⚙ <code>/status</code>  - Query server uptime & API endpoint health\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🌐 <b>API Endpoints:</b> <code>/api/kgs100</code> | <code>/api/kgs1000</code> | <code>/api/kgs/:count</code>\n"
        "⏰ <b>Auto-Sync:</b> <code>Everyday @ 05:00 AM IST</code>\n"
        "<code>>>> Enter command to execute...</code>"
    )

def format_hacker_finish_ui(meta: dict, top_courses: list, target_file: str = "kgs100.json") -> str:
    """Matrix Hacker finished summary report."""
    gen_time = meta.get("generated_at", "Just now")
    tot_courses = meta.get("total_courses", 0)
    tot_subs = meta.get("total_subjects", 0)
    tot_vids = meta.get("total_videos", 0)
    tot_notes = meta.get("total_notes", 0)
    exec_time = meta.get("execution_time_seconds", 0)

    api_path = "/api/kgs1000" if "1000" in target_file else "/api/kgs100"

    msg = (
        "<code>╔══════════════════════════════════════╗\n"
        "║  ✔ SYNC COMPLETE :: MISSION ACCOMPLISHED ║\n"
        "╚══════════════════════════════════════╝</code>\n"
        f"📅 <b>Timestamp:</b> <code>{gen_time}</code>\n"
        f"⏱ <b>Execution Time:</b> <code>{exec_time}s</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📚 <b>Total Batches Indexed:</b> <code>{tot_courses}</code>\n"
        f"📖 <b>Total Subjects Scraped:</b> <code>{tot_subs}</code>\n"
        f"🎥 <b>Total Video Lectures:</b> <code>{tot_vids}</code>\n"
        f"📄 <b>Total PDF Notes:</b> <code>{tot_notes}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 <b>TOP 5 LATEST BATCHES EXTRACTED:</b>\n"
    )

    for i, c in enumerate(top_courses[:5], 1):
        cid = c.get("id")
        title = c.get("title", "Batch")
        vcount = c.get("stats", {}).get("total_videos", 0)
        ncount = c.get("stats", {}).get("total_notes", 0)
        scount = c.get("stats", {}).get("total_subjects", 0)
        msg += f"<b>{i}.</b> [{cid}] <b>{title}</b>\n   └ 📖 {scount} Subs | 🎥 {vcount} Vids | 📄 {ncount} Notes\n"

    msg += (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>LIVE API:</b> <code>{api_path}</code>\n"
        f"🔗 <b>FILE:</b> <code>/{target_file}</code>\n"
        "<code>>>> Database is ready for deployment.</code>"
    )
    return msg

def handle_live_sync_command(chat_id: str, count: int = 100):
    """Handles the /sync, /kgs1000 and /update command with live terminal UI."""
    global IS_SYNCING
    if not SYNC_LOCK.acquire(blocking=False):
        send_telegram_message("⚠️ <b>ACCESS DENIED:</b> Another sync process is already executing! Please wait.", chat_id=chat_id)
        return

    IS_SYNCING = True
    target_file = f"kgs{count}.json" if count in [100, 1000] else f"kgs_{count}.json"
    file_path = f"./{target_file}"
    workers = 24 if count >= 500 else 12

    try:
        init_ui = (
            "╔══════════════════════════════════════╗\n"
            f"║  ⚡ <b>KGS CYBER TERMINAL :: {count} BATCHES</b>  ║\n"
            "╚══════════════════════════════════════╝\n"
            f"<code>[PROG] [░░░░░░░░░░░░░░] 0% (0/{count})</code>\n"
            "<code>>>> CONNECTING TO KGS CLOUD MAINFRAME...</code>\n"
            f"<code>>>> TARGET: LATEST {count} BATCHES, SUBJECTS & VIDEOS</code>"
        )
        msg_id = send_telegram_message(init_ui, chat_id=chat_id)

        data = scrape_kgs_batches(limit=count, max_threads=workers, live_chat_id=chat_id, live_msg_id=msg_id)
        
        if data:
            meta = data.get("metadata", {})
            courses = data.get("courses", [])
            final_report = format_hacker_finish_ui(meta, courses, target_file=target_file)
            
            # Edit initial message with completed overview
            edit_telegram_message(msg_id, final_report, chat_id=chat_id)
            
            # Send file
            if os.path.exists(file_path):
                send_telegram_document(file_path, caption=f"📄 <b>{target_file} Database ({len(courses)} Batches)</b> [Generated: {meta.get('generated_at')}]", chat_id=chat_id)
            elif os.path.exists("./kgs100.json"):
                send_telegram_document("./kgs100.json", caption=f"📄 <b>kgs100.json Database</b> [Generated: {meta.get('generated_at')}]", chat_id=chat_id)
        else:
            edit_telegram_message(msg_id, "❌ <b>FATAL ERROR:</b> Scraper failed to fetch KGS batch lists. Check logs.", chat_id=chat_id)
    finally:
        IS_SYNCING = False
        SYNC_LOCK.release()

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
    report_text = format_hacker_finish_ui(meta, courses)

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
                time.sleep(65)
            
            time.sleep(30)
        except KeyboardInterrupt:
            logger.info("🛑 Scheduler stopped by user.")
            break
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
            time.sleep(60)

def run_telegram_polling():
    """
    Polls Telegram for hacker commands: /start, /sync, /update, /stats, /getjson, /search
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ Cannot start Telegram polling: TELEGRAM_BOT_TOKEN is missing.")
        return

    logger.info("🤖 Starting Telegram Cyber Bot Long-Polling listener...")
    
    # 1. Clear any conflicting active webhook so getUpdates works reliably
    try:
        del_wh_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook?drop_pending_updates=false"
        del_req = urllib.request.Request(del_wh_url, headers={"User-Agent": "KGS-Bot/2.0"})
        with urllib.request.urlopen(del_req, timeout=10) as r:
            logger.info("🔗 Cleared Telegram Webhooks to ensure polling receives messages.")
    except Exception as wh_err:
        logger.debug(f"deleteWebhook note: {wh_err}")

    offset = 0

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
            req = urllib.request.Request(url, headers={"User-Agent": "KGS-Bot/2.0"})
            with urllib.request.urlopen(req, timeout=25) as response:
                result = json.loads(response.read().decode('utf-8'))
                
            if not result.get("ok"):
                logger.warning(f"Telegram getUpdates response not ok: {result}")
                time.sleep(3)
                continue

            updates = result.get("result", [])
            for upd in updates:
                offset = upd.get("update_id", 0) + 1
                msg = upd.get("message") or upd.get("channel_post") or {}
                text = (msg.get("text") or "").strip()
                chat = msg.get("chat", {})
                chat_id = chat.get("id")

                if not text or not chat_id:
                    continue

                logger.info(f"📩 Telegram Command received from {chat_id}: {text}")

                if text.startswith("/start") or text.startswith("/help"):
                    send_telegram_message(format_hacker_start_ui(), chat_id=chat_id)

                # Dynamic /kgs<count> command (e.g. /kgs100, /kgs250, /kgs500, /kgs1000)
                elif re.match(r"^/kgs(\d+)", text.lower()) or re.match(r"^/sync(\d+)", text.lower()):
                    m = re.match(r"^/(?:kgs|sync)(\d+)", text.lower())
                    custom_count = int(m.group(1)) if m else TARGET_COUNT
                    cmd_parts = text.split()
                    
                    target_filename = f"kgs{custom_count}.json"
                    # If user asked to download existing file: /kgs1000 get
                    if len(cmd_parts) > 1 and cmd_parts[1].lower() in ["get", "file", "download"]:
                        if os.path.exists(f"./{target_filename}"):
                            send_telegram_document(f"./{target_filename}", caption=f"📄 <b>{target_filename} database ({custom_count} Batches)</b>", chat_id=chat_id)
                        else:
                            send_telegram_message(f"⚠️ <code>{target_filename}</code> not found. Starting {custom_count} batches live scrape...", chat_id=chat_id)
                            threading.Thread(target=handle_live_sync_command, args=(str(chat_id), custom_count), daemon=True).start()
                    else:
                        threading.Thread(target=handle_live_sync_command, args=(str(chat_id), custom_count), daemon=True).start()

                elif text.startswith("/sync") or text.startswith("/update"):
                    # Launch sync in a separate thread so polling remains responsive
                    threading.Thread(target=handle_live_sync_command, args=(str(chat_id), TARGET_COUNT), daemon=True).start()

                elif text.startswith("/getjson"):
                    cmd_parts = text.split()
                    target_file = "./kgs100.json"
                    if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                        c_num = cmd_parts[1]
                        target_file = f"./kgs{c_num}.json"
                    elif re.match(r"^/getjson(\d+)", text.lower()):
                        c_num = re.match(r"^/getjson(\d+)", text.lower()).group(1)
                        target_file = f"./kgs{c_num}.json"

                    if os.path.exists(target_file):
                        send_telegram_document(target_file, caption=f"📄 <b>{os.path.basename(target_file)} database</b>", chat_id=chat_id)
                    elif os.path.exists("./kgs1000.json"):
                        send_telegram_document("./kgs1000.json", caption="📄 <b>kgs1000.json database</b>", chat_id=chat_id)
                    elif os.path.exists("./kgs100.json"):
                        send_telegram_document("./kgs100.json", caption="📄 <b>kgs100.json database</b>", chat_id=chat_id)
                    else:
                        send_telegram_message("⚠️ Database file is not generated yet. Send <code>/kgs100</code> or <code>/kgs1000</code> to start extraction.", chat_id=chat_id)

                elif text.startswith("/stats") or text.startswith("/status"):
                    cmd_parts = text.split()
                    target_file = "./kgs100.json"
                    if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                        target_file = f"./kgs{cmd_parts[1]}.json"
                    elif re.match(r"^/stats(\d+)", text.lower()):
                        c_num = re.match(r"^/stats(\d+)", text.lower()).group(1)
                        target_file = f"./kgs{c_num}.json"
                    elif not os.path.exists(target_file) and os.path.exists("./kgs1000.json"):
                        target_file = "./kgs1000.json"

                    if os.path.exists(target_file):
                        with open(target_file, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        meta = d.get("metadata", {})
                        stat_msg = (
                            "<code>╔══════════════════════════════════════╗\n"
                            f"║   ⚡ {os.path.basename(target_file).upper()} DATABASE STATS   ║\n"
                            "╚══════════════════════════════════════╝</code>\n"
                            f"📅 Last Sync: <code>{meta.get('generated_at')}</code>\n"
                            f"📚 Batches: <b>{meta.get('total_courses')}</b>\n"
                            f"📖 Subjects: <b>{meta.get('total_subjects')}</b>\n"
                            f"🎥 Video Lectures: <b>{meta.get('total_videos')}</b>\n"
                            f"📄 PDF Notes: <b>{meta.get('total_notes')}</b>\n"
                            f"⏱ Gen Time: <code>{meta.get('execution_time_seconds')}s</code>\n"
                            f"🌐 File: <code>/{os.path.basename(target_file)}</code>"
                        )
                        send_telegram_message(stat_msg, chat_id=chat_id)
                    else:
                        send_telegram_message(f"⚠️ <code>{os.path.basename(target_file)}</code> not found yet. Send <code>/kgs100</code> or <code>/kgs1000</code> to generate.", chat_id=chat_id)

                elif text.startswith("/video") or text.startswith("/v ") or text.startswith("/vid"):
                    raw_id = text.replace("/video", "").replace("/vid", "").replace("/v", "").strip()
                    if not raw_id or not raw_id.isdigit():
                        send_telegram_message("⚠️ <b>Syntax Error:</b> Provide numeric Video ID: <code>/video 561922</code>", chat_id=chat_id)
                        continue

                    vid_id = int(raw_id)
                    send_telegram_message(f"🔍 <b>[CYBER EXTRACTION]</b> Resolving Video ID <code>{vid_id}</code> from KGS stream servers...", chat_id=chat_id)
                    vinfo = fetch_single_video_details(vid_id)

                    if not vinfo or (not vinfo.get("video_url") and not vinfo.get("extra_pdfs")):
                        send_telegram_message(f"❌ <b>Error:</b> Video ID <code>{vid_id}</code> could not be resolved or does not exist.", chat_id=chat_id)
                    else:
                        v_url = vinfo.get("video_url") or "Not Available"
                        hd_url = vinfo.get("hd_video_url")
                        pdfs = vinfo.get("extra_pdfs", [])

                        vmsg = (
                            "<code>╔══════════════════════════════════════╗\n"
                            f"║   🎬 KGS VIDEO STREAM :: ID {vid_id}   ║\n"
                            "╚══════════════════════════════════════╝</code>\n"
                            f"🔗 <b>Stream URL:</b>\n<code>{v_url}</code>\n\n"
                        )
                        if hd_url:
                            vmsg += f"📺 <b>HD Quality:</b>\n<code>{hd_url}</code>\n\n"

                        if pdfs:
                            vmsg += "📄 <b>Attached PDF Notes:</b>\n"
                            for p in pdfs[:5]:
                                ptitle = p.get("title") or p.get("name") or "Lecture Note"
                                purl = p.get("url") or p.get("pdf_url")
                                vmsg += f"• <a href=\"{purl}\">{ptitle}</a>\n"
                            vmsg += "\n"

                        vmsg += f"🌐 <b>API Endpoint:</b> <code>/api/video-details/{vid_id}</code>"
                        send_telegram_message(vmsg, chat_id=chat_id)

                elif text.startswith("/search"):
                    query = text.replace("/search", "").strip().lower()
                    if not query:
                        send_telegram_message("⚠️ <b>Syntax Error:</b> Provide search keyword: <code>/search upsc</code>", chat_id=chat_id)
                        continue

                    search_file = "./kgs1000.json" if os.path.exists("./kgs1000.json") else ("./kgs100.json" if os.path.exists("./kgs100.json") else None)
                    if not search_file:
                        send_telegram_message("⚠️ Database file not found yet. Send <code>/sync</code> or <code>/kgs1000</code> first.", chat_id=chat_id)
                        continue

                    with open(search_file, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    matches = [c for c in d.get("courses", []) if query in c.get("title", "").lower()]

                    if not matches:
                        send_telegram_message(f"🔍 <b>[CYBER SCAN]</b> No batches found matching '<b>{query}</b>'.", chat_id=chat_id)
                    else:
                        reply = f"🔍 <b>[CYBER SCAN] Found {len(matches)} batches matching '{query}':</b>\n\n"
                        for c in matches[:8]:
                            reply += f"• [{c.get('id')}] <b>{c.get('title')}</b>\n  └ 📖 {c.get('stats', {}).get('total_subjects', 0)} Subs | 🎥 {c.get('stats', {}).get('total_videos', 0)} Vids | 📄 {c.get('stats', {}).get('total_notes', 0)} Notes\n"
                        send_telegram_message(reply, chat_id=chat_id)

        except KeyboardInterrupt:
            logger.info("🛑 Telegram polling stopped.")
            break
        except Exception as err:
            logger.error(f"Polling loop exception: {err}")
            time.sleep(3)

def interactive_terminal_prompt():
    """Interactive command-line interface when bot.py is executed directly without flags in a terminal."""
    print("=" * 65)
    print("⚡ STUDYAPKMOD - KGS CYBER TERMINAL & DYNAMIC SCRAPER ⚡")
    print("=" * 65)
    print("📌 Select an option:")
    print("  1. Enter batch count (e.g. 100, 250, 500, 1000) or command (/kgs100, /kgs1000)")
    print("  2. Start Telegram Bot polling daemon (/kgs<count>, /sync, /video)")
    print("  3. Run daily 5:00 AM IST scheduler")
    print("  4. Quick Scrape Top 100 Batches (kgs100.json)")
    print("  5. Full Scrape Top 1000 Batches (kgs1000.json)")
    print("  q. Exit")
    print("=" * 65)

    try:
        user_choice = input("👉 Enter choice / command [default: /kgs100]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nExiting...")
        return

    if not user_choice or user_choice in ["1", "/kgs100", "100"]:
        target_count = 100
        if user_choice == "1":
            try:
                raw_num = input("🔢 How many latest batches do you want to scrape? [e.g. 50, 100, 500, 1000]: ").strip()
                target_count = int(re.sub(r"\D", "", raw_num)) if re.sub(r"\D", "", raw_num) else 100
            except ValueError:
                target_count = 100
        elif re.match(r"^/kgs(\d+)", user_choice.lower()):
            target_count = int(re.match(r"^/kgs(\d+)", user_choice.lower()).group(1))
        elif user_choice.isdigit():
            target_count = int(user_choice)

        print(f"\n🚀 Starting live scraping for Top {target_count} Batches...")
        run_update_pipeline(count=target_count, send_telegram=False)

    elif re.match(r"^/kgs(\d+)", user_choice.lower()):
        target_count = int(re.match(r"^/kgs(\d+)", user_choice.lower()).group(1))
        print(f"\n🚀 Starting live scraping for Top {target_count} Batches...")
        run_update_pipeline(count=target_count, send_telegram=False)

    elif user_choice in ["2", "poll", "/poll"]:
        print("\n🤖 Starting Telegram Bot polling...")
        scheduler_thread = threading.Thread(
            target=run_daily_scheduler,
            args=(DAILY_UPDATE_HOUR_IST, DAILY_UPDATE_MINUTE_IST, TARGET_COUNT),
            daemon=True
        )
        scheduler_thread.start()
        run_telegram_polling()

    elif user_choice in ["3", "schedule"]:
        print(f"\n⏰ Starting daily scheduler (5:00 AM IST)...")
        run_daily_scheduler(target_hour=DAILY_UPDATE_HOUR_IST, target_minute=DAILY_UPDATE_MINUTE_IST, count=TARGET_COUNT)

    elif user_choice in ["4", "100"]:
        print("\n🚀 Scraping Top 100 Batches -> kgs100.json...")
        run_update_pipeline(count=100, send_telegram=False)

    elif user_choice in ["5", "1000", "/kgs1000"]:
        print("\n🚀 Scraping Top 1000 Batches -> kgs1000.json...")
        run_update_pipeline(count=1000, send_telegram=False)

    elif user_choice.lower() in ["q", "exit", "quit"]:
        print("Goodbye!")
        return
    else:
        # If user passed a number directly (e.g. 200, 500)
        digits = re.sub(r"\D", "", user_choice)
        if digits:
            cnt = int(digits)
            print(f"\n🚀 Scraping Top {cnt} Batches -> kgs{cnt}.json...")
            run_update_pipeline(count=cnt, send_telegram=False)
        else:
            print(f"Unknown input '{user_choice}', scraping default Top 100 Batches...")
            run_update_pipeline(count=100, send_telegram=False)

def main():
    parser = argparse.ArgumentParser(description="KGS Dynamic Batches Cyber Scraper & Telegram Bot")
    parser.add_argument("--now", action="store_true", help="Run scrape immediately and save kgs<count>.json")
    parser.add_argument("--telegram", action="store_true", help="Run scrape and upload to Telegram")
    parser.add_argument("--schedule", action="store_true", help="Start background daily 5:00 AM IST scheduler")
    parser.add_argument("--poll", action="store_true", help="Start Telegram Bot command polling (/start, /kgs<count>, /sync, /video)")
    parser.add_argument("--count", type=int, default=None, help="Number of latest batches to scrape (e.g. 100, 250, 500, 1000)")
    parser.add_argument("--hour", type=int, default=DAILY_UPDATE_HOUR_IST, help="Daily update hour in IST (default: 5)")
    parser.add_argument("--minute", type=int, default=DAILY_UPDATE_MINUTE_IST, help="Daily update minute in IST (default: 0)")

    args = parser.parse_args()

    # Determine batch count if provided
    batch_count = args.count if args.count is not None else TARGET_COUNT

    if args.poll:
        print("=" * 60)
        print("⚡ STUDYAPKMOD - KGS CYBER TERMINAL & LIVE SYNC ENGINE ⚡")
        print("=" * 60)
        scheduler_thread = threading.Thread(
            target=run_daily_scheduler,
            args=(args.hour, args.minute, batch_count),
            daemon=True
        )
        scheduler_thread.start()
        logger.info(f"🕒 Daily scheduler spawned in background (Trigger: {args.hour:02d}:{args.minute:02d} IST).")
        run_telegram_polling()
    elif args.schedule:
        run_daily_scheduler(target_hour=args.hour, target_minute=args.minute, count=batch_count)
    elif args.telegram:
        run_update_pipeline(count=batch_count, send_telegram=True)
    elif args.now or args.count is not None:
        run_update_pipeline(count=batch_count, send_telegram=False)
    else:
        # Check if running interactively in terminal (TTY)
        if sys.stdin.isatty():
            interactive_terminal_prompt()
        else:
            # Non-interactive default execution
            run_update_pipeline(count=batch_count, send_telegram=False)

if __name__ == "__main__":
    main()
