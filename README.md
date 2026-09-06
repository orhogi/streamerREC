<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/yt--dlp-latest-red?logo=youtube&logoColor=white" alt="yt-dlp">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/dependencies-4-purple" alt="4 dependencies">
</p>

<h1 align="center">StreamRec</h1>

<p align="center">
  <strong>Self-hosted live stream recorder with a fast, dependency-free web UI.</strong><br>
  Monitor channels across 30+ platforms and capture streams automatically — with recordings library, log viewer, webhooks, and optional password protection.
</p>

---

## Why StreamRec

- **Zero frontend dependencies** — the entire UI is one HTML file. No npm, no build step, no CDN requests. Loads instantly, works offline.
- **Light on resources** — polling pauses when the browser tab is hidden; a Raspberry Pi mode halves CPU/RAM/disk overhead.
- **Set-and-forget** — channels are polled for live status and recorded automatically the moment they go online, with infinite retry/backoff on dropouts.
- **Recordings library** — browse, preview, favorite, archive, and download finished captures from the web UI.

## Features

**Recording**
- Auto-record when a channel goes live (per-channel toggle or global master switch)
- One-click manual recording from the dashboard
- Quality selection (Best / 1080p / 720p / 480p / Lowest) and format (MP4 / MKV / TS)
- Per-channel overrides for quality, format, max duration, and max streams kept
- Automatic faststart remux on completion for smooth playback
- Stalled-stream detection with optional auto-stop

**Reliability**
- Auto-retry with configurable attempts and delay when a stream drops
- Process-tree termination (no orphaned yt-dlp/ffmpeg after crashes)
- Startup sweep kills leftover recorder processes from a previous unclean stop
- Live log viewer for the active session, retained after it ends

**Platform support** — 30+ sites via yt-dlp, including YouTube, Twitch, TikTok, Kick, Bilibili, Douyin, Huya, Douyu, SOOP, Niconico, Twitcasting, Bigo, Dailymotion, Facebook, Instagram, Twitter/X, Vimeo, Rumble, and more.

**Security**
- Optional local account (PBKDF2-hashed password) — when set, the whole API requires a session
- Same-origin protection for cookie-authenticated state changes
- SSRF guards on channel URLs and webhooks
- Dangerous yt-dlp flags blocked in user-supplied extra args

**Notifications** — Discord embeds (rich: thumbnail, duration, size) or generic JSON webhooks for Slack/ntfy/custom.

## Getting Started

### Docker (recommended)

```bash
git clone https://github.com/orhogi/streamerREC.git
cd streamerREC
docker compose up -d
```

Open `http://localhost:8080`. Recordings land in `./recordings`.

### Manual

Prerequisites: Python 3.12+, [FFmpeg](https://ffmpeg.org/download.html), [yt-dlp](https://github.com/yt-dlp/yt-dlp#installation) on PATH.

```bash
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`. Recordings default to `~/StreamRec/recordings`.

## Configuration

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RECORDINGS_DIR` | `~/StreamRec/recordings` | Where recordings and state are stored |
| `STREAMREC_PI_MODE` | `0` | `1` enables low-power optimizations (fewer pollers, capped buffers, 1 ffmpeg thread) |
| `STATIC_DIR` | directory of `main.py` | Where `index.html` is served from |

### Web UI settings

Everything else is configured in the UI: check interval, default quality/format, auto-convert to MP4, retention days, max duration, auto-retry, proxy, cookies, webhooks, and low-power mode. All settings persist in `state.json` inside the recordings directory.

## Recordings layout

```
recordings/
├── Twitch/<channel>/<date>/<name>_<date>_<time>.mp4
├── Kick/<channel>/<date>/…
├── cookies/          uploaded cookies.txt files
├── _archived/        archived recordings
├── state.json        channels, settings, recording index
└── account.json      local account (only if you set a password)
```

## Cookies / age-restricted streams

1. Export cookies from your browser with an extension like *Get cookies.txt LOCALLY*
2. Upload the `.txt` in **Settings → Cookies**
3. Assign it per channel or globally

## VPN / proxy

An optional WireProxy sidecar exposes your WireGuard tunnel as a SOCKS5 proxy. It is **not** started by default:

```bash
# place your WireGuard config at ./wg0.conf first
docker compose --profile vpn up -d
```

Then set the proxy per channel or globally to `socks5://wireproxy:1080`.

## Authentication

The app runs in open guest mode until you create an account (first-run prompt). Once an account exists, the API requires login. Deleting the account from the account panel returns the app to guest mode.

## Updating yt-dlp

**Settings → System → Update** updates yt-dlp in place (pip, with a binary fallback). Keeping yt-dlp current matters — extractor breakage is the most common recording failure.

## API

FastAPI auto-docs at `/docs`. Quick reference:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET/POST` | `/api/channels` | List / add channels |
| `PATCH/DELETE` | `/api/channels/{id}` | Update / delete a channel |
| `POST` | `/api/channels/{id}/record` `…/stop` `…/kill` | Recording control |
| `POST` | `/api/channels/{id}/refresh` | Re-fetch metadata + live status |
| `GET` | `/api/recordings` | Recording index |
| `GET` | `/api/preview/{id}` `…/download/{id}` `…/{id}/log` | File access |
| `POST` | `/api/recordings/{id}/favorite` `…/archive` | Organize |
| `GET/PATCH` | `/api/settings` | Configuration |
| `GET/POST` | `/api/account` | Local auth |
| `GET` | `/api/health` `/api/disk` | Status |

## Raspberry Pi / low-power mode

Set `STREAMREC_PI_MODE=1` (or toggle in Settings): concurrent subprocess cap drops 6 → 3, polling intervals double, ffmpeg runs single-threaded, and download buffers shrink to 32 KB.

## Project structure

```
streamerREC/
├── main.py               # FastAPI backend — API, recording engine, monitor loop
├── index.html            # entire frontend (single file, no build)
├── Dockerfile            # main container
├── Dockerfile.wireproxy  # optional VPN sidecar
├── docker-compose.yml
└── requirements.txt      # 4 packages
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Recording fails immediately | Update yt-dlp (Settings → System). Extractors break often. |
| Logs empty during recording | Update yt-dlp — very old versions silence output with `--print`. |
| "URL rejected: private/internal host" | You added a LAN/local URL — blocked intentionally (SSRF guard). |
| Doubled recordings after a crash | Fixed by the startup sweep; make sure you're on the latest code. |
| Streams 403 on Twitch with cookies | Re-export fresh cookies; Twitch rotates tokens aggressively. |

## Contributing

PRs welcome. Keep the frontend a single file and dependency-free.

## License

[MIT](LICENSE)
