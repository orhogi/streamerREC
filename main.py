import asyncio
import json
import logging
import os
import platform as _platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("streamrec")

# ── Platform detection ────────────────────────────────────────────────────────
IS_WINDOWS = _platform.system() == "Windows"
PI_MODE = os.environ.get("STREAMREC_PI_MODE", "0") == "1"

# ── Paths ─────────────────────────────────────────────────────────────────────
# Docker sets RECORDINGS_DIR=/recordings  |  bare metal falls back to ~/StreamRec/recordings
_rec_env = os.environ.get("RECORDINGS_DIR", "")
if _rec_env:
    RECORDINGS_DIR = Path(_rec_env)
else:
    RECORDINGS_DIR = Path.home() / "StreamRec" / "recordings"

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE  = RECORDINGS_DIR / "state.json"
COOKIES_DIR = RECORDINGS_DIR / "cookies"
COOKIES_DIR.mkdir(exist_ok=True)

# Static files: Docker puts index.html in /app, bare metal uses same dir as main.py
_static_dir = os.environ.get("STATIC_DIR", str(Path(__file__).parent))

# ── Version ───────────────────────────────────────────────────────────────────
VERSION = "1.0.0"

# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_state()
    logger.info("StreamRec %s starting — %d channels loaded", VERSION, len(channels))
    task = asyncio.create_task(monitor_loop())
    yield
    task.cancel()
    logger.info("StreamRec shutting down")

app = FastAPI(title="StreamRec API", version=VERSION, lifespan=lifespan)

_proc_semaphore = asyncio.Semaphore(3 if PI_MODE else 6)

channels:   dict[str, dict] = {}
recordings: dict[str, dict] = {}

_disk_cache:    dict  = {}
_disk_cache_ts: float = 0

# ── Tuning helpers (Pi vs. normal) ───────────────────────────────────────────
# These read from `settings["pi_mode"]` at call time so the toggle takes
# effect immediately without a restart.

def _is_pi() -> bool:
    """True when Potato / Pi mode is active (env var OR settings toggle)."""
    return settings.get("pi_mode", PI_MODE)

def get_size_poll_interval() -> int:
    return 8 if _is_pi() else 3

def get_log_limits() -> tuple[int, int]:
    """Return (max_lines, trim_to) for the recording log buffer."""
    return (60, 30) if _is_pi() else (100, 50)

def get_frontend_poll_hint() -> int:
    return 10 if _is_pi() else 5

def get_disk_cache_ttl() -> int:
    return 60 if _is_pi() else 30

def get_ffmpeg_threads() -> str:
    return "1" if _is_pi() else "2"

# Streaming / preview constants — large chunks reduce HTTP round-trips and
# I/O syscalls, critical on Raspberry Pi / slow SD cards.
PREVIEW_RANGE_CHUNK  = 10 * 1024 * 1024   # 10 MB per HTTP range response
PREVIEW_READ_CHUNK   = 512 * 1024         # 512 KB per file read()

# Remux timeout — 5 min to handle large files on slow Pi SD cards
REMUX_TIMEOUT        = 300

# ── Debounced state persistence ──────────────────────────────────────────────
_save_state_pending = False
_save_state_task:   Optional[asyncio.Task] = None

def _schedule_save_state():
    """Debounce state saves — collapse rapid writes into one disk write."""
    global _save_state_pending, _save_state_task
    _save_state_pending = True
    if _save_state_task and not _save_state_task.done():
        return  # already scheduled
    _save_state_task = asyncio.get_running_loop().create_task(_debounced_save())

async def _debounced_save():
    """Wait for writes to settle, then flush once."""
    global _save_state_pending
    while True:
        _save_state_pending = False
        await asyncio.sleep(2)  # coalesce window
        if not _save_state_pending:
            break                # no new writes arrived — safe to flush
    _save_state_sync()

settings: dict = {
    "pi_mode":          PI_MODE,
    "monitor_interval": 120 if PI_MODE else 60,
    "default_quality":  "best",
    "default_format":   "mp4",
    "auto_convert_mp4": False,
    "delete_original":  False,
    "record_on_add":    False,
    "auto_retry":       True,
    "max_retries":      5,
    "retry_delay":      15,
    "proxy":            "",
    "cookies_file":     "",
    "extra_args":       "",
}

# ── Cross-platform process helpers ────────────────────────────────────────────

def _subprocess_kwargs() -> dict:
    """
    Extra kwargs for asyncio.create_subprocess_exec so we can kill the whole
    process tree later.
    - Windows: CREATE_NEW_PROCESS_GROUP lets us send CTRL_BREAK_EVENT to the group.
    - Unix:    setsid creates a new session; killpg kills the whole group.
    """
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"preexec_fn": os.setsid}


def _kill_proc(pid: int, force: bool = False) -> None:
    """Terminate or kill a process (and its children) cross-platform."""
    try:
        if IS_WINDOWS:
            # CTRL_BREAK_EVENT propagates to the whole process group on Windows
            sig = signal.CTRL_BREAK_EVENT
            os.kill(pid, sig)
            if force:
                # Give it a moment then hard-kill
                import ctypes
                ctypes.windll.kernel32.TerminateProcess(
                    ctypes.windll.kernel32.OpenProcess(1, False, pid), 1
                )
        else:
            sig = signal.SIGKILL if force else signal.SIGTERM
            try:
                os.killpg(os.getpgid(pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                os.kill(pid, sig)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        pass


# ── State persistence ─────────────────────────────────────────────────────────

def _save_state_sync():
    """Write state to disk immediately (internal — prefer _save_state)."""
    saved_channels = {}
    for cid, ch in channels.items():
        c = dict(ch)
        for k in ("recording_id", "is_live", "last_checked"):
            c.pop(k, None)
        saved_channels[cid] = c
    # Persist finished recordings (completed/error) so they survive restarts
    saved_recordings = {}
    for rid, rec in recordings.items():
        if rec.get("status") in ("completed", "error"):
            saved_recordings[rid] = rec
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({
                "channels": saved_channels,
                "settings": settings,
                "recordings": saved_recordings,
            }, indent=2),
            encoding="utf-8",
        )
        tmp.replace(STATE_FILE)
    except Exception as e:
        logger.warning("Failed to save state: %s", e)


def _save_state():
    """Save state — debounced in async context, immediate otherwise."""
    try:
        asyncio.get_running_loop()  # check if we're in an async context
        _schedule_save_state()
    except RuntimeError:
        # No running event loop (startup / sync context) — write immediately
        _save_state_sync()


def _load_state():
    global settings
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        for cid, ch in data.get("channels", {}).items():
            ch["recording_id"] = None
            ch["is_live"]      = False
            ch["last_checked"] = None
            # Re-detect platform for any channels saved as Unknown
            if ch.get("platform") in ("Unknown", "", None) and ch.get("url"):
                ch["platform"] = detect_platform(ch["url"])
            # Fill display_name from URL if blank
            if not ch.get("display_name") and ch.get("url"):
                ch["display_name"] = _username_from_url(ch["url"])
            if not ch.get("username") and ch.get("url"):
                ch["username"] = _username_from_url(ch["url"])
            channels[cid] = ch
        for k, v in data.get("settings", {}).items():
            if k in settings:
                settings[k] = v
        for rid, rec in data.get("recordings", {}).items():
            # Strip any in-progress state fields that no longer apply
            rec.pop("pid", None)
            rec.pop("stopping", None)
            rec.pop("speed", None)
            recordings[rid] = rec
    except Exception as e:
        logger.warning("Failed to load state: %s", e)


# ── Platform detection ────────────────────────────────────────────────────────

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
    (r"chaturbate\.com",         "Chaturbate"),
    (r"cam4\.com",               "Cam4"),
    (r"myfreecams\.com",         "MyFreeCams"),
    (r"camsoda\.com",            "CamSoda"),
    (r"bongacams\.com",          "BongaCams"),
    (r"cammodels\.com",          "CamModels"),
    (r"streamate\.com",          "Streamate"),
    (r"flirt4free\.com",         "Flirt4Free"),
]

def detect_platform(url: str) -> str:
    for pattern, name in PLATFORM_MAP:
        if re.search(pattern, url, re.I):
            return name
    return "Unknown"


# ── Metadata fetch ────────────────────────────────────────────────────────────

def _username_from_url(url: str) -> str:
    """Best-effort username extraction directly from the URL path."""
    try:
        path = urlparse(url).path.strip("/")
        # Take first non-empty path segment
        part = path.split("/")[0] if path else ""
        # Ignore generic segments
        if part and part not in ("live", "channel", "watch", "user", "c", "videos"):
            return part
    except Exception:
        pass
    return ""


async def fetch_metadata(url: str) -> dict:
    # Always extract a fallback username from the URL itself
    url_username = _username_from_url(url)

    try:
        async with _proc_semaphore:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--dump-single-json", "--no-download",
                "--playlist-items", "1", "--socket-timeout", "15", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)

        # Even if yt-dlp returns non-zero (offline room), stdout may still have data
        if stdout:
            try:
                data = json.loads(stdout)
            except Exception:
                data = {}
        else:
            data = {}

        thumbnails = data.get("thumbnails") or []
        thumbnail  = data.get("thumbnail") or (thumbnails[-1]["url"] if thumbnails else "")
        avatar = ""
        for t in reversed(thumbnails):
            tid = (t.get("id") or "").lower()
            if "avatar" in tid or "profile" in tid:
                avatar = t.get("url", "")
                break
        if not avatar:
            avatar = await _try_scrape_avatar(url)

        # Prefer yt-dlp data, fall back to URL-parsed username
        yt_name = data.get("uploader") or data.get("channel") or data.get("creator") or ""
        yt_user = data.get("uploader_id") or data.get("channel_id") or ""

        display_name = yt_name or url_username
        username     = yt_user or url_username

        return {
            "display_name": display_name,
            "username":     username,
            "avatar":       avatar,
            "thumbnail":    thumbnail,
            "is_live":      bool(data.get("is_live")),
        }
    except Exception:
        # Total failure — still return URL-derived name so card isn't blank
        if url_username:
            return {
                "display_name": url_username,
                "username":     url_username,
                "avatar":       "",
                "thumbnail":    "",
                "is_live":      False,
            }
        return {}


async def _try_scrape_avatar(url: str) -> str:
    try:
        async with _proc_semaphore:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-sL", "--max-time", "10", "-A",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        if not stdout:
            return ""
        html = stdout.decode("utf-8", errors="replace")
        for pat in (r'"avatarLarger"\s*:\s*"([^"]+)"',
                    r'"avatarMedium"\s*:\s*"([^"]+)"',
                    r'"avatarThumb"\s*:\s*"([^"]+)"'):
            m = re.search(pat, html)
            if m:
                return m.group(1).replace(r'\u002F', '/')
        m = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\'>]+)["\']',
            html, re.I,
        )
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


async def _check_chaturbate_live(url: str, proxy: str = "") -> Optional[bool]:
    """Scrape Chaturbate page directly — returns True/False/None (None = inconclusive)."""
    try:
        curl_cmd = [
            "curl", "-sL", "--max-time", "10", "-A",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        if proxy:
            curl_cmd += ["--proxy", proxy]
        curl_cmd.append(url)
        proc = await asyncio.create_subprocess_exec(
            *curl_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        if not stdout:
            return None
        html = stdout.decode("utf-8", errors="replace")
        # Chaturbate embeds room status in the page
        if '"room_status": "public"' in html or '"room_status":"public"' in html:
            return True
        if 'offline' in html.lower() and 'room_status' in html:
            return False
        return None
    except Exception:
        return None


async def check_is_live(url: str, proxy: str = "") -> bool:
    # For Chaturbate, try a fast HTTP scrape first before invoking yt-dlp
    if re.search(r"chaturbate\.com", url, re.I):
        result = await _check_chaturbate_live(url, proxy=proxy)
        if result is not None:
            return result

    try:
        async with _proc_semaphore:
            cmd = ["yt-dlp", "--simulate", "--no-warnings",
                   "--socket-timeout", "20", "--playlist-items", "1"]
            if proxy:
                cmd += ["--proxy", proxy]
            cmd.append(url)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
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


# ── Recording ─────────────────────────────────────────────────────────────────

async def _start_recording_for_channel(ch_id: str) -> Optional[str]:
    ch = channels.get(ch_id)
    if not ch:
        return None
    existing = ch.get("recording_id")
    if existing and existing in recordings and recordings[existing]["status"] in ("recording", "starting"):
        return None
    rec_id = str(uuid.uuid4())[:8]
    recordings[rec_id] = {
        "id": rec_id, "channel_id": ch_id,
        "url": ch["url"], "platform": ch["platform"],
        "quality": ch.get("quality") or settings["default_quality"],
        "format":  ch.get("format")  or settings["default_format"],
        "status": "starting", "created_at": time.time(),
        "started_at": None, "ended_at": None,
        "bytes": 0, "speed": None,
        "filepath": None, "filename": None,
        "log": [], "stopping": False, "auto": False,
    }
    channels[ch_id]["recording_id"] = rec_id
    asyncio.create_task(run_recording(rec_id))
    return rec_id


async def run_recording(rec_id: str):
    rec = recordings[rec_id]
    ch  = channels.get(rec["channel_id"], {})
    quality      = rec.get("quality") or settings["default_quality"]
    fmt          = rec.get("format")  or settings["default_format"]
    url          = rec["url"]
    platform_raw = rec.get("platform") or "Unknown"
    platform     = platform_raw.lower()

    username     = ch.get("display_name") or ch.get("username") or rec_id
    safe_plat    = re.sub(r'[^\w\-]', '_', platform_raw)
    safe_user    = re.sub(r'[^\w\-]', '_', username)
    now          = datetime.now()
    date_str     = now.strftime("%Y-%m-%d")
    time_str     = now.strftime("%H-%M-%S")
    rec_dir      = RECORDINGS_DIR / safe_plat / safe_user / date_str
    rec_dir.mkdir(parents=True, exist_ok=True)
    stem         = f"{safe_user}_{date_str}_{time_str}"
    output_path  = rec_dir / f"{stem}.%(ext)s"

    _no_live_from_start = (
        "tiktok", "kick", "stripchat", "bigo", "pandalive",
        "chaturbate", "cam4", "myfreecams", "camsoda", "bongacams",
        "cammodels", "streamate", "flirt4free",
    )
    _cam_platforms = _no_live_from_start  # same set for format logic

    # Cam/HLS sites use numeric format IDs — "best" keyword alone fails.
    # Build a fallback chain that works for both cam sites and regular streams.
    _height_re = re.match(r'^(\d+)p?$', quality)
    if quality in ("best", ""):
        if platform in _cam_platforms:
            effective_quality = "bestvideo+bestaudio/best"
        else:
            effective_quality = "bestvideo+bestaudio/bestvideo/best"
    elif quality == "bestvideo+bestaudio":
        effective_quality = "bestvideo+bestaudio/best"
    elif _height_re and platform in _cam_platforms:
        # e.g. "720p" or "720" on cam sites — use height filter with fallback
        h = _height_re.group(1)
        effective_quality = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/bestvideo+bestaudio/best"
    else:
        # User specified explicit quality (1080p, 720p, etc.) for non-cam platforms
        effective_quality = quality

    cmd = ["yt-dlp", "--no-part"]
    if platform not in _no_live_from_start:
        cmd += ["--live-from-start", "--hls-use-mpegts"]

    # Limit ffmpeg thread count — critical for Pi / low-power CPUs
    ffmpeg_threads = get_ffmpeg_threads()
    cmd += [
        "--retries", "infinite", "--fragment-retries", "infinite",
        "--retry-sleep", "5", "--socket-timeout", "30",
        "--no-warnings", "--newline",
        "--concurrent-fragments", "1",
        "--fixup", "force",
        "--downloader-args", f"ffmpeg:-threads {ffmpeg_threads} -fflags +genpts+discardcorrupt",
        "-f", effective_quality,
        "--merge-output-format", fmt,
        "--progress", "--print", "after_move:filepath",
    ]
    # On Pi / low-memory systems, cap the download buffer to reduce RAM usage
    if _is_pi():
        cmd += ["--buffer-size", "32K"]
    # Chaturbate (and similar HLS cam sites) have audio segments that start
    # exactly 1 second ahead of video — delay audio by 1s to compensate.
    if platform in _cam_platforms:
        cmd += ["--postprocessor-args", "ffmpeg:-c:v copy -c:a aac -af adelay=1000|1000"]

    # Proxy (channel > global)
    proxy = ch.get("proxy") or settings.get("proxy", "")
    if proxy:
        cmd += ["--proxy", proxy]

    # Cookies file (channel > global)
    cf_name = ch.get("cookies_file") or settings.get("cookies_file", "")
    if cf_name:
        cf = Path(cf_name) if Path(cf_name).is_absolute() else COOKIES_DIR / cf_name
        if cf.exists():
            cmd += ["--cookies", str(cf)]

    # Username / password for age-restricted sites
    ch_user = ch.get("ch_username", "")
    ch_pass = ch.get("ch_password", "")
    if ch_user:
        cmd += ["--username", ch_user]
    if ch_pass:
        cmd += ["--password", ch_pass]

    # Extra yt-dlp args (channel > global)
    extra = ch.get("extra_args") or settings.get("extra_args", "")
    if extra:
        try:
            # shlex.split is POSIX by default; on Windows use posix=False
            cmd += shlex.split(extra, posix=not IS_WINDOWS)
        except Exception:
            pass

    cmd += ["-o", str(output_path), url]

    rec["status"]     = "recording"
    rec["started_at"] = time.time()
    rec["log"]        = []
    size_task         = None
    logger.info("Recording started: %s for %s (%s)", rec_id, username, url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **_subprocess_kwargs(),
        )
        rec["pid"] = proc.pid

        async def _poll_size():
            last_bytes = 0
            last_time = time.time()
            while True:
                await asyncio.sleep(get_size_poll_interval())
                for f in rec_dir.glob(f"{stem}.*"):
                    try:
                        sz = f.stat().st_size
                        if sz > 0:
                            now = time.time()
                            delta_bytes = sz - last_bytes
                            delta_time = now - last_time
                            if delta_time > 0 and last_bytes > 0 and delta_bytes >= 0:
                                bps = delta_bytes / delta_time
                                if bps >= 1024**2:
                                    rec["speed"] = f"{bps/1024**2:.1f}MiB/s"
                                elif bps >= 1024:
                                    rec["speed"] = f"{bps/1024:.1f}KiB/s"
                                else:
                                    rec["speed"] = f"{bps:.0f}B/s"
                            last_bytes = sz
                            last_time = now
                            rec["bytes"] = sz
                    except Exception:
                        pass
                    break

        size_task = asyncio.create_task(_poll_size())

        rec_dir_str = str(RECORDINGS_DIR)
        async for raw_line in proc.stdout:
            # ffmpeg uses \r to overwrite progress; split on both \r and \n
            for line in raw_line.decode("utf-8", errors="replace").replace("\r", "\n").split("\n"):
                line = line.strip()
                if not line:
                    continue
                rec["log"].append(line)
                log_max, log_trim = get_log_limits()
                if len(rec["log"]) > log_max:
                    rec["log"] = rec["log"][-log_trim:]
                # ffmpeg progress line (HLS via ffmpeg downloader):
                # "frame= 49 fps=0.0 size=  256KiB time=00:00:01 bitrate=1279.8kbits/s speed= 3.2x"
                if "frame=" in line and "bitrate=" in line:
                    m_size = re.search(r"size=\s*(\d+\.?\d*)\s*(GiB|MiB|KiB|B)\b", line)
                    if m_size:
                        v = float(m_size.group(1))
                        u = {"GiB": 1024**3, "MiB": 1024**2, "KiB": 1024, "B": 1}[m_size.group(2)]
                        rec["bytes"] = int(v * u)
                    m_br = re.search(r"bitrate=\s*(\d+\.?\d*\s*\w+bits/s)", line)
                    if m_br:
                        rec["speed"] = m_br.group(1)
                # yt-dlp download progress line (HTTP downloads)
                elif "[download]" in line or "[hlsnative]" in line:
                    m = re.search(r"(\d+\.?\d*)\s*(GiB|MiB|KiB|B)\b", line)
                    if m:
                        v = float(m.group(1))
                        u = {"GiB": 1024**3, "MiB": 1024**2, "KiB": 1024, "B": 1}[m.group(2)]
                        rec["bytes"] = int(v * u)
                    m2 = re.search(r"(\d+\.?\d*\s*(?:GiB|MiB|KiB|B)/s)", line)
                    if m2:
                        rec["speed"] = m2.group(1)
                # Detect final filepath printed by --print after_move:filepath
                if (not line.startswith("[") and not line.startswith("ERROR")
                        and len(line) > 4 and rec_dir_str in line):
                    p = Path(line)
                    if p.suffix:
                        rec["filepath"] = line
                        rec["filename"] = p.name

        await proc.wait()
        rc = proc.returncode
        # Resolve filepath now (before status check) in case --print didn't fire
        if not rec.get("filepath"):
            for f in rec_dir.glob(f"{stem}.*"):
                rec["filepath"] = str(f)
                rec["filename"] = f.name
                break
        # Treat as completed if manually stopped OR if a file with real content was captured
        # (yt-dlp exits non-zero when broadcaster goes offline, even after a full capture)
        file_captured = bool(rec.get("filepath") and Path(rec["filepath"]).exists()
                             and Path(rec["filepath"]).stat().st_size > 0)
        rec["status"] = "completed" if (rc == 0 or rec.get("stopping") or file_captured) else "error"
        if rc != 0 and not rec.get("stopping") and not file_captured:
            rec["error"] = f"Exit code {rc}"
            logger.warning("Recording %s failed with exit code %d", rec_id, rc)
        else:
            logger.info("Recording %s completed", rec_id)

    except Exception as e:
        rec["status"] = "error"
        rec["error"]  = str(e)
        logger.error("Recording %s exception: %s", rec_id, e)

    finally:
        if size_task:
            size_task.cancel()
        rec["ended_at"] = time.time()
        rec.pop("pid", None)

        # Fall back to file glob if yt-dlp didn't print the path
        if not rec.get("filepath"):
            for f in rec_dir.glob(f"{stem}.*"):
                rec["filepath"] = str(f)
                rec["filename"] = f.name
                break

        if fp := rec.get("filepath"):
            try:
                rec["bytes"] = Path(fp).stat().st_size
            except Exception:
                pass

        # Remux to fix containers and move moov atom to file start for
        # smooth playback (faststart).  Run on ALL completed recordings —
        # not just manual stops — so files play without lag on any device.
        fp = rec.get("filepath", "")
        if fp and Path(fp).exists():
            suffix    = Path(fp).suffix
            fixed_path = str(Path(fp).with_name(Path(fp).stem + "_fixed" + suffix))
            try:
                fix_proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-i", fp, "-c", "copy", "-movflags", "+faststart",
                    "-threads", ffmpeg_threads, fixed_path, "-y",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(fix_proc.wait(), timeout=REMUX_TIMEOUT)
                if fix_proc.returncode == 0 and Path(fixed_path).exists():
                    Path(fp).unlink(missing_ok=True)
                    Path(fixed_path).rename(fp)
                    try:
                        rec["bytes"] = Path(fp).stat().st_size
                    except Exception:
                        pass
                else:
                    Path(fixed_path).unlink(missing_ok=True)
            except Exception:
                try:
                    Path(fixed_path).unlink(missing_ok=True)
                except Exception:
                    pass

        # Optional MP4 conversion
        auto_convert = ch.get("auto_convert_mp4", settings["auto_convert_mp4"])
        delete_orig  = ch.get("delete_original",  settings["delete_original"])
        fp = rec.get("filepath", "")
        if auto_convert and fp and not fp.endswith(".mp4") and Path(fp).exists():
            mp4_path = str(Path(fp).with_suffix(".mp4"))
            try:
                conv = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-i", fp, "-c", "copy",
                    "-movflags", "+faststart",
                    "-threads", ffmpeg_threads,
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
                    except Exception:
                        pass
            except Exception:
                pass

        if ch_id := rec.get("channel_id"):
            if ch_id in channels:
                channels[ch_id]["recording_id"] = None
                channels[ch_id]["is_live"]      = False

        _save_state()

        # Auto-retry on unexpected disconnect
        retry_ch_id = rec.get("channel_id")
        # Don't retry if stream ran for more than 30s — that's a natural end, not a crash
        run_duration = (rec.get("ended_at") or time.time()) - (rec.get("started_at") or time.time())
        natural_end  = run_duration > 30 and file_captured
        should_retry = (
            not rec.get("stopping")
            and not natural_end
            and rec.get("status") == "error"
            and settings.get("auto_retry", True)
            and retry_ch_id
            and retry_ch_id in channels
            and channels[retry_ch_id].get("monitoring", True)
        )
        if should_retry:
            attempt    = rec.get("_retry_attempt", 0) + 1
            max_retries = settings.get("max_retries", 5)
            delay      = settings.get("retry_delay", 15)
            if attempt <= max_retries:
                rec["log"].append(
                    f"[StreamRec] Stream disconnected. Retrying in {delay}s "
                    f"(attempt {attempt}/{max_retries})…"
                )
                await asyncio.sleep(delay)
                if retry_ch_id in channels and not channels[retry_ch_id].get("recording_id"):
                    new_id = await _start_recording_for_channel(retry_ch_id)
                    if new_id:
                        recordings[new_id]["_retry_attempt"] = attempt
                        recordings[new_id]["auto"] = True


# ── Monitor loop ──────────────────────────────────────────────────────────────

async def monitor_loop():
    while True:
        interval = settings.get("monitor_interval", 60)
        await asyncio.sleep(interval)
        monitored_count = sum(1 for c in channels.values() if c.get("monitoring", True))
        logger.debug("Monitor tick — checking %d channels", monitored_count)
        for ch_id, ch in list(channels.items()):
            if not ch.get("monitoring", True):
                continue
            existing = ch.get("recording_id")
            if existing and existing in recordings:
                r = recordings[existing]
                if r["status"] in ("recording", "starting"):
                    channels[ch_id]["is_live"]      = True
                    channels[ch_id]["last_checked"] = time.time()
                    continue
            proxy   = ch.get("proxy") or settings.get("proxy", "")
            is_live = await check_is_live(ch["url"], proxy=proxy)
            channels[ch_id]["is_live"]      = is_live
            channels[ch_id]["last_checked"] = time.time()
            if is_live:
                logger.info("Channel %s is live — starting auto-record", ch_id)
                rec_id = await _start_recording_for_channel(ch_id)
                if rec_id:
                    recordings[rec_id]["auto"] = True


# ── Request models ────────────────────────────────────────────────────────────

class AddChannelRequest(BaseModel):
    url:              str
    quality:          str  = ""
    format:           str  = ""
    monitoring:       bool = True
    auto_convert_mp4: bool = False
    delete_original:  bool = False
    record_now:       bool = False
    proxy:            str  = ""
    cookies_file:     str  = ""
    username:         str  = ""
    password:         str  = ""
    extra_args:       str  = ""

class UpdateChannelRequest(BaseModel):
    monitoring:       Optional[bool] = None
    quality:          Optional[str]  = None
    format:           Optional[str]  = None
    auto_convert_mp4: Optional[bool] = None
    delete_original:  Optional[bool] = None
    proxy:            Optional[str]  = None
    cookies_file:     Optional[str]  = None
    username:         Optional[str]  = None
    password:         Optional[str]  = None
    extra_args:       Optional[str]  = None

class UpdateSettingsRequest(BaseModel):
    pi_mode:          Optional[bool] = None
    monitor_interval: Optional[int]  = None
    default_quality:  Optional[str]  = None
    default_format:   Optional[str]  = None
    auto_convert_mp4: Optional[bool] = None
    delete_original:  Optional[bool] = None
    record_on_add:    Optional[bool] = None
    auto_retry:       Optional[bool] = None
    max_retries:      Optional[int]  = None
    retry_delay:      Optional[int]  = None
    proxy:            Optional[str]  = None
    cookies_file:     Optional[str]  = None
    extra_args:       Optional[str]  = None

class ReorderRequest(BaseModel):
    order: list[str]

class BulkActionRequest(BaseModel):
    ids:    list[str]
    action: str  # "record" | "stop" | "delete"

class ImportRequest(BaseModel):
    channels: dict = {}
    settings: dict = {}
    merge:    bool = True


# ── Helper: stop a recording by rec dict ─────────────────────────────────────

def _stop_rec(rec: dict, force: bool = False):
    rec["stopping"] = True
    if pid := rec.get("pid"):
        _kill_proc(pid, force=force)


# ── Channel endpoints ─────────────────────────────────────────────────────────

@app.post("/api/channels")
async def add_channel(req: AddChannelRequest):
    # Validate URL — must be http/https to prevent SSRF
    parsed = urlparse(req.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "Invalid URL — must start with http:// or https://")
    ch_id    = str(uuid.uuid4())[:8]
    platform = detect_platform(req.url)
    ch = {
        "id": ch_id, "url": req.url, "platform": platform,
        "quality": req.quality, "format": req.format,
        "monitoring":       req.monitoring,
        "auto_convert_mp4": req.auto_convert_mp4,
        "delete_original":  req.delete_original,
        "proxy":            req.proxy,
        "cookies_file":     req.cookies_file,
        "ch_username":      req.username,
        "ch_password":      req.password,
        "extra_args":       req.extra_args,
        "created_at":  time.time(),
        "display_name": "", "username": "", "avatar": "", "thumbnail": "",
        "is_live": False, "last_checked": None, "recording_id": None,
    }
    channels[ch_id] = ch

    async def _fetch_and_record():
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

    asyncio.create_task(_fetch_and_record())
    if req.record_now:
        asyncio.create_task(_start_recording_for_channel(ch_id))
    _save_state()
    logger.info("Channel added: %s (%s) [%s]", ch_id, platform, req.url)
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
            c["rec_speed"]  = None; c["rec_started"] = None; c["rec_id"] = None
        result.append(c)
    return sorted(result, key=lambda x: (x.get("sort_order", 9999), -x["created_at"]))


@app.patch("/api/channels/{ch_id}")
async def update_channel(ch_id: str, req: UpdateChannelRequest):
    if ch_id not in channels:
        raise HTTPException(404, "Not found")
    for field, val in req.model_dump(exclude_none=True).items():
        # username/password map to ch_username/ch_password to avoid clash with metadata field
        if field == "username":
            channels[ch_id]["ch_username"] = val
        elif field == "password":
            channels[ch_id]["ch_password"] = val
        else:
            channels[ch_id][field] = val
    _save_state()
    return channels[ch_id]


@app.post("/api/channels/{ch_id}/record")
async def record_channel(ch_id: str):
    ch = channels.get(ch_id)
    if not ch:
        raise HTTPException(404, "Channel not found")
    existing = ch.get("recording_id")
    if existing and existing in recordings and recordings[existing]["status"] in ("recording", "starting"):
        raise HTTPException(400, "Already recording")
    rec_id = await _start_recording_for_channel(ch_id)
    if not rec_id:
        raise HTTPException(400, "Already recording")
    return {"rec_id": rec_id}


@app.post("/api/channels/{ch_id}/stop")
async def stop_channel(ch_id: str):
    ch = channels.get(ch_id)
    if not ch:
        raise HTTPException(404, "Not found")
    rec_id = ch.get("recording_id")
    if not rec_id or rec_id not in recordings:
        raise HTTPException(400, "Not recording")
    _stop_rec(recordings[rec_id], force=False)
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
    _stop_rec(rec, force=True)
    rec["status"]   = "completed"
    rec["ended_at"] = time.time()
    channels[ch_id]["recording_id"] = None
    return {"ok": True}


@app.post("/api/channels/{ch_id}/refresh")
async def refresh_channel(ch_id: str):
    ch = channels.get(ch_id)
    if not ch:
        raise HTTPException(404, "Not found")
    # Re-detect platform in case it was saved as Unknown
    if ch.get("platform") == "Unknown" or not ch.get("platform"):
        channels[ch_id]["platform"] = detect_platform(ch["url"])
    meta = await fetch_metadata(ch["url"])
    if meta:
        channels[ch_id].update({
            "display_name": meta.get("display_name") or ch.get("display_name") or "",
            "username":     meta.get("username")     or ch.get("username") or "",
            "avatar":       meta.get("avatar")       or ch.get("avatar", ""),
            "thumbnail":    meta.get("thumbnail")    or ch.get("thumbnail", ""),
            "is_live":      meta.get("is_live", False),
            "last_checked": time.time(),
        })
    _save_state()
    return channels[ch_id]


@app.delete("/api/channels/{ch_id}")
async def delete_channel(ch_id: str):
    ch = channels.pop(ch_id, None)
    if not ch:
        raise HTTPException(404, "Not found")
    rec_id = ch.get("recording_id")
    if rec_id and rec_id in recordings:
        _stop_rec(recordings[rec_id], force=False)
    _save_state()
    logger.info("Channel deleted: %s", ch_id)
    return {"ok": True}


@app.post("/api/channels/reorder")
async def reorder_channels(req: ReorderRequest):
    for i, ch_id in enumerate(req.order):
        if ch_id in channels:
            channels[ch_id]["sort_order"] = i
    _save_state()
    return {"ok": True}


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
                        _stop_rec(rec, force=False)
                results.append({"id": ch_id, "ok": True})
            elif req.action == "delete":
                ch = channels.pop(ch_id, None)
                if ch:
                    rec_id = ch.get("recording_id")
                    if rec_id and rec_id in recordings:
                        _stop_rec(recordings[rec_id], force=False)
                results.append({"id": ch_id, "ok": True})
        except Exception:
            results.append({"id": ch_id, "ok": False})
    _save_state()
    return {"results": results}


# ── Recording endpoints ───────────────────────────────────────────────────────

@app.get("/api/recordings")
async def list_recordings():
    result = []
    for rec in recordings.values():
        r = dict(rec)
        r.pop("log", None)
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
        except Exception:
            pass
    return {"ok": True}


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
    suffix    = file_path.suffix.lower()
    content_type = (
        "video/mp4"        if suffix == ".mp4" else
        "video/x-matroska" if suffix == ".mkv" else
        "video/mp2t"
    )

    range_header = request.headers.get("range")
    if range_header:
        start = int(range_header.replace("bytes=", "").split("-")[0])
        end   = min(start + PREVIEW_RANGE_CHUNK, file_size - 1)
        length = end - start + 1

        def iterfile():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(PREVIEW_READ_CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iterfile(), status_code=206, media_type=content_type,
            headers={
                "Content-Range":  f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges":  "bytes",
                "Content-Length": str(length),
                "Cache-Control":  "private, max-age=3600",
                "Connection":     "keep-alive",
            },
        )
    return FileResponse(fp, media_type=content_type, headers={
        "Accept-Ranges": "bytes",
        "Cache-Control":  "private, max-age=3600",
    })


# ── Settings endpoints ────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    return settings


@app.patch("/api/settings")
async def update_settings(req: UpdateSettingsRequest):
    for field, val in req.model_dump(exclude_none=True).items():
        settings[field] = val
    _save_state()
    return settings


# ── Cookies endpoints ─────────────────────────────────────────────────────────

@app.post("/api/cookies/upload")
async def upload_cookies(file: UploadFile = File(...)):
    safe_name = re.sub(r'[^\w\-\.]', '_', file.filename or "cookies.txt")
    dest      = COOKIES_DIR / safe_name
    content   = await file.read()
    dest.write_bytes(content)
    return {"ok": True, "filename": safe_name, "size": len(content)}


@app.get("/api/cookies")
async def list_cookies():
    files = []
    for f in sorted(COOKIES_DIR.iterdir()):
        if f.is_file():
            files.append({"filename": f.name, "size": f.stat().st_size})
    return files


@app.delete("/api/cookies/{filename}")
async def delete_cookies(filename: str):
    safe = re.sub(r'[^\w\-\.]', '_', filename)
    dest = COOKIES_DIR / safe
    if not dest.exists():
        raise HTTPException(404, "Not found")
    dest.unlink()
    return {"ok": True}


# ── Platforms endpoint ────────────────────────────────────────────────────────

SUPPORTED_PLATFORMS = [
    {"name": "YouTube",     "domain": "youtube.com / youtu.be",  "color": "#FF0000", "emoji": "▶",  "notes": "Livestreams, premieres, scheduled streams"},
    {"name": "Twitch",      "domain": "twitch.tv",               "color": "#6441a5", "emoji": "🎮", "notes": "Live channels, VOD replay"},
    {"name": "TikTok",      "domain": "tiktok.com",              "color": "#010101", "emoji": "♪",  "notes": "Live streams"},
    {"name": "Kick",        "domain": "kick.com",                "color": "#53fc18", "emoji": "⚡", "notes": "Live channels"},
    {"name": "Bilibili",    "domain": "bilibili.com",            "color": "#00a1d6", "emoji": "B",  "notes": "Live streams"},
    {"name": "Douyin",      "domain": "douyin.com",              "color": "#010101", "emoji": "♪",  "notes": "Chinese TikTok live"},
    {"name": "Huya",        "domain": "huya.com",                "color": "#ff8c00", "emoji": "🎮", "notes": "Chinese game streaming"},
    {"name": "Douyu",       "domain": "douyu.com",               "color": "#ff6600", "emoji": "🐟", "notes": "Chinese game streaming"},
    {"name": "Afreeca TV",  "domain": "afreecatv.com",           "color": "#006aff", "emoji": "🔵", "notes": "Korean streaming platform"},
    {"name": "Sooplive",    "domain": "sooplive.co.kr",          "color": "#1a6cff", "emoji": "🔵", "notes": "Korean streaming (formerly AfreecaTV)"},
    {"name": "Naver",       "domain": "naver.com",               "color": "#03c75a", "emoji": "N",  "notes": "Korean portal live streams"},
    {"name": "Niconico",    "domain": "nicovideo.jp",            "color": "#888888", "emoji": "⚪", "notes": "Japanese video / live"},
    {"name": "Facebook",    "domain": "facebook.com / fb.watch", "color": "#1877f2", "emoji": "f",  "notes": "Live videos — use cookies for age-restricted"},
    {"name": "Instagram",   "domain": "instagram.com",           "color": "#e1306c", "emoji": "📷", "notes": "Live, Reels — requires cookies for private"},
    {"name": "Twitter/X",   "domain": "twitter.com / x.com",    "color": "#1da1f2", "emoji": "🐦", "notes": "Spaces, live video"},
    {"name": "Vimeo",       "domain": "vimeo.com",               "color": "#1ab7ea", "emoji": "V",  "notes": "Live events"},
    {"name": "Rumble",      "domain": "rumble.com",              "color": "#85c742", "emoji": "🟢", "notes": "Live streams"},
    {"name": "Stripchat",   "domain": "stripchat.com",           "color": "#ff4500", "emoji": "🔞", "notes": "Adult live — use cookies for age verification"},
    {"name": "Twitcasting", "domain": "twitcasting.tv",          "color": "#2f6db5", "emoji": "📡", "notes": "Japanese mobile streaming"},
    {"name": "Bigo Live",   "domain": "bigo.tv",                 "color": "#00c73c", "emoji": "🎤", "notes": "Global live streaming"},
    {"name": "Pandalive",   "domain": "pandalive.co.kr",         "color": "#ff6699", "emoji": "🐼", "notes": "Korean streaming"},
    {"name": "Weibo",       "domain": "weibo.com",               "color": "#e6162d", "emoji": "微",  "notes": "Chinese social media live"},
    {"name": "Dailymotion", "domain": "dailymotion.com",         "color": "#0066dc", "emoji": "D",  "notes": "Live & VOD"},
    {"name": "Chaturbate", "domain": "chaturbate.com",           "color": "#f47321", "emoji": "🔞", "notes": "Adult live — cookies for age verification"},
    {"name": "Cam4",       "domain": "cam4.com",                 "color": "#e8403a", "emoji": "🔞", "notes": "Adult live streaming"},
    {"name": "MyFreeCams", "domain": "myfreecams.com",           "color": "#009b77", "emoji": "🔞", "notes": "Adult live streaming"},
    {"name": "CamSoda",    "domain": "camsoda.com",              "color": "#ff6b35", "emoji": "🔞", "notes": "Adult live streaming"},
    {"name": "BongaCams",  "domain": "bongacams.com",            "color": "#f5a623", "emoji": "🔞", "notes": "Adult live streaming"},
    {"name": "CamModels",  "domain": "cammodels.com",            "color": "#7b2d8b", "emoji": "🔞", "notes": "Adult live streaming"},
    {"name": "Streamate",  "domain": "streamate.com",            "color": "#c0392b", "emoji": "🔞", "notes": "Adult live streaming"},
    {"name": "Flirt4Free", "domain": "flirt4free.com",           "color": "#e91e8c", "emoji": "🔞", "notes": "Adult live streaming"},
]

@app.get("/api/platforms")
async def list_platforms():
    return SUPPORTED_PLATFORMS


# ── Misc endpoints ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"ok": True, "channels": len(channels), "recordings": len(recordings)}


@app.get("/api/version")
async def version():
    return {
        "version": VERSION,
        "pi_mode": _is_pi(),
        "poll_interval": get_frontend_poll_hint(),
    }


@app.get("/api/disk")
async def disk_usage():
    global _disk_cache, _disk_cache_ts
    now = time.time()
    if _disk_cache and now - _disk_cache_ts < get_disk_cache_ttl():
        return _disk_cache
    try:
        usage     = shutil.disk_usage(str(RECORDINGS_DIR))
        rec_bytes = sum(
            f.stat().st_size for f in RECORDINGS_DIR.rglob("*")
            if f.is_file() and f.name != "state.json"
        )
        _disk_cache = {
            "total": usage.total, "used": usage.used,
            "free":  usage.free,  "recordings_bytes": rec_bytes,
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


@app.post("/api/import")
async def import_config(req: ImportRequest):
    imported = 0
    for cid, ch in req.channels.items():
        if req.merge and cid in channels:
            continue
        ch["recording_id"] = None
        ch["is_live"]      = False
        ch["last_checked"] = None
        ch.setdefault("id",         cid)
        ch.setdefault("created_at", time.time())
        channels[cid] = ch
        imported += 1
    for k, v in req.settings.items():
        if k in settings:
            settings[k] = v
    _save_state()
    return {"ok": True, "imported_channels": imported}


# ── Static files (must be last) ───────────────────────────────────────────────
app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
