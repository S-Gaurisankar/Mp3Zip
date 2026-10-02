#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================================="
echo "    Mp3Zip - Studio Music Extraction & Transcoding Engine  "
echo "=========================================================="

if [ ! -d "venv" ]; then
    echo "[*] Initializing Python virtual environment..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt
fi

echo "[*] Verifying system binaries..."
command -v ffmpeg >/dev/null 2>&1 || { echo >&2 "[!] Error: ffmpeg is required but not installed."; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { echo >&2 "[!] Error: ffprobe is required but not installed."; exit 1; }

echo "[*] Launching Mp3Zip Web Dashboard on http://localhost:8000..."
./venv/bin/python main.py "$@"
