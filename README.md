# Mp3Zip - Studio Audio Extractor & MP3 Transcoder

A production-grade, automated music extraction engine that resolves pristine studio audio streams from YouTube Music, transcodes strictly to high-fidelity MP3 (LAME VBR V0), embeds ID3v2.3 tags and cover art, and provides a real-time reactive web UI and CLI.

---

## 🏗️ Architectural Foundations & Standards

1. **Standardized Stream Resolution (`yt-dlp`):**
   * Uses `yt-dlp` core engine with progress hooks, exponential retry handling, and cipher resolution.
   * Target stream pattern: Decouples metadata resolution from YouTube video search, querying studio masters (`ytsearch1:<Artist> - <Title> official audio` or Topic tracks) to eliminate skits, dialogue, and extended music video intros.

2. **Strict MP3 Delivery & Optimal Transcoding (FFmpeg):**
   * YouTube stores audio natively in Opus (~160 kbps) or AAC (~128 kbps). Artificial CBR 320 kbps padding is strictly avoided (which inflates file sizes by 3x without recovering lost frequencies).
   * Stream is transcoded to MP3 via `libmp3lame` with **Variable Bitrate (VBR) V0** (`-q:a 0`, ~245 kbps perceptual maximum) and resampled to **44,100 Hz** (`-ar 44100`) for maximum perceptual fidelity and legacy device compatibility.
   * Container tags are cleanly stripped (`-map_metadata -1`) prior to ID3 tagging.

3. **Atomic File Operations & Fault Tolerance:**
   * Intermediate files and raw streams execute inside an isolated scratch workspace (`.tmp_work/<job_id>/`).
   * Transcoded MP3s are tagged with ID3v2.3 frames (`TIT2`, `TPE1`, `TALB`, `TYER`, `TRCK`, `APIC` front cover art) via `mutagen`.
   * Atomically moves finished `.mp3` files to `output/<Artist>/<Artist> - <Title>.mp3` only upon zero-error exit codes.
   * Automatically purges scratch directories and orphan files upon failure, cancellation, or engine restart.
   * Applies randomized jitter (2–5s) between requests to prevent HTTP 429 rate limiting.

4. **Asynchronous Task Queue & WebSockets:**
   * Multi-worker background task pool with state machine:
     `Queued` ➔ `Resolving Stream` ➔ `Downloading` ➔ `Transcoding (FFmpeg)` ➔ `Tagging ID3` ➔ `Completed` / `Failed`.
   * Real-time WebSocket broadcasting with sub-second ETA, speed, and percentage updates.

---

## 🚀 Quick Start

### 1. Requirements
* Linux / macOS / Windows with **Python 3.10+**
* `ffmpeg` and `ffprobe` with `libmp3lame` support installed:
  ```bash
  # Ubuntu / Debian
  sudo apt update && sudo apt install -y ffmpeg

  # macOS
  brew install ffmpeg
  ```

### 2. Launch Web Application
```bash
./start.sh
```
Or manually:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py --port 8000
```
Open your browser at **`http://localhost:8000`**.

### 3. CLI Mode
You can also run extraction jobs directly from the terminal:
```bash
# Single or multiple tracks
./venv/bin/python main.py --cli -t "Daft Punk - Get Lucky" "Pink Floyd - Time"

# From a track list file (.txt or .csv)
./venv/bin/python main.py --cli -f tracks.txt -o ./my_music
```

---

## 💻 Dashboard Features

1. **Ingestion Controls:**
   * Multi-line text box supporting `Artist - Title`, `Artist - Title (Album)`, CSV (`Artist,Title,Album`), and direct YouTube Music URLs.
   * Drag-and-drop file uploader for `.txt` and `.csv` files.
   * Preset confirmation banner verifying LAME VBR V0, 44.1 kHz, and Topic targeting.

2. **Real-Time Job Queue & State Machine:**
   * Live status badges with animations per track.
   * Dynamic progress bars with real-time download speed (MB/s) and ETA.
   * Inline Retry button with manual search query / stream override modal.
   * Task cancellation and queue clearing controls.

3. **Completed Library & Audio Preview:**
   * Embedded sticky audio preview player with waveform visualizer and seekbar.
   * Filter and search library tracks by artist, album, or title.
   * One-click "Open Output Folder" action triggering OS file manager (`xdg-open` / `open` / `explorer`).

4. **Settings & System Diagnostics:**
   * Automatic startup detection and validation of `ffmpeg`, `ffprobe`, and `libmp3lame`.
   * Configurable output directory, concurrency limit, and randomized jitter delays.

---

## 📡 REST & WebSocket API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/system-status` | Probe FFmpeg, FFprobe, and encoder diagnostics |
| `GET` | `/api/queue` | Retrieve current queue state and history |
| `POST` | `/api/queue/add` | Enqueue tracks from raw text |
| `POST` | `/api/queue/upload` | Enqueue tracks from `.txt` or `.csv` upload |
| `POST` | `/api/queue/{id}/retry`| Retry job with optional search override |
| `POST` | `/api/queue/{id}/cancel`| Cancel active or pending extraction |
| `POST` | `/api/queue/clear` | Clear completed/failed or all jobs |
| `GET` | `/api/library` | List downloaded tracks with ID3 metadata |
| `GET` | `/api/library/stream` | Stream MP3 for browser audio preview player |
| `POST` | `/api/library/open` | Open output directory in system file explorer |
| `GET` | `/api/config` | Get current application configuration |
| `POST` | `/api/config` | Update output directory, jitter, and concurrency |
| `WS` | `/ws` | Bi-directional real-time WebSocket connection |

---

## 🧪 Testing

Run the automated test suite covering system diagnostics, metadata parsing, FFmpeg LAME transcoding, ID3 tagging, and FastAPI endpoints:
```bash
./venv/bin/python -m unittest discover tests
```
