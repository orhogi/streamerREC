<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/yt--dlp-latest-red?logo=youtube&logoColor=white" alt="yt-dlp">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/platforms-30+-purple" alt="30+ Platforms">
</p>

<h1 align="center">🔴 StreamRec</h1>

<p align="center">
  <strong>Self-hosted live stream recorder with a sleek, modern web UI.</strong><br>
  Automatically monitor and record live streams from 30+ platforms — all from a clean, unified dashboard.
</p>

---

## 📑 Table of Contents

- [Features](#-features)
- [Getting Started](#-getting-started)
- [Updating](#-updating)
- [VPN / Proxy Setup](#-vpn--proxy-setup)
- [Cookies / Age-Restricted Streams](#-cookies--age-restricted-streams)
- [Configuration](#-configuration)
- [Architecture](#️-architecture)
- [Project Structure](#-project-structure)
- [API Reference](#-api-reference)
- [Raspberry Pi / Low-Power Devices](#-raspberry-pi--low-power-devices)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features

### 🌍 Multi-Platform Support
Record live streams from **30+ platforms** including:

| Platform | Platform | Platform | Platform |
|----------|----------|----------|----------|
| YouTube | Twitch | TikTok | Kick |
| Bilibili | Instagram | Facebook | Twitter/X |
| Rumble | Vimeo | Dailymotion | Niconico |
| Douyin | Huya | Douyu | Afreeca |
| Sooplive | Naver | Weibo | Bigo |
| Twitcasting | Pandalive | Stripchat | Chaturbate |
| Cam4 | MyFreeCams | BongaCams | CamSoda |
| CamModels | Streamate | Flirt4Free | _…and more via yt-dlp_ |

### 🎯 Core Capabilities
- **Automatic Live Detection** — Periodically checks channel statuses and starts recording automatically
- **Multi-Channel Monitoring** — Monitor dozens of streamers simultaneously with individual active/paused toggles
- **One-Click Instant Recording** — Manually trigger or stop recordings at any time directly from the channel cards
- **Real-Time Stream Stats** — Live recording counter, capture bitrate/speed, and file size on disk updated in real time
- **Quality & Format Selection** — Choose Best, 1080p, 720p, 480p, or Lowest quality per channel, in MP4, MKV, or TS
- **Per-Channel Notes & Settings** — Customize proxies, credentials, quality overrides, and notes per streamer
- **Stream Title & Avatar Tracking** — Live badges, avatars, and broadcast titles refreshed automatically

### 📡 Smart Recording & Reliability
- **Twitch & HLS Stream Reliability** — Native handling for Twitch and live HLS streams without failed rewind conflicts
- **Auto-Retry with Backoff** — Automatically reconnects if a stream drops, with configurable retry count and delay
- **Post-Processing & Faststart Remux** — Optional lossless MP4 remuxing and container healing for interrupted streams
- **Safe Process Termination** — Comprehensive process tree termination (`taskkill` on Windows / process group on Unix) prevents orphaned background processes or file locking
- **Stalled Stream Detection** — Auto-stops recordings if incoming data stalls for more than 2 minutes
- **Webhooks & Discord Embeds** — Rich embed notifications for Discord and JSON alerts for Slack/custom webhooks, with an in-UI **Test Webhook** button

### 🖥️ Modernized Web Dashboard
- **Focused Two-View Layout** — Clean, distraction-free **Channels** and **Settings** navigation
- **Dark & Light Themes** — Toggle instantly between modern dark glow and clean light mode
- **Categorized Settings Center** — Six dedicated settings panes:
  1. 📁 **General & Storage** — Directories, retention policies, and MP4 remuxing
  2. 🎬 **Recording & Quality** — Default qualities, max duration, and concurrent slot caps
  3. 🌐 **Network & Engine** — Proxy, retry delays, yt-dlp version info and 1-click update
  4. 🔔 **Notifications** — Webhook alerts with instant test delivery
  5. 🍪 **Cookies & Auth** — Upload and manage Netscape cookies for age-restricted channels
  6. ⚙️ **System & Maintenance** — Configuration export, import, and factory reset
- **Live Output Drawer** — Inspect real-time `yt-dlp` logs with one click
- **Responsive & Lightweight** — Pure vanilla CSS/JS with zero build steps or heavy node dependencies

---

## 🚀 Getting Started

### Docker Compose (Recommended)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/orhogi/streamerREC.git
   cd streamerREC
   ```

2. **Start the application:**
   ```bash
   docker compose up -d
   ```

3. **Open your browser:**
   ```text
   http://localhost:8080
   ```

Your recordings will be saved in the `./recordings` directory.

### Docker Run

```bash
docker build -t streamrec .
docker run -d \
  --name streamrec \
  -p 8080:8080 \
  -v ./recordings:/recordings \
  --restart unless-stopped \
  streamrec
```

### Manual Installation (Bare Metal / Dev)

**Prerequisites:**
- Python 3.12+
- [FFmpeg](https://ffmpeg.org/download.html)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp#installation)

```bash
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 🔄 Updating

### Docker

```bash
cd streamerREC
git pull
docker compose down
docker compose build --no-cache
docker compose up -d
```

Your channels, settings, and completed recordings are stored in `./recordings/state.json` and persist across updates.

### Manual

```bash
cd streamerREC
git pull
pip install -r requirements.txt --upgrade
```

---

## 🔒 VPN / Proxy Setup

StreamRec includes a built-in WireGuard proxy (wireproxy) sidecar container exposing a SOCKS5 proxy at `socks5://wireproxy:1080` that you can assign to individual channels or globally.

Useful for:
- Recording geo-blocked streams
- Routing specific site traffic through a VPN
- Bypassing IP rate limits on specific platforms

### 1. Add your WireGuard config

Place your WireGuard config file at `streamerREC/wg0.conf`:

```ini
[Interface]
PrivateKey = <your private key>
Address = 10.x.x.x/32
DNS = 1.1.1.1

[Peer]
PublicKey = <server public key>
Endpoint = <server>:<port>
AllowedIPs = 0.0.0.0/0
```

### 2. Rebuild with the VPN config

```bash
docker compose down && docker compose build && docker compose up -d
```

### 3. Assign the proxy

- **Per Channel:** Open channel settings → set **Proxy** to `socks5://wireproxy:1080`
- **Globally:** Go to **Settings → Network & Engine** → set **Global Proxy**

---

## 🍪 Cookies / Age-Restricted Streams

For platforms requiring authentication or age verification:

1. Export your browser cookies using an extension (e.g., **Get cookies.txt LOCALLY**)
2. Go to **Settings → Cookies & Auth** in the web UI and upload the `.txt` file
3. Assign the cookies file to individual channels or globally

---

## 🧰 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAMREC_PI_MODE` | `0` | Set to `1` to enable Raspberry Pi / low-power optimizations |
| `RECORDINGS_DIR` | `~/StreamRec/recordings` | Override base recordings directory |

### Settings (Web UI)

| Setting | Default | Description |
|---------|---------|-------------|
| Low-power / Pi mode | Off | Reduces CPU/RAM/IO for single-board computers |
| Check Interval | 60s | How often to poll channel live status |
| Default Quality | `best` | Default resolution/quality profile |
| Default Format | `mp4` | Default output container format |
| Auto-convert to MP4 | Off | Remux finished recordings to MP4 |
| Delete Original | Off | Remove source container after MP4 conversion |
| Auto-Retry | On | Reconnect automatically on stream dropouts |
| Max Retries | 5 | Max reconnection attempts per session |
| Retry Delay | 15s | Seconds between reconnection attempts |
| Global Proxy | — | Proxy URL applied across all channels |
| Webhook URL | — | Discord or Slack/HTTP endpoint for live alerts |
| Auto-stop stalled | Off | Force-stop recordings when no new data arrives |

---

## 🏗️ Architecture

```text
─────────────────────────────────────────────
              Browser
          (index.html – SPA)
─────────────────┬───────────────────────────
                 │ REST API
─────────────────▼───────────────────────────
             FastAPI Server
              (main.py)

  ┌────────────┐ ┌────────────┐ ┌─────────┐
  │  Channel   │ │ Recording  │ │ Monitor │
  │  Manager   │ │  Engine    │ │  Loop   │
  └────────────┘ └─────┬──────┘ └─────────┘
                       │
                 ┌─────▼──────┐
                 │  yt-dlp +  │
                 │   FFmpeg   │
                 └────────────┘
─────────────────────────────────────────────
                 │
          ┌──────▼──────┐   ┌─────────────┐
          │ /recordings │   │  wireproxy  │
          │  (volume)   │   │ (WireGuard) │
          └─────────────┘   └─────────────┘
```

- **Frontend:** Responsive SPA with dark/light themes, zero npm build step
- **Backend:** FastAPI with non-blocking async subprocess execution
- **Engine:** `yt-dlp` and `FFmpeg`
- **State:** Persistent JSON volume storage

---

## 📁 Project Structure

```text
streamerREC/
├── main.py              # FastAPI backend, routes, process engine, monitor loop
├── index.html           # Modern frontend SPA (CSS/JS embedded)
├── Dockerfile           # StreamRec Docker container definition
├── Dockerfile.wireproxy # Wireproxy sidecar container
├── docker-compose.yml   # Multi-container Compose service config
├── requirements.txt     # Python dependencies
├── screenshots/         # Documentation assets
├── LICENSE              # MIT License
└── README.md
```

---

## 📖 API Reference

<details>
<summary><strong>Channels</strong></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/channels` | Add a new channel |
| `GET` | `/api/channels` | List all monitored channels |
| `PATCH` | `/api/channels/{id}` | Update channel settings / toggle monitoring |
| `DELETE` | `/api/channels/{id}` | Delete a channel |
| `POST` | `/api/channels/{id}/record` | Start recording immediately |
| `POST` | `/api/channels/{id}/stop` | Stop recording gracefully |
| `POST` | `/api/channels/{id}/kill` | Force-kill recording process |
| `POST` | `/api/channels/{id}/refresh` | Check channel status & metadata now |
| `POST` | `/api/channels/reorder` | Update channel sort orders |
| `POST` | `/api/channels/bulk` | Bulk record / stop / delete |
| `POST` | `/api/channels/bulk-edit` | Bulk update quality / format |

</details>

<details>
<summary><strong>Settings & Engine</strong></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/settings` | Get current settings |
| `PATCH` | `/api/settings` | Update configuration |
| `POST` | `/api/settings/test-webhook` | Send a test notification to configured webhook |
| `GET` | `/api/ytdlp-version` | Get installed yt-dlp version |
| `POST` | `/api/ytdlp-update` | Update yt-dlp to latest release |
| `GET` | `/api/cookies` | List uploaded cookies files |
| `POST` | `/api/cookies/upload` | Upload a Netscape cookies file |
| `DELETE` | `/api/cookies/{filename}` | Delete a cookies file |
| `GET` | `/api/export` | Export settings and channels as JSON |
| `POST` | `/api/import` | Import configuration JSON |
| `GET` | `/api/disk` | Disk capacity and free space stats |
| `GET` | `/api/health` | Service health and active slot usage |

</details>

---

## 🍓 Raspberry Pi / Low-Power Devices

Enable Pi mode in `docker-compose.yml` or via environment:

```yaml
environment:
  - STREAMREC_PI_MODE=1
```

Optimizations applied:
- Concurrent subprocess limit reduced (6 → 3)
- Polling intervals relaxed to save CPU cycles
- FFmpeg thread count constrained to prevent thermal throttling
- yt-dlp buffer capped at 32 KB to minimize memory consumption

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
