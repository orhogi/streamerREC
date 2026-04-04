import asyncio
import json
import os
import re
import signal
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="StreamRec API")

RECORDINGS_DIR = Path("/recordings")
RECORDINGS_DIR.mkdir(exist_ok=True)

channels: dict[str, dict] = {}
recordings: dict[str, dict] = {}

settings: dict = {
    "monitor_interval": 60,
    "default_quality": "best",
    "default_format": "mp4",
    "auto_convert_mp4": False,
    "delete_original": False,
    "record_on_add": False,
}

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
        return {
            "display_name": data.get("uploader") or data.get("channel") or data.get("creator") or "",
            "username":     data.get("uploader_id") or data.get("channel_id") or "",
            "avatar":       "",
            "thumbnail":    thumbnail,
            "is_live":      bool(data.get("is_live")),
        }
    except Exception:
        return {}


async def check_is_live(url: str) -> bool:
    try:
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
    output_path = RECORDINGS_DIR / f"{rec_id}.%(ext)s"

    cmd = [
        "yt-dlp", "--no-part", "--live-from-start", "--hls-use-mpegts",
        "--retries", "infinite", "--fragment-retries", "infinite",
        "--retry-sleep", "5", "--socket-timeout", "30",
        "--no-warnings", "--newline",
        "-f", quality,
        "--merge-output-format", fmt,
        "--progress", "--print", "after_move:filepath",
        "-o", str(output_path), url,
    ]

    rec["status"] = "recording"
    rec["started_at"] = time.time()
    rec["log"] = []

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        rec["pid"] = proc.pid

        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            rec["log"].append(line)
            if len(rec["log"]) > 300:
                rec["log"] = rec["log"][-150:]
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
        rec["ended_at"] = time.time()
        rec.pop("pid", None)

        if not rec.get("filepath"):
            for f in RECORDINGS_DIR.glob(f"{rec_id}.*"):
                rec["filepath"] = str(f)
                rec["filename"] = f.name
                break

        if fp := rec.get("filepath"):
            try:
                rec["bytes"] = Path(fp).stat().st_size
            except:
                pass

        auto_convert = ch.get("auto_convert_mp4", settings["auto_convert_mp4"])
        delete_orig  = ch.get("delete_original",  settings["delete_original"])
        fp = rec.get("filepath", "")

        if auto_convert and fp and not fp.endswith(".mp4") and Path(fp).exists():
            mp4_path = fp.rsplit(".", 1)[0] + ".mp4"
            try:
                conv = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-i", fp, "-c", "copy", mp4_path, "-y",
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
    asyncio.create_task(monitor_loop())


class AddChannelRequest(BaseModel):
    url: str
    quality: str = ""
    format: str = ""
    monitoring: bool = True
    auto_convert_mp4: bool = False
    delete_original: bool = False
    record_now: bool = False

class UpdateChannelRequest(BaseModel):
    monitoring: Optional[bool] = None
    quality: Optional[str] = None
    format: Optional[str] = None
    auto_convert_mp4: Optional[bool] = None
    delete_original: Optional[bool] = None

class UpdateSettingsRequest(BaseModel):
    monitor_interval: Optional[int] = None
    default_quality: Optional[str] = None
    default_format: Optional[str] = None
    auto_convert_mp4: Optional[bool] = None
    delete_original: Optional[bool] = None
    record_on_add: Optional[bool] = None


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

    asyncio.create_task(fetch_and_maybe_record())

    if req.record_now:
        asyncio.create_task(_start_recording_for_channel(ch_id))

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
    return sorted(result, key=lambda x: x["created_at"], reverse=True)


@app.patch("/api/channels/{ch_id}")
async def update_channel(ch_id: str, req: UpdateChannelRequest):
    if ch_id not in channels:
        raise HTTPException(404, "Not found")
    for field, val in req.model_dump(exclude_none=True).items():
        channels[ch_id][field] = val
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
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
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
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
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
    return settings


@app.get("/api/health")
async def health():
    return {"ok": True, "channels": len(channels), "recordings": len(recordings)}


app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
