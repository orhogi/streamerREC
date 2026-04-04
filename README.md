<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/yt--dlp-latest-red?logo=youtube&logoColor=white" alt="yt-dlp">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

<h1 align="center">🔴 StreamRec</h1>

<p align="center">
  <strong>Self-hosted live stream recorder with a beautiful web UI.</strong><br>
  Automatically monitor and record live streams from 20+ platforms — all from a single dashboard.
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/e277c969-f4be-41cf-86d8-159a5b0687d4" alt="StreamRec Dashboard — Dark Mode" width="100%">
</p>

---

## ✨ Features

### 📡 Multi-Platform Support
Record live streams from **20+ platforms** including:

| Platform | Platform | Platform | Platform |
|----------|----------|----------|----------|
| YouTube | Twitch | TikTok | Kick |
| Bilibili | Instagram | Facebook | Twitter/X |
| Rumble | Vimeo | Dailymotion | Niconico |
| Douyin | Huya | Douyu | Afreeca |
| Sooplive | Naver | Weibo | Bigo |
| Twitcasting | Pandalive | Stripchat | _…and more via yt-dlp_ |

### 🎯 Core Capabilities
- **Automatic Live Detection** — Periodically checks if a channel is live and starts recording automatically
- **Multi-Channel Monitoring** — Monitor dozens of channels simultaneously from a single dashboard
- **One-Click Recording** — Manually start/stop recordings at any time
- **Quality Selection** — Choose from Best, 1080p, 720p, 480p, or Lowest quality per channel
- **Multiple Formats** — Record in MP4, MKV, or TS container formats
- **Live-from-Start** — Captures the stream from the very beginning (on supported platforms)
- **Bulk Actions** — Select multiple channels and record, stop, or delete them all at once
- **Channel Reordering** — Drag-and-drop to organize your channel list

### 🔄 Smart Recording
- **Auto-Retry on Disconnect** — Automatically reconnects when a stream drops, with configurable retry count and delay
- **Post-Processing** — Optionally auto-convert recordings to MP4 after completion (lossless remux)
- **Container Fix** — Automatically remuxes interrupted recordings to fix broken containers
- **Progress Tracking** — Real-time file size and download speed displayed per recording

### 🖥️ Beautiful Web Interface
- **Dark & Light Themes** — Toggle between dark and light mode with one click
- **Responsive Design** — Works on desktop, tablet, and mobile
- **Search & Filter** — Quickly find channels with the built-in search bar
- **In-Browser Preview** — Play back completed recordings directly in the browser with streaming video support
- **Live Log Panel** — View real-time recording logs at the bottom of the screen
- **Disk Usage Stats** — Monitor your storage usage from the recordings page

### ⚙️ Configuration
- **Per-Channel Overrides** — Set quality, format, and post-processing options individually per channel
- **Import / Export** — Back up and restore your channel list and settings as a JSON file
- **Persistent State** — All channels and settings survive container restarts
- **Raspberry Pi Mode** — Built-in resource-constrained mode for low-power devices (`STREAMREC_PI_MODE=1`)

---

## 📸 Screenshots

<details>
<summary><strong>🌙 Dark Mode — Channels</strong></summary>
<br>
<img src="https://github.com/user-attachments/assets/e277c969-f4be-41cf-86d8-159a5b0687d4" alt="Channels page in dark mode" width="100%">
</details>

<details>
<summary><strong>☀️ Light Mode — Channels</strong></summary>
<br>
<img src="https://github.com/user-attachments/assets/167226bf-1b10-4a1a-96c4-94f0deb13a64" alt="Channels page in light mode" width="100%">
</details>

<details>
<summary><strong>⚙️ Settings</strong></summary>
<br>
<img src="https://github.com/user-attachments/assets/d1d5b426-061a-4496-8a88-49d0225336bd" alt="Settings page" width="100%">
</details>

<details>
<summary><strong>➕ Add Channel</strong></summary>
<br>
<img src="https://github.com/user-attachments/assets/3dd39816-a93b-4f0f-afbc-8295cf857661" alt="Add channel modal" width="100%">
</details>

<details>
<summary><strong>🎬 Recordings</strong></summary>
<br>
<img src="https://github.com/user-attachments/assets/008ac8ca-59a8-4d3e-ac2a-3a30ec377bf5" alt="Recordings page" width="100%">
</details>

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
# Install Python dependencies
pip install -r requirements.txt

# Create recordings directory
mkdir -p recordings

# Start the server
uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAMREC_PI_MODE` | `0` | Set to `1` to enable Raspberry Pi mode (reduces concurrency, increases check intervals) |

### Settings (via Web UI)

| Setting | Default | Description |
|---------|---------|-------------|
| Check Interval | 60s (120s Pi) | How often to check if channels are live |
| Default Quality | `best` | Default recording quality for new channels |
| Default Format | `mp4` | Default container format |
| Auto-convert to MP4 | Off | Remux completed recordings to MP4 |
| Delete Original | Off | Remove source file after MP4 conversion |
| Auto-Retry | On | Reconnect on unexpected disconnections |
| Max Retries | 5 | Maximum reconnect attempts |
| Retry Delay | 15s | Wait time between retries |

---

## 🏗️ Architecture

StreamRec is a single-container application with a clean architecture:

```
┌─────────────────────────────────────────────┐
│                  Browser                     │
│            (index.html — SPA)                │
└──────────────────┬──────────────────────────┘
                   │ REST API
┌──────────────────▼──────────────────────────┐
│              FastAPI Server                   │
│               (main.py)                      │
│                                              │
│  ┌────────────┐  ┌────────────┐  ┌────────┐ │
│  │  Channel    │  │  Recording │  │ Monitor│ │
│  │  Manager    │  │  Engine    │  │  Loop  │ │
│  └────────────┘  └─────┬──────┘  └────────┘ │
│                        │                     │
│                  ┌─────▼──────┐              │
│                  │  yt-dlp +  │              │
│                  │   FFmpeg   │              │
│                  └────────────┘              │
└──────────────────────────────────────────────┘
                   │
            ┌──────▼──────┐
            │ /recordings │
            │  (volume)   │
            └─────────────┘
```

- **Frontend:** Single-page HTML/CSS/JS application (no build step required)
- **Backend:** Python FastAPI with async subprocess management
- **Recording:** Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [FFmpeg](https://ffmpeg.org/)
- **State:** JSON file persisted to the recordings volume

---

## 📁 Project Structure

```
streamerREC/
├── main.py              # FastAPI backend — API routes, recording engine, monitor loop
├── index.html           # Complete frontend — single-file SPA with embedded CSS/JS
├── Dockerfile           # Container image definition
├── docker-compose.yml   # Docker Compose service configuration
├── requirements.txt     # Python dependencies (fastapi, uvicorn)
└── README.md            # This file
```

---

## 🔌 API Reference

StreamRec exposes a full REST API that powers the web UI. You can also use it for automation and integrations.

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

</details>

<details>
<summary><strong>Settings & System</strong></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/settings` | Get current settings |
| `PATCH` | `/api/settings` | Update settings |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/disk` | Disk usage stats |
| `GET` | `/api/export` | Export configuration |
| `POST` | `/api/import` | Import configuration |

</details>

---

## 🍓 Raspberry Pi / Low-Power Devices

StreamRec includes a dedicated Pi mode for running on resource-constrained hardware:

```yaml
environment:
  - STREAMREC_PI_MODE=1
```

When enabled:
- Concurrent subprocess limit reduced from 6 → 3
- Default monitor interval increased from 60s → 120s

The included `docker-compose.yml` also sets resource limits (512 MB RAM, 3 CPU cores) suitable for Pi-class hardware.

---

## 🤝 Contributing

Contributions are welcome! Feel free to open an issue or submit a pull request.

---

## 📄 License

This project is open source. See the repository for license details.
