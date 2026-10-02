import shutil
import subprocess
from typing import Dict, Any, Tuple

def check_binary(binary_name: str) -> Tuple[bool, str]:
    path = shutil.which(binary_name)
    if not path:
        return False, f"'{binary_name}' binary not found in system PATH."
    try:
        res = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            first_line = res.stdout.splitlines()[0] if res.stdout else "Available"
            return True, f"{path} ({first_line})"
        return True, path
    except Exception as e:
        return False, f"Error checking {binary_name}: {str(e)}"

def check_mp3lame_support() -> Tuple[bool, str]:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return False, "ffmpeg not found"
    try:
        res = subprocess.run([ffmpeg_path, "-encoders"], capture_output=True, text=True, timeout=5)
        if "libmp3lame" in res.stdout:
            return True, "libmp3lame encoder detected"
        return False, "libmp3lame encoder not found in ffmpeg build"
    except Exception as e:
        return False, f"Failed to probe encoders: {str(e)}"

def run_system_diagnostics() -> Dict[str, Any]:
    ffmpeg_ok, ffmpeg_msg = check_binary("ffmpeg")
    ffprobe_ok, ffprobe_msg = check_binary("ffprobe")
    lame_ok, lame_msg = check_mp3lame_support() if ffmpeg_ok else (False, "N/A")

    all_ok = ffmpeg_ok and ffprobe_ok and lame_ok

    troubleshooting = []
    if not ffmpeg_ok or not ffprobe_ok:
        troubleshooting.append("FFmpeg/FFprobe missing. Install via: 'sudo apt update && sudo apt install -y ffmpeg' (Debian/Ubuntu) or 'brew install ffmpeg' (macOS) or download from https://ffmpeg.org/download.html")
    if ffmpeg_ok and not lame_ok:
        troubleshooting.append("FFmpeg is missing MP3 support (libmp3lame). Please install a full build of FFmpeg.")

    return {
        "ready": all_ok,
        "ffmpeg": {
            "available": ffmpeg_ok,
            "details": ffmpeg_msg
        },
        "ffprobe": {
            "available": ffprobe_ok,
            "details": ffprobe_msg
        },
        "libmp3lame": {
            "available": lame_ok,
            "details": lame_msg
        },
        "troubleshooting": troubleshooting
    }
