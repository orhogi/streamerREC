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
  <strong>Self-hosted live stream recorder with a beautiful web UI.</strong><br>
  Automatically monitor and record live streams from 30+ platforms — all from a single dashboard.
</p>

<p align="center">
  <img src="screenshots/channels-dark.png" alt="StreamRec Dashboard – Dark Mode" width="100%">
</p>

---

## 📑 Table of Contents

- [Features](#-features)
- [Screenshots](#-screenshots)
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
- **Automatic Live Detection** — Periodically checks if a channel is live and starts recording automatically
- **Multi-Channel Monitoring** — Monitor dozens of channels simultaneously from a single dashboard
- **One-Click Recording** — Manually start/stop recordings at any time
- **Quality Selection** — Choose from Best, 1080p, 720p, 480p, or Lowest quality per channel
- **Multiple Formats** — Record in MP4, MKV, or TS container formats
- **Live-from-Start** — Captures the stream from the very beginning (on supported platforms)
- **Bulk Actions** — Multi-select channels and record, stop, delete, or edit quality/format in bulk
- **Channel Reordering** — Drag-and-drop to organize your channel list
- **Per-Channel Notes** — Add private notes to each channel for context
- **Stream Title Tracking** — See what the streamer is currently broadcasting

### 📡 Smart Recording
- **Auto-Retry on Disconnect** — Automatically reconnects when a stream drops, with configurable retry count and delay
- **Post-Processing** — Optionally auto-convert recordings to MP4 after completion (lossless remux)
- **Container Fix** — Automatically remuxes interrupted recordings to fix broken containers
- **Progress Tracking** — Real-time file size, download speed, and duration displayed per recording
- **Max Duration Enforcement** — Set a per-channel or global time limit; recordings auto-stop gracefully when reached
- **Recording Retention** — Auto-delete recordings older than N days to manage disk space (0 = keep forever)
- **Stalled Detection** — Warns (or auto-stops) when a stream stops sending data silently
- **Webhook Notifications** — POST JSON to any HTTP endpoint when streams go live or recordings complete
- **Archive & Restore** — Move completed recordings to an archive folder and restore them later

### 🖥️ Beautiful Web Interface
- **Dark & Light Themes** — Toggle between dark and light mode with one click
- **Responsive Design** — Works on desktop, tablet, and mobile
- **Search & Filter** — Quickly find channels by name, platform, notes, or stream title
- **Sort Channels** — Order by name, platform, recently added, last checked, or live first
- **Recordings Filter & Sort** — Filter by status and sort by date, size, or name
- **In-Browser Preview** — Play back completed recordings directly in the browser
- **Live Log Panel** — View real-time yt-dlp output from the channels or recordings page
- **Disk Usage Stats** — Monitor your storage usage from the recordings page
- **Concurrent Slot Indicator** — See how many recording slots are in use (e.g. 2/6)
- **Keyboard Shortcuts** — Press `N` to add, `1-4` to navigate pages, `R/S/Del` for bulk actions

### ⚙️ Configuration
- **Per-Channel Overrides** — Set quality, format, proxy, and post-processing options individually per channel
- **VPN / Proxy Support** — Route any channel through a proxy or WireGuard VPN (built-in wireproxy sidecar)
- **Cookies / Credentials** — Record age-restricted streams using browser cookies or username/password
- **Import / Export** — Back up and restore your channel list and settings as a JSON file
- **Persistent State** — All channels, settings, and finished recordings survive container restarts
- **Raspberry Pi Mode** — Built-in resource-constrained mode for low-power devices (`STREAMREC_PI_MODE=1`)

### 👤 Local Account (optional)
- **Personalize the dashboard** — Pick a username and a profile picture that shows in the top-right corner across every page
- **Password-protected** — Stored with PBKDF2-HMAC-SHA256 (200k iterations) over a 32-byte random salt; the plaintext is never written to disk
- **Skip anytime** — A **Skip for now** button on the welcome screen keeps the full dashboard usable without an account
- **Account settings menu** — Edit username, change password (with current-password verification), swap or remove your profile picture, or delete the account entirely
- **Private on-disk** — Account file (`account.json`) is `chmod 600` on Unix and lives inside the recordings volume, not in the exported config

### 🛡️ Reliability
- **Supervised monitor loop** — Per-channel live checks run in parallel and crash-isolated; one broken URL can't stall detection for the rest
- **Graceful shutdown** — In-flight recordings are stopped cleanly and state is flushed when the server exits
- **Proper concurrency caps** — Concurrent `yt-dlp` and `curl` subprocesses honour the process semaphore
- **Per-channel recording lock** — Prevents accidental double-recording from concurrent calls
- **Stalled recording detection** — Warns (or auto-stops) when a stream stops sending data silently
- **Upload limits** — Cookies files capped at 5 MiB, profile pictures at 2 MiB
- **PBKDF2 password hashing** — Account passwords hashed with 200k SHA256 iterations; plaintext never stored
- **Atomic file writes** — State and account files written to `.tmp` then atomically renamed to prevent corruption

---

## 📸 Screenshots

### 🌙 Dark Mode — Channels
> The main dashboard showing all monitored channels with live status, recording controls, and real-time stats.

<img src="screenshots/channels-dark.png" alt="Channels page in dark mode" width="100%">

### ☀️ Light Mode — Channels
> The same channel dashboard in light theme — switch with one click.

<img src="screenshots/channels-light.png" alt="Channels page in light mode" width="100%">

### ➕ Add Channel
> Add any channel by pasting a URL — StreamRec auto-detects the platform and fetches metadata.

<img src="screenshots/add-channel.png" alt="Add channel modal" width="100%">

### ⚙️ Settings
> Configure global defaults, proxy, cookies, auto-retry behavior, and more.

<img src="screenshots/settings.png" alt="Settings page" width="100%">

### 🎬 Recordings
> Browse, preview, download, or delete completed recordings — all from the web UI.

<img src="screenshots/recordings.png" alt="Recordings page" width="100%">

### 🌐 Platforms
> View all 30+ supported streaming platforms at a glance.

<img src="screenshots/platforms.png" alt="Platforms page" width="100%">

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
   ```
   http://localhost:8080
   ```

That's it! Your recordings will be saved in the `./recordings` directory.

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

### Manual Installation

**Prerequisites:**
- Python 3.12+
- [FFmpeg](https://ffmpeg.org/download.html)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp#installation)

```bash
pip install -r requirements.txt
mkdir -p recordings
uvicorn main:app --host 0.0.0.0 --port 8080
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

Your channels, settings, and completed recordings are stored in `./recordings/state.json` and will persist across updates. If you created a local account, the hashed credentials live in `./recordings/account.json` and your profile picture in `./recordings/avatars/` — back these up alongside the rest of the recordings folder.

### Manual

```bash
cd streamerREC
git pull
pip install -r requirements.txt --upgrade
# Restart the server
```

---

## 🔒 VPN / Proxy Setup

StreamRec includes a built-in WireGuard proxy (wireproxy) that runs as a sidecar container. It exposes a SOCKS5 proxy at `socks5://wireproxy:1080` that you can assign to individual channels or globally.

This is useful for:
- Recording geo-blocked streams
- Routing cam site traffic through a VPN
- Bypassing IP bans on specific platforms

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

> You can get a WireGuard config from any VPN provider (Mullvad, ProtonVPN, etc.) or your own server.

### 2. Rebuild with the VPN config

```bash
docker compose down && docker compose build && docker compose up -d
```

### 3. Assign the proxy to a channel

In the web UI:
1. Open a channel's settings
2. Set the **Proxy** field to:
   ```
   socks5://wireproxy:1080
   ```
3. Save

That channel will now record and check live status through the VPN.

### 4. Set a global proxy (optional)

To route **all** channels through the VPN:
1. Go to **Settings**
2. Set the **Proxy** field to:
   ```
   socks5://wireproxy:1080
   ```
3. Save

> The proxy is opt-in — channels without a proxy set go direct. Live detection also routes through the proxy, so geo-blocked channels are detected correctly.

---

## 🍪 Cookies / Age-Restricted Streams

For platforms that require login (age-restricted content, private streams):

1. Export your browser cookies using a browser extension (e.g. **Get cookies.txt LOCALLY**)
2. Go to **Settings → Cookies** in the web UI and upload the file
3. Assign the cookies file to the channel in its settings

You can also set a username/password per channel for platforms that support it.

### Webhook Event Payloads

<details>
<summary><strong><code>stream_live</code> — fired when a monitored stream goes live</strong></summary>

```json
{
  "event": "stream_live",
  "channel_id": "abc12345",
  "name": "StreamerName",
  "url": "https://twitch.tv/streamer",
  "platform": "Twitch",
  "recording_id": "def67890"
}
```
</details>

<details>
<summary><strong><code>recording_complete</code> — fired when a recording finishes (success or error)</strong></summary>

```json
{
  "event": "recording_complete",
  "recording_id": "def67890",
  "channel_id": "abc12345",
  "status": "completed",
  "filename": "StreamerName_2026-05-03_14-30-00.mp4",
  "bytes": 150994944,
  "error": "",
  "platform": "Twitch"
}
```
</details>

---

## 🧰 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAMREC_PI_MODE` | `0` | Set to `1` to enable Raspberry Pi mode |
| `RECORDINGS_DIR` | `~/StreamRec/recordings` | Override recordings directory |

### Settings (via Web UI)

| Setting | Default | Description |
|---------|---------|-------------|
| Potato / Pi mode | Off | Reduce CPU/RAM/I/O for low-power devices |
| Check Interval | 60s (120s Pi) | How often to check if channels are live |
| Auto-record when live | Off | Start recording automatically when a stream goes live |
| Default Quality | `best` | Default recording quality for new channels |
| Default Format | `mp4` | Default container format |
| Auto-convert to MP4 | Off | Remux completed recordings to MP4 |
| Delete Original | Off | Remove source file after MP4 conversion |
| Auto-Retry | On | Reconnect on unexpected disconnections |
| Max Retries | 5 | Maximum reconnect attempts |
| Retry Delay | 15s | Wait time between retries |
| Proxy | — | Global proxy for all channels |
| Extra yt-dlp args | — | Additional yt-dlp arguments applied globally |
| Cookies File | — | Global cookies file for authentication |
| Retention Days | 0 (keep forever) | Auto-delete recordings older than this |
| Max Duration | 0 (no limit) | Auto-stop recordings after N minutes (global) |
| Webhook URL | — | POST JSON on stream live & recording complete |
| Auto-stop stalled | Off | Force-stop recordings that stop receiving data |

---

## 🏗️ Architecture

```
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

- **Frontend:** Single-page HTML/CSS/JS (no build step)
- **Backend:** Python FastAPI with async subprocess management
- **Recording:** Powered by yt-dlp and FFmpeg
- **State:** JSON file persisted to the recordings volume
- **VPN:** Optional wireproxy sidecar (WireGuard → SOCKS5)

---

## 📁 Project Structure

```
streamerREC/
├── main.py              # FastAPI backend — API routes, recording engine, monitor loop
├── index.html           # Complete frontend — single-file SPA with embedded CSS/JS
├── Dockerfile           # Container image definition
├── Dockerfile.wireproxy # Wireproxy sidecar image
├── docker-compose.yml   # Docker Compose service configuration
├── requirements.txt     # Python dependencies
├── screenshots/         # App screenshots used in README
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
| `GET` | `/api/channels` | List all channels |
| `PATCH` | `/api/channels/{id}` | Update channel settings |
| `DELETE` | `/api/channels/{id}` | Delete a channel |
| `POST` | `/api/channels/{id}/record` | Start recording |
| `POST` | `/api/channels/{id}/stop` | Stop recording (graceful) |
| `POST` | `/api/channels/{id}/kill` | Force-stop recording |
| `POST` | `/api/channels/{id}/refresh` | Refresh channel metadata |
| `POST` | `/api/channels/reorder` | Reorder channel list |
| `POST` | `/api/channels/bulk` | Bulk record/stop/delete |
| `POST` | `/api/channels/bulk-edit` | Bulk edit quality/format |

</details>

<details>
<summary><strong>Recordings</strong></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/recordings` | List all recordings |
| `GET` | `/api/recordings/{id}/log` | Get recording log |
| `GET` | `/api/download/{id}` | Download a recording |
| `GET` | `/api/preview/{id}` | Stream/preview a recording |
| `DELETE` | `/api/recordings/{id}` | Delete a recording |
| `POST` | `/api/recordings/{id}/archive` | Archive a recording |
| `POST` | `/api/recordings/{id}/restore` | Restore an archived recording |

</details>

<details>
<summary><strong>Settings & System</strong></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/settings` | Get current settings |
| `PATCH` | `/api/settings` | Update settings |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/version` | Get StreamRec version |
| `GET` | `/api/disk` | Disk usage stats |
| `GET` | `/api/export` | Export configuration |
| `POST` | `/api/import` | Import configuration |

</details>

<details>
<summary><strong>Account</strong></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/account` | Get current account (`{exists: false}` if none) |
| `POST` | `/api/account` | Create account (`username`, `password`, `confirm_password`) |
| `PATCH` | `/api/account` | Update username or change password |
| `DELETE` | `/api/account` | Delete the account and its avatar |
| `POST` | `/api/account/avatar` | Upload a profile picture (multipart, max 2 MiB) |
| `DELETE` | `/api/account/avatar` | Remove the current profile picture |
| `POST` | `/api/account/login` | Verify `username` + `password` against the stored hash |

</details>

---

## 🍓 Raspberry Pi / Low-Power Devices

```yaml
environment:
  - STREAMREC_PI_MODE=1
```

When enabled:
- Concurrent subprocess limit reduced from 6 → 3
- Default monitor interval increased from 60s → 120s
- FFmpeg threads limited to 1 (vs 2 normally) for lower CPU usage
- yt-dlp download buffer capped at 32 KB to reduce memory usage
- File-size polling interval increased from 3s → 8s
- Log buffer trimmed more aggressively (60 → 30 lines)
- Disk usage cache extended from 30s → 60s
- State saves debounced (2s coalesce window) to reduce disk I/O
- Frontend poll interval increased from 5s → 10s
- Search inputs debounced to reduce DOM queries

> **Tip:** Uncomment the `deploy.resources.limits` section in `docker-compose.yml` to also limit RAM and CPU usage.

---

## ❓ Troubleshooting

<details>
<summary><strong>Stream is live but not detected</strong></summary>

- Check that the URL is correct and accessible from your server
- If the channel is geo-blocked, set up a [proxy or VPN](#-vpn--proxy-setup)
- Try increasing the check interval in Settings if you have many channels
- Use the **Refresh** button on the channel card to manually re-check

</details>

<details>
<summary><strong>Recording starts but file is 0 bytes or very small</strong></summary>

- Some platforms require cookies for full access — see [Cookies setup](#-cookies--age-restricted-streams)
- Try changing the recording quality (some streams don't support all quality levels)
- Check the recording log (click the channel card → view log) for error details

</details>

<details>
<summary><strong>Container won't start / port conflict</strong></summary>

- Make sure port 8080 isn't already in use: `lsof -i :8080`
- Change the port mapping in `docker-compose.yml`: `"3000:8080"` to use port 3000 instead
- Check Docker logs: `docker compose logs streamrec`

</details>

<details>
<summary><strong>wireproxy container keeps restarting</strong></summary>

- Make sure `wg0.conf` exists and is valid
- If you don't need the VPN feature, you can comment out the `wireproxy` service and the `depends_on` line in `docker-compose.yml`

</details>

<details>
<summary><strong>yt-dlp errors / unsupported site</strong></summary>

- Rebuild the Docker image to get the latest yt-dlp: `docker compose build --no-cache`
- For manual installs, update yt-dlp: `pip install -U yt-dlp`
- Check [yt-dlp supported sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) for compatibility

</details>

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** this repository
2. **Create** a feature branch: `git checkout -b my-feature`
3. **Commit** your changes: `git commit -m "Add my feature"`
4. **Push** to the branch: `git push origin my-feature`
5. **Open** a pull request

### Ideas for contributions
- 🌐 Add translations / i18n support
- 📨 Add more notification targets (Telegram, Pushover, Apprise, email)
- 🧪 Add test coverage
- 📊 Add recording analytics / statistics dashboard
- ☁️ Automatic cloud backup (S3, R2, Backblaze B2)
- 🧩 Plugin system for custom post-processing scripts
- 📱 PWA support (offline mode, push notifications)

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
