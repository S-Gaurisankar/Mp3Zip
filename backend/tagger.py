import logging
from pathlib import Path
from typing import Optional
import requests
from mutagen.id3 import (
    ID3,
    ID3NoHeaderError,
    TIT2,
    TPE1,
    TALB,
    TDRC,
    TYER,
    TRCK,
    TCON,
    COMM,
    APIC,
    Encoding
)
from mutagen.mp3 import MP3

logger = logging.getLogger("Tagger")

def fetch_image_data(image_url: str) -> Optional[bytes]:
    """Download cover art image bytes."""
    if not image_url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(image_url, headers=headers, timeout=3)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception as e:
        logger.warning(f"Could not fetch thumbnail image from {image_url}: {e}")
    return None

def embed_id3_tags(
    mp3_file_path: Path,
    title: str,
    artist: str,
    album: Optional[str] = "Single",
    year: Optional[str] = None,
    track_number: Optional[int] = None,
    genre: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    comment: str = "Studio Audio Extractor"
) -> bool:
    """
    Inject clean ID3v2.3 tags and embedded album art into the MP3 file.
    """
    if not mp3_file_path.exists():
        logger.error(f"Cannot tag non-existent file: {mp3_file_path}")
        return False

    try:
        try:
            audio = MP3(str(mp3_file_path), ID3=ID3)
            if audio.tags is None:
                audio.add_tags()
        except ID3NoHeaderError:
            audio = MP3(str(mp3_file_path))
            audio.add_tags()

        tags = audio.tags

        # Clear any existing corrupted tags
        tags.clear()

        # Text frames (Encoding.UTF8 / Encoding.LATIN1)
        # Using UTF_8 for full international artist/title support
        enc = Encoding.UTF8

        tags.add(TIT2(encoding=enc, text=[title]))
        tags.add(TPE1(encoding=enc, text=[artist]))
        tags.add(TALB(encoding=enc, text=[album or "Single"]))

        if year:
            tags.add(TDRC(encoding=enc, text=[str(year)]))
            tags.add(TYER(encoding=enc, text=[str(year)]))

        if track_number is not None:
            tags.add(TRCK(encoding=enc, text=[str(track_number)]))

        if genre:
            tags.add(TCON(encoding=enc, text=[genre]))

        if comment:
            tags.add(COMM(encoding=enc, lang="eng", desc="Metadata", text=[comment]))

        # Album Art Embed
        art_data = image_bytes or (fetch_image_data(thumbnail_url) if thumbnail_url else None)
        if art_data:
            mime = "image/jpeg"
            if art_data.startswith(b"\x89PNG"):
                mime = "image/png"

            tags.add(
                APIC(
                    encoding=enc,
                    mime=mime,
                    type=3,  # Front cover
                    desc="Cover",
                    data=art_data
                )
            )

        # Save with ID3v2.3 for maximum player compatibility (cars, hi-fi, older mp3 players)
        tags.save(str(mp3_file_path), v2_version=3)
        logger.info(f"Successfully embedded ID3 tags into {mp3_file_path.name}")
        return True

    except Exception as e:
        logger.error(f"Failed to embed ID3 tags into {mp3_file_path}: {e}")
        return False
