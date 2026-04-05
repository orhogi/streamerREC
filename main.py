import asyncio
import json
import os
import re
import shutil
import signal
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PI_MODE = os.environ.get("STREAMREC_PI_MODE", "0") == "1"

app = FastAPI(title="StreamRec API")

RECORDINGS_DIR = Path("/recordings")
RECORDINGS_DIR.mkdir(exist_ok=True)
STATE_FILE = RECORDINGS_DIR / "state.json"

# Limit concurrent yt-dlp / ffmpeg subprocesses (Pi has limited RAM+CPU)
_proc_semaphore = asyncio.Semaphore(3 if PI_MODE else 6)

channels: dict[str, dict] = {}
recordings: dict[str, dict] = {}

# Disk-usage cache to avoid expensive rglob on every request
_disk_cache: dict = {}
_disk_cache_ts: float = 0

settings: dict = {
    "monitor_interval": 120 if PI_MODE else 60,
    "default_quality": "best",
    "default_format": "mp4",
    "auto_convert_mp4": False,
    "delete_original": False,
    "record_on_add": False,
    "auto_retry": True,
    "max_retries": 5,
    "retry_delay": 15,
}


def _save_state():
    """Persist channels and settings to disk."""
    # Strip runtime-only keys from channels before saving
    saved_channels = {}
    for cid, ch in channels.items():
        c = dict(ch)
        c.pop("recording_id", None)
        c.pop("is_live", None)
        c.pop("last_checked", None)
        saved_channels[cid] = c
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"channels": saved_channels, "settings": settings}, indent=2))
        tmp.replace(STATE_FILE)
    except Exception:
        pass


def _load_state():
    """Restore channels and settings from disk."""
    global settings
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text())
        for cid, ch in data.get("channels", {}).items():
            ch["recording_id"] = None
            ch["is_live"] = False
            ch["last_checked"] = None
            channels[cid] = ch
        saved_settings = data.get("settings", {})
        for k, v in saved_settings.items():
            if k in settings:
                settings[k] = v
    except Exception:
        pass

PLATFORM_MAP = [
    (r"youtube\.com|youtu\.be",  "YouTube"),
    (r"twitch\.tv",              "Twitch"),
    (r"tiktok\.com",             "TikTok"),
    (r"kick\.com",               "Kick"),
    (r"bilibili\.com",           "Bilibili"),
    (r"douyin\.com",             "Douyin"),
    (r"afreecatv\.com",          "Afreeca"),
    (r"sooplive\.co",            "Sooplive"),
    (r"naver\.com",              "Naver"),
    (r"weibo\.com",              "Weibo"),
    (r"huya\.com",               "Huya"),
    (r"douyu\.com",              "Douyu"),
    (r"nicovideo\.jp",           "Niconico"),
    (r"dailymotion\.com",        "Dailymotion"),
    (r"facebook\.com|fb\.watch", "Facebook"),
    (r"instagram\.com",          "Instagram"),
    (r"twitter\.com|x\.com",     "Twitter/X"),
    (r"vimeo\.com",              "Vimeo"),
    (r"rumble\.com",             "Rumble"),
    (r"stripchat\.com",          "Stripchat"),
    (r"twitcasting\.tv",         "Twitcasting"),
    (r"pandalive\.co",           "Pandalive"),
    (r"bigo\.tv",                "Bigo"),
]

def detect_platform(url: str) -> str:
    for pattern, name in PLATFORM_MAP:
        if re.search(pattern, url, re.I):
            return name
    return "Unknown"


async def fetch_metadata(url: str) -> dict:
    try:
        async with _proc_semaphore:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--dump-single-json", "--no-download",
                "--playlist-items", "1", "--socket-timeout", "15", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0 or not stdout:
            return {}
        data = json.loads(stdout)
        thumbnails = data.get("thumbnails") or []
        thumbnail = data.get("thumbnail") or (thumbnails[-1]["url"] if thumbnails else "")
        avatar = ""
        for t in reversed(thumbnails):
            tid = (t.get("id") or "").lower()
            if "avatar" in tid or "profile" in tid:
                avatar = t.get("url", "")
                break
        if not avatar:
            avatar = await _try_scrape_avatar(url)
        return {
            "display_name": data.get("uploader") or data.get("channel") or data.get("creator") or "",
            "username":     data.get("uploader_id") or data.get("channel_id") or "",
            "avatar":       avatar,
            "thumbnail":    thumbnail,
            "is_live":      bool(data.get("is_live")),
        }
    except Exception:
        return {}


async def _try_scrape_avatar(url: str) -> str:
    """Try to scrape avatar from the page HTML (works for TikTok, etc)."""
    try:
        async with _proc_semaphore:
            proc = await asyncio.create_subprocess_exec(
            "curl", "-sL", "--max-time", "10", "-A",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        if not stdout:
            return ""
        html = stdout.decode("utf-8", errors="replace")
        # TikTok embeds avatar URLs in JSON-LD or meta tags
        m = re.search(r'"avatarLarger"\s*:\s*"([^"]+)"', html)
        if m:
            return m.group(1).replace(r'\u002F', '/')
        m = re.search(r'"avatarMedium"\s*:\s*"([^"]+)"', html)
        if m:
            return m.group(1).replace(r'\u002F', '/')
        m = re.search(r'"avatarThumb"\s*:\s*"([^"]+)"', html)
        if m:
            return m.group(1).replace(r'\u002F', '/')
        # Generic og:image avatar pattern
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\'>]+)["\']', html, re.I)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


async def check_is_live(url: str) -> bool:
    try:
        async with _proc_semaphore:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--simulate", "--no-warnings",
                "--socket-timeout", "20", "--playlist-items", "1", url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        try:
            await asyncio.wait_for(proc.wait(), timeout=35)
        except asyncio.TimeoutError:
            proc.kill()
            return False
        return proc.returncode == 0
    except Exception:
        return False


async def _start_recording_for_channel(ch_id: str) -> Optional[str]:
    ch = channels.get(ch_id)
    if not ch:
        return None
    existing = ch.get("recording_id")
    if existing and existing in recordings and recordings[existing]["status"] in ("recording", "starting"):
        return None
    rec_id = str(uuid.uuid4())[:8]
    recordings[rec_id] = {
        "id": rec_id,
        "channel_id": ch_id,
        "url": ch["url"],
        "platform": ch["platform"],
        "quality": ch.get("quality") or settings["default_quality"],
        "format": ch.get("format") or settings["default_format"],
        "status": "starting",
        "created_at": time.time(),
        "started_at": None,
        "ended_at": None,
        "bytes": 0,
        "speed": None,
        "filepath": None,
        "filename": None,
        "log": [],
        "stopping": False,
        "auto": False,
    }
    channels[ch_id]["recording_id"] = rec_id
    asyncio.create_task(run_recording(rec_id))
    return rec_id


async def run_recording(rec_id: str):
    rec = recordings[rec_id]
    ch  = channels.get(rec["channel_id"], {})
    quality = rec.get("quality") or settings["default_quality"]
    fmt     = rec.get("format")  or settings["default_format"]
    url     = rec["url"]
    platform_raw = rec.get("platform") or "Unknown"
    platform = platform_raw.lower()
    username = ch.get("display_name") or ch.get("username") or rec_id
    # Sanitise for filesystem
    safe_platform = re.sub(r'[^\w\-]', '_', platform_raw)
    safe_username = re.sub(r'[^\w\-]', '_', username)
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M-%S")
    rec_dir = RECORDINGS_DIR / safe_platform / safe_username / date_str
    rec_dir.mkdir(parents=True, exist_ok=True)
    filename_stem = f"{safe_username}_{date_str}_{time_str}"
    output_path = rec_dir / f"{filename_stem}.%(ext)s"

    cmd = ["yt-dlp", "--no-part"]
    record_from_start = ch.get("record_from_start", True)
    if record_from_start and platform not in ("tiktok", "kick", "stripchat", "bigo", "pandalive"):
        cmd += ["--live-from-start", "--hls-use-mpegts"]
    cmd += [
        "--retries", "infinite", "--fragment-retries", "infinite",
        "--retry-sleep", "5", "--socket-timeout", "30",
        "--no-warnings", "--newline",
        "--concurrent-fragments", "1",
        "--downloader-args", "ffmpeg:-threads 2",
        "-f", quality,
        "--merge-output-format", fmt,
        "--progress", "--print", "after_move:filepath",
        "-o", str(output_path), url,
    ]

    rec["status"] = "recording"
    rec["started_at"] = time.time()
    rec["log"] = []
    size_task = None

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        rec["pid"] = proc.pid

        async def _poll_size():
            while True:
                await asyncio.sleep(10)
                for f in rec_dir.glob(f"{filename_stem}.*"):
                    try:
                        sz = f.stat().st_size
                        if sz > 0:
                            rec["bytes"] = sz
                    except Exception:
                        pass
                    break
        size_task = asyncio.create_task(_poll_size())

        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            rec["log"].append(line)
            if len(rec["log"]) > 100:
                rec["log"] = rec["log"][-50:]
            if "[download]" in line:
                m = re.search(r"(\d+\.?\d*)\s*(GiB|MiB|KiB|B)\b", line)
                if m:
                    v = float(m.group(1))
                    u = {"GiB": 1024**3, "MiB": 1024**2, "KiB": 1024, "B": 1}[m.group(2)]
                    rec["bytes"] = int(v * u)
                m2 = re.search(r"at\s+(\d+\.?\d*\s*(?:GiB|MiB|KiB|B)/s)", line)
                if m2:
                    rec["speed"] = m2.group(1)
            if line.startswith("/recordings/") and not line.startswith("["):
                rec["filepath"] = line
                rec["filename"] = Path(line).name

        await proc.wait()
        rc = proc.returncode
        rec["status"] = "completed" if (rc == 0 or rec.get("stopping")) else "error"
        if rc != 0 and not rec.get("stopping"):
            rec["error"] = f"Exit code {rc}"

    except Exception as e:
        rec["status"] = "error"
        rec["error"] = str(e)

    finally:
        if size_task:
            size_task.cancel()
        rec["ended_at"] = time.time()
        rec.pop("pid", None)

        if not rec.get("filepath"):
            for f in rec_dir.glob(f"{filename_stem}.*"):
                rec["filepath"] = str(f)
                rec["filename"] = f.name
                break

        if fp := rec.get("filepath"):
            try:
                rec["bytes"] = Path(fp).stat().st_size
            except:
                pass

        # Always remux to fix broken containers from interrupted recordings
        fp = rec.get("filepath", "")
        if fp and Path(fp).exists() and rec.get("stopping"):
            fixed_path = fp.rsplit(".", 1)[0] + "_fixed." + fp.rsplit(".", 1)[-1]
            try:
                fix_proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-i", fp, "-c", "copy", "-movflags", "+faststart",
                    "-threads", "2",
                    fixed_path, "-y",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(fix_proc.wait(), timeout=120)
                if fix_proc.returncode == 0 and Path(fixed_path).exists():
                    Path(fp).unlink(missing_ok=True)
                    Path(fixed_path).rename(fp)
                    try:
                        rec["bytes"] = Path(fp).stat().st_size
                    except:
                        pass
                else:
                    Path(fixed_path).unlink(missing_ok=True)
            except Exception:
                Path(fixed_path).unlink(missing_ok=True)

        auto_convert = ch.get("auto_convert_mp4", settings["auto_convert_mp4"])
        delete_orig  = ch.get("delete_original",  settings["delete_original"])
        fp = rec.get("filepath", "")

        if auto_convert and fp and not fp.endswith(".mp4") and Path(fp).exists():
            mp4_path = fp.rsplit(".", 1)[0] + ".mp4"
            try:
                conv = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-i", fp, "-c", "copy", "-threads", "2",
                    mp4_path, "-y",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await conv.wait()
                if conv.returncode == 0:
                    if delete_orig:
                        Path(fp).unlink(missing_ok=True)
                    rec["filepath"] = mp4_path
                    rec["filename"] = Path(mp4_path).name
                    try:
                        rec["bytes"] = Path(mp4_path).stat().st_size
                    except:
                        pass
            except Exception:
                pass

        if ch_id := rec.get("channel_id"):
            if ch_id in channels:
                channels[ch_id]["recording_id"] = None
                channels[ch_id]["is_live"] = False

        # Auto-retry on non-manual stop
        retry_ch_id = rec.get("channel_id")
        should_retry = (
            not rec.get("stopping")
            and rec.get("status") == "error"
            and settings.get("auto_retry", True)
            and retry_ch_id
            and retry_ch_id in channels
            and channels[retry_ch_id].get("monitoring", True)
        )
        if should_retry:
            attempt = rec.get("_retry_attempt", 0) + 1
            max_retries = settings.get("max_retries", 5)
            delay = settings.get("retry_delay", 15)
            if attempt <= max_retries:
                rec["log"].append(f"[StreamRec] Stream disconnected. Retrying in {delay}s (attempt {attempt}/{max_retries})…")
                await asyncio.sleep(delay)
                if retry_ch_id in channels and not channels[retry_ch_id].get("recording_id"):
                    new_rec_id = await _start_recording_for_channel(retry_ch_id)
                    if new_rec_id:
                        recordings[new_rec_id]["_retry_attempt"] = attempt
                        recordings[new_rec_id]["auto"] = True


async def monitor_loop():
    while True:
        interval = settings.get("monitor_interval", 60)
        await asyncio.sleep(interval)
        for ch_id, ch in list(channels.items()):
            if not ch.get("monitoring", True):
                continue
            existing_rec_id = ch.get("recording_id")
            if existing_rec_id and existing_rec_id in recordings:
                r = recordings[existing_rec_id]
                if r["status"] in ("recording", "starting"):
                    channels[ch_id]["is_live"] = True
                    channels[ch_id]["last_checked"] = time.time()
                    continue
            is_live = await check_is_live(ch["url"])
            channels[ch_id]["is_live"] = is_live
            channels[ch_id]["last_checked"] = time.time()
            if is_live:
                rec_id = await _start_recording_for_channel(ch_id)
                if rec_id:
                    recordings[rec_id]["auto"] = True


@app.on_event("startup")
async def startup():
    _load_state()
    asyncio.create_task(monitor_loop())


class AddChannelRequest(BaseModel):
    url: str
    quality: str = ""
    format: str = ""
    monitoring: bool = True
    auto_convert_mp4: bool = False
    delete_original: bool = False
    record_now: bool = False
    record_from_start: bool = True

class UpdateChannelRequest(BaseModel):
    monitoring: Optional[bool] = None
    quality: Optional[str] = None
    format: Optional[str] = None
    auto_convert_mp4: Optional[bool] = None
    delete_original: Optional[bool] = None
    record_from_start: Optional[bool] = None

class UpdateSettingsRequest(BaseModel):
    monitor_interval: Optional[int] = None
    default_quality: Optional[str] = None
    default_format: Optional[str] = None
    auto_convert_mp4: Optional[bool] = None
    delete_original: Optional[bool] = None
    record_on_add: Optional[bool] = None
    auto_retry: Optional[bool] = None
    max_retries: Optional[int] = None
    retry_delay: Optional[int] = None


@app.post("/api/channels")
async def add_channel(req: AddChannelRequest):
    ch_id = str(uuid.uuid4())[:8]
    platform = detect_platform(req.url)
    ch = {
        "id": ch_id, "url": req.url, "platform": platform,
        "quality": req.quality, "format": req.format,
        "monitoring": req.monitoring,
        "auto_convert_mp4": req.auto_convert_mp4,
        "delete_original": req.delete_original,
        "record_from_start": req.record_from_start,
        "created_at": time.time(),
        "display_name": "", "username": "", "avatar": "", "thumbnail": "",
        "is_live": False, "last_checked": None, "recording_id": None,
    }
    channels[ch_id] = ch

    async def fetch_and_maybe_record():
        meta = await fetch_metadata(req.url)
        if meta and ch_id in channels:
            channels[ch_id].update({
                "display_name": meta.get("display_name", ""),
                "username":     meta.get("username", ""),
                "avatar":       meta.get("avatar", ""),
                "thumbnail":    meta.get("thumbnail", ""),
                "is_live":      meta.get("is_live", False),
                "last_checked": time.time(),
            })
            _save_state()

    asyncio.create_task(fetch_and_maybe_record())

    if req.record_now:
        asyncio.create_task(_start_recording_for_channel(ch_id))

    _save_state()
    return {"id": ch_id, "platform": platform}


@app.get("/api/channels")
async def list_channels():
    result = []
    for ch in channels.values():
        c = dict(ch)
        rec_id = c.get("recording_id")
        if rec_id and rec_id in recordings:
            r = recordings[rec_id]
            c["rec_status"]  = r["status"]
            c["rec_bytes"]   = r.get("bytes", 0)
            c["rec_speed"]   = r.get("speed")
            c["rec_started"] = r.get("started_at")
            c["rec_id"]      = rec_id
        else:
            c["rec_status"] = None; c["rec_bytes"] = 0
            c["rec_speed"] = None; c["rec_started"] = None; c["rec_id"] = None
        result.append(c)
    return sorted(result, key=lambda x: (x.get("sort_order", 9999), -x["created_at"]))


@app.patch("/api/channels/{ch_id}")
async def update_channel(ch_id: str, req: UpdateChannelRequest):
    if ch_id not in channels:
        raise HTTPException(404, "Not found")
    for field, val in req.model_dump(exclude_none=True).items():
        channels[ch_id][field] = val
    _save_state()
    return channels[ch_id]


@app.post("/api/channels/{ch_id}/record")
async def record_channel(ch_id: str):
    rec_id = await _start_recording_for_channel(ch_id)
    if not rec_id:
        raise HTTPException(400, "Already recording or not found")
    return {"rec_id": rec_id}


@app.post("/api/channels/{ch_id}/stop")
async def stop_channel(ch_id: str):
    ch = channels.get(ch_id)
    if not ch:
        raise HTTPException(404, "Not found")
    rec_id = ch.get("recording_id")
    if not rec_id or rec_id not in recordings:
        raise HTTPException(400, "Not recording")
    rec = recordings[rec_id]
    rec["stopping"] = True
    if pid := rec.get("pid"):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    return {"ok": True}


@app.post("/api/channels/{ch_id}/kill")
async def kill_channel(ch_id: str):
    ch = channels.get(ch_id)
    if not ch:
        raise HTTPException(404, "Not found")
    rec_id = ch.get("recording_id")
    if not rec_id or rec_id not in recordings:
        raise HTTPException(400, "Not recording")
    rec = recordings[rec_id]
    rec["stopping"] = True
    if pid := rec.get("pid"):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    rec["status"] = "completed"
    rec["ended_at"] = time.time()
    channels[ch_id]["recording_id"] = None
    return {"ok": True}


@app.post("/api/channels/{ch_id}/refresh")
async def refresh_channel(ch_id: str):
    ch = channels.get(ch_id)
    if not ch:
        raise HTTPException(404, "Not found")
    meta = await fetch_metadata(ch["url"])
    if meta:
        channels[ch_id].update({
            "display_name": meta.get("display_name") or ch["display_name"],
            "username":     meta.get("username") or ch["username"],
            "avatar":       meta.get("avatar") or ch.get("avatar", ""),
            "thumbnail":    meta.get("thumbnail") or ch["thumbnail"],
            "is_live":      meta.get("is_live", False),
            "last_checked": time.time(),
        })
    return channels[ch_id]


@app.delete("/api/channels/{ch_id}")
async def delete_channel(ch_id: str):
    ch = channels.pop(ch_id, None)
    if not ch:
        raise HTTPException(404, "Not found")
    rec_id = ch.get("recording_id")
    if rec_id and rec_id in recordings:
        rec = recordings[rec_id]
        rec["stopping"] = True
        if pid := rec.get("pid"):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
    _save_state()
    return {"ok": True}


@app.get("/api/recordings")
async def list_recordings():
    result = []
    for rec in recordings.values():
        r = dict(rec); r.pop("log", None)
        result.append(r)
    return sorted(result, key=lambda x: x["created_at"], reverse=True)


@app.get("/api/recordings/{rec_id}/log")
async def get_log(rec_id: str):
    rec = recordings.get(rec_id)
    if not rec:
        raise HTTPException(404, "Not found")
    return {"log": rec.get("log", [])}


@app.get("/api/download/{rec_id}")
async def download_recording(rec_id: str):
    rec = recordings.get(rec_id)
    if not rec:
        raise HTTPException(404, "Not found")
    fp = rec.get("filepath")
    if not fp or not Path(fp).exists():
        raise HTTPException(404, "File not found")
    return FileResponse(fp, filename=rec.get("filename", f"{rec_id}.mp4"))


@app.delete("/api/recordings/{rec_id}")
async def delete_recording(rec_id: str):
    rec = recordings.pop(rec_id, None)
    if not rec:
        raise HTTPException(404, "Not found")
    if fp := rec.get("filepath"):
        try:
            Path(fp).unlink()
        except:
            pass
    return {"ok": True}


@app.get("/api/settings")
async def get_settings():
    return settings


@app.patch("/api/settings")
async def update_settings(req: UpdateSettingsRequest):
    for field, val in req.model_dump(exclude_none=True).items():
        settings[field] = val
    _save_state()
    return settings


@app.get("/api/health")
async def health():
    return {"ok": True, "channels": len(channels), "recordings": len(recordings)}


@app.get("/api/preview/{rec_id}")
async def preview_recording(rec_id: str, request: Request):
    rec = recordings.get(rec_id)
    if not rec:
        raise HTTPException(404, "Not found")
    fp = rec.get("filepath")
    if not fp or not Path(fp).exists():
        raise HTTPException(404, "File not found")
    file_path = Path(fp)
    file_size = file_path.stat().st_size
    content_type = "video/mp4" if fp.endswith(".mp4") else "video/x-matroska" if fp.endswith(".mkv") else "video/mp2t"

    range_header = request.headers.get("range")
    if range_header:
        start_str = range_header.replace("bytes=", "").split("-")[0]
        start = int(start_str)
        end = min(start + 2 * 1024 * 1024, file_size - 1)
        length = end - start + 1

        def iterfile():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iterfile(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )
    return FileResponse(fp, media_type=content_type)


class ReorderRequest(BaseModel):
    order: list[str]


@app.post("/api/channels/reorder")
async def reorder_channels(req: ReorderRequest):
    for i, ch_id in enumerate(req.order):
        if ch_id in channels:
            channels[ch_id]["sort_order"] = i
    _save_state()
    return {"ok": True}


class BulkActionRequest(BaseModel):
    ids: list[str]
    action: str  # "record", "stop", "delete"


@app.post("/api/channels/bulk")
async def bulk_action(req: BulkActionRequest):
    results = []
    for ch_id in req.ids:
        try:
            if req.action == "record":
                rid = await _start_recording_for_channel(ch_id)
                results.append({"id": ch_id, "ok": bool(rid)})
            elif req.action == "stop":
                ch = channels.get(ch_id)
                if ch and ch.get("recording_id"):
                    rec = recordings.get(ch["recording_id"])
                    if rec:
                        rec["stopping"] = True
                        if pid := rec.get("pid"):
                            try:
                                os.killpg(os.getpgid(pid), signal.SIGTERM)
                            except (ProcessLookupError, PermissionError, OSError):
                                try:
                                    os.kill(pid, signal.SIGTERM)
                                except ProcessLookupError:
                                    pass
                results.append({"id": ch_id, "ok": True})
            elif req.action == "delete":
                ch = channels.pop(ch_id, None)
                if ch:
                    rec_id = ch.get("recording_id")
                    if rec_id and rec_id in recordings:
                        rec = recordings[rec_id]
                        rec["stopping"] = True
                        if pid := rec.get("pid"):
                            try:
                                os.killpg(os.getpgid(pid), signal.SIGTERM)
                            except (ProcessLookupError, PermissionError, OSError):
                                try:
                                    os.kill(pid, signal.SIGTERM)
                                except ProcessLookupError:
                                    pass
                results.append({"id": ch_id, "ok": True})
        except Exception:
            results.append({"id": ch_id, "ok": False})
    _save_state()
    return {"results": results}


@app.get("/api/disk")
async def disk_usage():
    global _disk_cache, _disk_cache_ts
    now = time.time()
    if _disk_cache and now - _disk_cache_ts < 30:
        return _disk_cache
    try:
        usage = shutil.disk_usage(str(RECORDINGS_DIR))
        # Calculate recordings folder size (can be slow on Pi with many files)
        rec_bytes = sum(f.stat().st_size for f in RECORDINGS_DIR.rglob("*") if f.is_file() and f.name != "state.json")
        _disk_cache = {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "recordings_bytes": rec_bytes,
        }
        _disk_cache_ts = now
        return _disk_cache
    except Exception:
        return {"total": 0, "used": 0, "free": 0, "recordings_bytes": 0}


@app.get("/api/export")
async def export_config():
    saved_channels = {}
    for cid, ch in channels.items():
        c = dict(ch)
        for k in ("recording_id", "is_live", "last_checked"):
            c.pop(k, None)
        saved_channels[cid] = c
    return {"channels": saved_channels, "settings": settings}


class ImportRequest(BaseModel):
    channels: dict = {}
    settings: dict = {}
    merge: bool = True


@app.post("/api/import")
async def import_config(req: ImportRequest):
    imported = 0
    for cid, ch in req.channels.items():
        if req.merge and cid in channels:
            continue
        ch["recording_id"] = None
        ch["is_live"] = False
        ch["last_checked"] = None
        if "id" not in ch:
            ch["id"] = cid
        if "created_at" not in ch:
            ch["created_at"] = time.time()
        channels[cid] = ch
        imported += 1
    for k, v in req.settings.items():
        if k in settings:
            settings[k] = v
    _save_state()
    return {"ok": True, "imported_channels": imported}


app.mount("/", StaticFiles(directory="/app", html=True), name="static")
