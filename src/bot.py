# -*- coding: utf-8 -*-
""" """
import asyncio
import json
import logging
import os
import re
import sys
import threading
import time
from urllib.parse import unquote

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import telegram

_basedir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _basedir)
sys.path.insert(0, os.path.dirname(_basedir))

import secrets
import httpx

from gopeed_client import GopeedClient, filter_keep_files
from av_search import search_av
from detector import classify
from poster import fetch_movie_poster, fetch_av_poster, download_poster_bytes
from ai import analyze_input
from hgme_search import search as hgme_search, get_torrents as hgme_get_torrents
from hgme_proxy import get_session as hgme_get_session

AV_CODE_RE = re.compile(r'\b([A-Z]{3,5}-\d{3,5})\b')

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GOPEED_URL = os.getenv("GOPEED_URL", "http://127.0.0.1:9999")
GOPEED_TOKEN = os.getenv("GOPEED_TOKEN", "")
AV_DEST = os.getenv("AV_DEST", "/video4/DL/RSS")
BT_DEST = os.getenv("BT_DEST", "/video4/D4")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "3"))
PROXY_URL = os.getenv("PROXY_URL", "")
HTTP_PROXY = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or PROXY_URL
PROXY = {"https": HTTP_PROXY} if HTTP_PROXY else {}
HGME_ENABLED = os.getenv("HGME_ENABLED", "").lower() == "true"

gopeed = GopeedClient(GOPEED_URL, GOPEED_TOKEN)

TASKS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "tasks.json")

# task_id -> {chat_id, message_id, gid, name, magnet, dest, source_name, poll_task, started}
active_tasks = {}

# hgeme pending magnet selections: token -> (magnet, title)
_pending_magnets = {}

# hgeme pending search candidates: token -> (keyword, list[Candidate])
_pending_searches = {}

_pending_created = {}

def _cleanup_pending():
    now = time.time()
    stale = [k for k in list(_pending_created.keys()) if now - _pending_created[k] > 300]
    for k in stale:
        _pending_magnets.pop(k, None)
        _pending_searches.pop(k, None)
        _pending_created.pop(k, None)

def _save_tasks():
    data = {}
    for tid, t in active_tasks.items():
        if tid.startswith("_"):
            continue
        data[tid] = {k: v for k, v in t.items() if k != "poll_task"}
    try:
        os.makedirs(os.path.dirname(TASKS_FILE), exist_ok=True)
        json.dump(data, open(TASKS_FILE, "w"))
    except Exception as e:
        logger.warning("Failed to save tasks: %s", e)

def _load_tasks():
    try:
        return json.load(open(TASKS_FILE))
    except Exception as e:
        logger.warning("Failed to load tasks: %s", e)
        return {}

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger("tg-download-bot")


FILL = "\u2588"
SHADE = "\u2591"

TYPE_ICON = {"av": "🔞", "bt": "🎬"}

def icon(task):
    return TYPE_ICON.get(task.get("input_type", "bt"), "🎬")

def progress_bar(percent, width=16):
    filled = int(width * min(percent, 100) / 100)
    return FILL * filled + SHADE * (width - filled)


def extract_name(magnet):
    """Extract display name from magnet link."""
    if "&dn=" in magnet:
        try:
            raw = magnet.split("&dn=")[1].split("&")[0]
            return unquote(raw)[:80]
        except Exception as e:
            logger.warning("Failed to extract name from magnet: %s", e)
    return magnet[:60]


def format_size(mb):
    if mb >= 1024:
        return f"{mb / 1024:.1f}GB"
    return f"{mb:.0f}MB"

def format_speed(bps):
    if bps >= 1048576:
        return f"{bps / 1048576:.1f}MB/s"
    elif bps >= 1024:
        return f"{bps / 1024:.0f}KB/s"
    return f"{bps:.0f}B/s"

def format_elapsed(secs):
    if secs < 60:
        return f"{secs}s"
    elif secs < 3600:
        return f"{secs // 60}m{secs % 60}s"
    return f"{secs // 3600}h{(secs % 3600) // 60}m{secs % 60}s"

async def edit_progress(context, task, text, reply_markup=None):
    """Edit message caption (photo) or text depending on task type."""
    if task.get("is_photo"):
        try:
            await context.bot.edit_message_caption(
                chat_id=task["chat_id"],
                message_id=task["message_id"],
                caption=text,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.warning("Failed to edit photo caption: %s", e)
    else:
        try:
            await context.bot.edit_message_text(
                chat_id=task["chat_id"],
                message_id=task["message_id"],
                text=text,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.warning("Failed to edit message text: %s", e)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _touch()
    text = update.message.text
    chat_id = update.effective_chat.id

    input_type, content = classify(text)

    if input_type is None:
        await update.message.reply_text(
            "⚠️ 无法识别输入。\n发送磁力链接或 AV 番号（如 ABP-123）。"
        )
        return

    if input_type == "movie_search":
        if not HGME_ENABLED:
            await update.message.reply_text(
                "⚠️ HGME 搜索未启用。\n发送磁力链接或 AV 番号（如 ABP-123）。"
            )
            return
        await handle_movie_search(update, context, content)
        return

    if not gopeed.ping():
        await update.message.reply_text("❌ Gopeed 连接失败。")
        return

    if input_type == "av":
        # Bare AV number - search sukebei, javbus poster
        dest = AV_DEST
        msg = await update.message.reply_text(f"🔍 搜索 `{content}`...")
        try:
            results = search_av(content, proxies=PROXY)
        except Exception as e:
            await msg.edit_text(f"❌ 搜索失败:\n`{str(e)[:200]}`")
            return
        if not results:
            await msg.edit_text(f"😵 未找到 `{content}` 的结果。")
            return
        magnet = results[0]["magnet"]
        display = f"{content} ({results[0]['size']})"

        poster_url = None
        try:
            t0 = time.time()
            poster_url = await asyncio.to_thread(fetch_av_poster, content, proxies=PROXY)
            logger.info("AV poster %s in %.1fs", "OK" if poster_url else "miss", time.time() - t0)
        except Exception as e:
            logger.warning("AV poster error: %s", e)

        gid = None
        try:
            gid = gopeed.add_uri(magnet, {"dir": dest})
            try:
                gid, files = gopeed.wait_for_metadata(gid, timeout=15)
                keep = filter_keep_files(files)
                if keep:
                    gopeed.set_select_file(gid, keep)
            except Exception as e:
                logger.warning("File filter error: %s", e)
        except Exception as e:
            await msg.edit_text(f"❌ 提交失败:\n`{str(e)[:200]}`")
            return
    else:
        # Magnet link - AI analysis first, then submit to correct dest
        magnet = content
        display = extract_name(content)
        dest = BT_DEST

        msg = await update.message.reply_text("🤖 AI 分析中...")

        poster_url = None
        t0 = time.time()

        await msg.edit_text(f"🤖 AI 分析中...\n\n📄 `{display[:100]}`")

        ai_result = await asyncio.to_thread(analyze_input, display)
        logger.info("AI returned in %.1fs", time.time() - t0)
        if ai_result:
            thinking = ai_result.get("thinking", "")
            result_type = {"av": "🔞 AV 番号", "movie": "🎬 电影", "tv": "📺 剧集"}.get(ai_result["type"], ai_result["type"])
            ai_msg = f"🤖 AI 分析完成\n\n📄 `{display[:80]}`\n\n📌 识别: {result_type}\n🎯 片名: `{ai_result['name']}`"
            if thinking:
                ai_msg += f"\n\n💭 `{thinking[:200]}...`" if len(thinking) > 200 else f"\n\n💭 `{thinking}`"
            await msg.edit_text(ai_msg)
            await asyncio.sleep(0.5)

            if ai_result.get("type") == "av":
                dest = AV_DEST
                code = ai_result.get("av_code") or ai_result["name"]
                poster_code = code
                m = AV_CODE_RE.search(code)
                if m:
                    poster_code = m.group(1)
                logger.info("AI detected AV: dest=%s code=%s poster_code=%s", dest, code, poster_code)
                try:
                    poster_url = await asyncio.to_thread(fetch_av_poster, poster_code, proxies=PROXY)
                except Exception as e:
                    logger.warning("AV poster error: %s", e)
            else:
                clean_name = ai_result["name"]
                logger.info("AI movie name: %s", clean_name)
                try:
                    t0 = time.time()
                    poster_url = await asyncio.to_thread(fetch_movie_poster, clean_name, proxies=PROXY)
                    logger.info("TMDB poster %s in %.1fs", "OK" if poster_url else "miss", time.time() - t0)
                except Exception as e:
                    logger.warning("Movie poster error: %s", e)
        else:
            m = AV_CODE_RE.search(display)
            if m:
                dest = AV_DEST
                code = m.group(1).upper()
                logger.info("Regex fallback: AV detected code=%s", code)
                try:
                    poster_url = await asyncio.to_thread(fetch_av_poster, code, proxies=PROXY)
                except Exception as e:
                    logger.warning("AV poster error: %s", e)
            else:
                name_no_ext = os.path.splitext(display)[0]
                clean = re.split(r'\.(?:1080[pi]|2160[pi]|720[pi]|480[pi]|WEB[-.]?DL|BluRay|HDTV|HDRip|DVDRip|x?264|x?265|HEVC|AAC|AC3)\b', name_no_ext, flags=re.I)[0].replace('.', ' ').strip()
                try:
                    poster_url = await asyncio.to_thread(fetch_movie_poster, clean, proxies=PROXY)
                except Exception as e:
                    logger.warning("Movie poster fallback error: %s", e)
            logger.info("AI not available, used fallback poster search")

        gid = None
        try:
            gid = gopeed.add_uri(magnet, {"dir": dest})
            await msg.edit_text(f"📥 提交下载到 `{dest}`...")
            try:
                gid, files = gopeed.wait_for_metadata(gid, timeout=15)
                keep = filter_keep_files(files)
                if keep:
                    gopeed.set_select_file(gid, keep)
            except Exception as e:
                logger.warning("File filter error: %s", e)
        except Exception as e:
            await msg.edit_text(f"❌ 提交失败:\n`{str(e)[:200]}`")
            return

    await asyncio.sleep(1)

    offline_name = display

    task_id = f"{chat_id}_{int(time.time())}"

    is_photo = False
    if poster_url:
        t0 = time.time()
        poster_bytes = download_poster_bytes(poster_url, proxies=PROXY)
        logger.info("Download poster in %.1fs, %s bytes", time.time() - t0, len(poster_bytes) if poster_bytes else 0)
        if poster_bytes:
            is_photo = True
    poll_task = asyncio.create_task(poll_download(task_id, context))

    active_tasks[task_id] = {
        "chat_id": chat_id,
        "message_id": msg.message_id,
        "gid": gid,
        "name": offline_name,
        "magnet": magnet,
        "dest": dest,
        "source_name": display,
        "started": time.time(),
        "input_type": input_type,
        "poll_task": poll_task,
        "is_photo": is_photo,
    }
    _save_tasks()

    keyboard = [[InlineKeyboardButton("🗑 删除任务", callback_data=f"cancel_{task_id}")]]
    ic = TYPE_ICON.get(input_type, "🎬")
    initial_text = (
        f"📥 下载中\n\n"
        f"{ic} `{display}`\n"
        f"⏳ 准备中...\n"
        f"📂 目标: `{dest}`"
    )
    if is_photo:
        try:
            sent = await context.bot.send_photo(
                chat_id=chat_id,
                photo=poster_bytes,
                caption=initial_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            active_tasks[task_id]["message_id"] = sent.message_id
            await msg.delete()
        except Exception as e:
            logger.warning("send_photo failed: %s", e)
            active_tasks[task_id]["is_photo"] = False
            await msg.edit_text(initial_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await msg.edit_text(initial_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def poll_download(task_id, context):
    while task_id in active_tasks:
        await asyncio.sleep(POLL_INTERVAL)
        if task_id not in active_tasks:
            return

        task = active_tasks[task_id]
        gid = task.get("gid")

        if not gid:
            try:
                active_list = gopeed.tell_active() or []
                waiting = gopeed.tell_waiting(0, 10) or []
                for t in active_list + waiting:
                    files = t.get("files", [])
                    for f in files:
                        uris = f.get("uris", [])
                        for u in uris:
                            if task["magnet"] in u.get("uri", ""):
                                gid = t["gid"]
                                task["gid"] = gid
                                _save_tasks()
                                break
                        if gid:
                            break
                    if gid:
                        break
            except Exception as e:
                logger.warning("Failed to poll active/waiting tasks: %s", e)
            if not gid:
                continue

        try:
            status_data = gopeed.tell_status(gid)
        except Exception as e:
            logger.warning("Poll error %s: %s", task_id, e)
            continue

        aria_status = status_data.get("status")
        total = int(status_data.get("totalLength", 0))
        completed = int(status_data.get("completedLength", 0))
        speed = int(status_data.get("downloadSpeed", 0))

        # Get file name from gopeed response
        files = status_data.get("files", [])
        if files:
            task["name"] = os.path.basename(files[0].get("path", task["name"])) or task["name"]

        if aria_status == "complete" or (total > 0 and completed >= total):
            await on_download_complete(task_id, context)
            return

        if aria_status == "error":
            error_msg = status_data.get("errorMessage", "未知错误")
            kb = [[InlineKeyboardButton("🗑 删除任务", callback_data=f"cancel_{task_id}")]]
            await edit_progress(
                context, task,
                f"❌ 失败: `{task['source_name']}`\n`{error_msg[:100]}`",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            return

        if aria_status == "removed":
            kb = [[InlineKeyboardButton("🗑 删除任务", callback_data=f"cancel_{task_id}")]]
            await edit_progress(
                context, task,
                f"🗑 已删除: `{task['source_name']}`",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            return

        if total > 0:
            perc = (completed / total) * 100
            bar = progress_bar(perc)
            elapsed = int(time.time() - task["started"])
            speed_str = format_speed(speed)
            remaining = int((total - completed) / speed) if speed > 0 else 0
            kb = [[InlineKeyboardButton("🗑 删除任务", callback_data=f"cancel_{task_id}")]]
            await edit_progress(
                context, task,
                (
                    f"📥 下载中\n\n"
                    f"{icon(task)} `{task['source_name']}`\n"
                    f"`{bar}` {perc:.1f}%\n"
                    f"⚡ {speed_str} | ⏱ {format_elapsed(elapsed)} | 剩余 {format_elapsed(remaining)}\n"
                    f"📂 {format_size(completed / 1048576)} / {format_size(total / 1048576)}\n"
                    f"📁 目标: `{task['dest']}`"
                ),
                reply_markup=InlineKeyboardMarkup(kb),
            )
        else:
            elapsed = int(time.time() - task["started"])
            kb = [[InlineKeyboardButton("🗑 删除任务", callback_data=f"cancel_{task_id}")]]
            await edit_progress(
                context, task,
                (
                    f"📥 下载中\n\n"
                    f"{icon(task)} `{task['source_name']}`\n"
                    f"📂 目标: `{task['dest']}`"
                ),
                reply_markup=InlineKeyboardMarkup(kb),
            )


async def on_download_complete(task_id, context):
    task = active_tasks.get(task_id)
    if not task:
        return

    total_elapsed = int(time.time() - task["started"])
    final_path = os.path.join(task["dest"], task["name"])

    complete_text = (
        f"✅ 下载完成！\n\n"
        f"{icon(task)} `{task['source_name']}`\n"
        f"📂 路径: `{final_path}`\n"
        f"⏱ 用时: {format_elapsed(total_elapsed)}"
    )

    # Clean up gopeed download result
    gid = task.get("gid")
    if gid:
        try:
            gopeed.remove_download_result(gid)
        except Exception as e:
            logger.warning("Remove download result error: %s", e)

    await edit_progress(context, task, complete_text)

    _save_tasks()
    if task_id in active_tasks:
        del active_tasks[task_id]


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _touch()
    query = update.callback_query
    await query.answer()

    task_id = query.data[7:]
    task = active_tasks.get(task_id)

    if not task:
        await query.edit_message_text("任务已完成。")
        return

    poll_task = task.get("poll_task")
    if poll_task:
        poll_task.cancel()

    # Remove gopeed task
    gid = task.get("gid")
    if gid:
        try:
            gopeed.force_remove(gid)
        except Exception as e:
            logger.warning("Force remove error: %s", e)

    await edit_progress(context, task, f"🗑 已取消 `{task['source_name']}`")
    _save_tasks()
    del active_tasks[task_id]


async def handle_movie_search(update, context, keyword):
    msg = await update.message.reply_text(f"🔍 搜索 `{keyword}`...")
    try:
        candidates = await asyncio.to_thread(hgme_search, keyword)
    except Exception as e:
        await msg.edit_text(f"❌ 搜索失败:\n`{str(e)[:200]}`")
        return

    if not candidates:
        await msg.edit_text(f"😵 未找到 `{keyword}` 的结果")
        return

    token = secrets.token_hex(4)
    _pending_searches[token] = (keyword, candidates)
    _pending_created[token] = time.time()

    keyboard = []
    for c in candidates[:6]:
        rating = ""
        m = re.search(r"豆瓣 ([\d.]+)", c.score)
        if m:
            rating = m.group(1)
        label = f"🎬 {c.title} ({c.year}) ⭐{rating}" if c.year and rating else f"🎬 {c.title} ⭐{rating}" if rating else f"🎬 {c.title} ({c.year})" if c.year else f"🎬 {c.title}"
        callback = f"hgme_{token}_{c.kind}_{c.id}"
        keyboard.append([InlineKeyboardButton(label, callback_data=callback)])

    await msg.edit_text(
        f"📋 找到 {len(candidates)} 个结果，请选择👇",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_hgme_select(update, context):
    _touch()
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_", 3)
    if len(parts) < 4:
        await query.edit_message_text("❌ 无效选择，请重新搜索")
        return
    search_token = parts[1]
    kind = parts[2]
    id_ = parts[3]

    try:
        items = await asyncio.to_thread(hgme_get_torrents, kind, id_)
    except Exception as e:
        await query.edit_message_text(f"❌ 获取资源失败:\n`{str(e)[:200]}`")
        return

    token = secrets.token_hex(4)
    _pending_magnets[token] = items
    _pending_created[token] = time.time()

    keyboard = []
    for i, item in enumerate(items):
        label = f"{item.size} [{item.tag}] {item.title[:50]}"
        callback = f"mg_{token}_{i}"
        keyboard.append([InlineKeyboardButton(label, callback_data=callback)])

    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data=f"back_{search_token}")])

    msg = f"📦 中字资源 ({len(items)} 条)，请选择👇" if items else "😵 未找到中字资源"
    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_magnet_select(update, context):
    _touch()
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_", 2)
    token = parts[1]
    idx = int(parts[2]) if len(parts) > 2 else 0

    items = _pending_magnets.pop(token, None)
    if not items or idx >= len(items):
        await query.edit_message_text("⏰ 选择已过期，请重新搜索")
        return

    item = items[idx]
    magnet = item.magnet
    display = item.title

    if not gopeed.ping():
        await query.edit_message_text("❌ Gopeed 连接失败。")
        return

    await query.edit_message_text(f"📥 提交下载...\n\n`{display[:100]}`")

    gid = None
    try:
        gid = gopeed.add_uri(magnet, {"dir": BT_DEST})
        try:
            gid, files = gopeed.wait_for_metadata(gid, timeout=15)
            keep = filter_keep_files(files)
            if keep:
                gopeed.set_select_file(gid, keep)
        except Exception as e:
            logger.warning("File filter error: %s", e)
    except Exception as e:
        await query.edit_message_text(f"❌ 提交失败:\n`{str(e)[:200]}`")
        return

    await asyncio.sleep(1)

    offline_name = display

    task_id = f"{query.message.chat_id}_{int(time.time())}"
    chat_id = query.message.chat_id

    poster_url = None
    ai_result = await asyncio.to_thread(analyze_input, display)
    if ai_result and ai_result.get("name"):
        clean_name = ai_result["name"]
        logger.info("AI: magnet_select -> name=%s", clean_name)
        if ai_result.get("type") == "av":
            poster_url = await asyncio.to_thread(fetch_av_poster, clean_name, proxies=PROXY)
        else:
            poster_url = await asyncio.to_thread(fetch_movie_poster, clean_name, proxies=PROXY)
    else:
        name_no_ext = os.path.splitext(display)[0]
        clean_name = re.split(r'\.(?:1080[pi]|2160[pi]|720[pi]|480[pi]|WEB[-.]?DL|BluRay|HDTV|HDRip|DVDRip|x?264|x?265|HEVC|AAC|AC3)\b', name_no_ext, flags=re.I)[0].replace('.', ' ').strip()
        try:
            poster_url = await asyncio.to_thread(fetch_movie_poster, clean_name, proxies=PROXY)
        except Exception as e:
            logger.warning("Movie poster error: %s", e)

    poll_task = asyncio.create_task(poll_download(task_id, context))

    dest = BT_DEST
    is_photo = False
    poster_bytes = None
    if poster_url:
        try:
            poster_bytes = download_poster_bytes(poster_url, proxies=PROXY)
            if poster_bytes:
                is_photo = True
        except Exception as e:
            logger.warning("Failed to download poster bytes: %s", e)

    active_tasks[task_id] = {
        "chat_id": chat_id,
        "message_id": query.message.message_id,
        "gid": gid,
        "name": offline_name,
        "magnet": magnet,
        "dest": dest,
        "source_name": display,
        "started": time.time(),
        "input_type": "bt",
        "poll_task": poll_task,
        "is_photo": is_photo,
    }
    _save_tasks()

    keyboard = [[InlineKeyboardButton("🗑 删除任务", callback_data=f"cancel_{task_id}")]]
    initial_text = (
        f"📥 离线下载中\n\n"
        f"🎬 `{display}`\n"
        f"⏳ 准备中...\n"
        f"📂 目标: `{BT_DEST}`"
    )
    if is_photo and poster_bytes:
        try:
            sent = await context.bot.send_photo(
                chat_id=chat_id,
                photo=poster_bytes,
                caption=initial_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            active_tasks[task_id]["message_id"] = sent.message_id
            try:
                await query.message.delete()
            except Exception as e:
                logger.warning("Failed to delete query message: %s", e)
        except Exception as e:
            logger.warning("send_photo failed: %s", e)
            active_tasks[task_id]["is_photo"] = False
            await query.edit_message_text(initial_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.edit_message_text(initial_text, reply_markup=InlineKeyboardMarkup(keyboard))


_last_update_time = time.time()


def _watchdog():
    """Watchdog: if no updates for 10 minutes, force restart."""
    while True:
        time.sleep(60)
        idle = time.time() - _last_update_time
        if idle > 600:
            logger.error(f"[WATCHDOG] No updates for {int(idle)}s, killing process for restart")
            os._exit(1)


def _touch():
    global _last_update_time
    _last_update_time = time.time()
async def handle_back_select(update, context):
    _touch()
    query = update.callback_query
    await query.answer()

    search_token = query.data.split("_", 1)[1]
    entry = _pending_searches.get(search_token)
    if not entry:
        await query.edit_message_text("⏰ 选择已过期，请重新搜索")
        return

    _, candidates = entry
    keyboard = []
    for c in candidates[:6]:
        rating = ""
        m = re.search(r"豆瓣 ([\d.]+)", c.score)
        if m:
            rating = m.group(1)
        label = f"🎬 {c.title} ({c.year}) ⭐{rating}" if c.year and rating else f"🎬 {c.title} ⭐{rating}" if rating else f"🎬 {c.title} ({c.year})" if c.year else f"🎬 {c.title}"
        callback = f"hgme_{search_token}_{c.kind}_{c.id}"
        keyboard.append([InlineKeyboardButton(label, callback_data=callback)])

    await query.edit_message_text(
        f"📋 找到 {len(candidates)} 个结果，请选择👇",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def main():
    if not gopeed.ping():
        logger.error("Gopeed connection failed!")
        sys.exit(1)
    logger.info("Gopeed connected, starting bot...")

    from telegram.request import HTTPXRequest
    req = HTTPXRequest(
        proxy=PROXY_URL,
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
    )
    bot = telegram.Bot(token=BOT_TOKEN, request=req)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(req)
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=0)
    app.add_handler(CallbackQueryHandler(handle_cancel, pattern=r"^cancel_"), group=0)
    app.add_handler(CallbackQueryHandler(handle_hgme_select, pattern=r"^hgme_"), group=0)
    app.add_handler(CallbackQueryHandler(handle_magnet_select, pattern=r"^mg_"), group=0)
    app.add_handler(CallbackQueryHandler(handle_back_select, pattern=r"^back_"), group=0)

    offset = None

    async def _run():
        nonlocal offset
        await app.initialize()
        saved = _load_tasks()
        count = 0
        for tid, task in list(saved.items()):
            gid = task.get("gid")
            if gid:
                try:
                    status = gopeed.tell_status(gid)
                    if status.get("status") in ("complete", "removed", "error"):
                        continue
                except Exception as e:
                    logger.warning("Failed to check task status during recovery: %s", e)
            task["poll_task"] = None
            active_tasks[tid] = task
            poll_task = asyncio.create_task(poll_download(tid, app))
            active_tasks[tid]["poll_task"] = poll_task
            count += 1
        if count:
            logger.info("Recovered %d active tasks", count)
            _save_tasks()
        else:
            try:
                os.remove(TASKS_FILE)
            except Exception as e:
                logger.warning("Failed to remove tasks file: %s", e)

        logger.info("Starting polling with watchdog...")
        _touch()

        # Close any existing polling session
        try:
            async with httpx.AsyncClient(proxy=PROXY_URL, timeout=10) as c:
                await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", json={"offset": -1, "timeout": 0})
                await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/close")
        except Exception as e:
            logger.warning("Failed to close old polling session: %s", e)

        while True:
            _cleanup_pending()
            try:
                data = None
                async with httpx.AsyncClient(proxy=PROXY_URL, timeout=35) as c:
                    resp = await c.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                        json={"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]},
                    )
                    data = resp.json()
                _touch()
                if data and not data.get("ok"):
                    logger.warning("Telegram API error: %s", data.get("description"))
                    await asyncio.sleep(5)
                    continue
                for update_data in data.get("result", []):
                    update = telegram.Update.de_json(update_data, bot)
                    offset = update.update_id + 1
                    try:
                        await app.process_update(update)
                    except Exception as e:
                        logger.warning("Process update error: %s", str(e)[:200])
            except Exception as e:
                logger.warning("Poll error: %s", str(e)[:200])
                await asyncio.sleep(3)

    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()
    asyncio.run(_run())




if __name__ == "__main__":
    main()

