import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable
from .config import config

logger = logging.getLogger("Transcoder")

async def transcode_to_mp3(
    source_file: Path,
    target_mp3_path: Path,
    progress_callback: Optional[Callable[[str], None]] = None
) -> bool:
    """
    Transcode an input audio stream strictly to high-fidelity MP3 using FFmpeg:
    - Codec: libmp3lame
    - Variable Bitrate (VBR): V0 (-q:a 0)
    - Sample Rate: 44,100 Hz (-ar 44100)
    - Strip existing noisy metadata container tags (-map_metadata -1)
    """
    if not source_file.exists():
        logger.error(f"Source audio file does not exist: {source_file}")
        return False

    target_mp3_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(source_file),
        "-vn",                       # Disable video stream
        "-codec:a", "libmp3lame",    # High-quality LAME MP3 encoder
        "-q:a", str(config.vbr_quality),  # VBR V0 preset (~245kbps perceptual max)
        "-ar", str(config.sample_rate),   # 44.1 kHz standard audio rate
        "-map_metadata", "-1",       # Clean strip container metadata
        str(target_mp3_path)
    ]

    logger.info(f"Executing FFmpeg: {' '.join(cmd)}")
    if progress_callback:
        progress_callback("Running FFmpeg LAME V0 transcode...")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode(errors="replace")
            logger.error(f"FFmpeg transcoding failed with code {proc.returncode}: {error_msg}")
            return False

        if not target_mp3_path.exists() or target_mp3_path.stat().st_size == 0:
            logger.error(f"FFmpeg output file missing or empty: {target_mp3_path}")
            return False

        logger.info(f"FFmpeg transcode completed successfully: {target_mp3_path.name} ({target_mp3_path.stat().st_size / 1024:.1f} KB)")
        return True

    except Exception as e:
        logger.error(f"Exception during FFmpeg transcode: {e}", exc_info=True)
        return False
