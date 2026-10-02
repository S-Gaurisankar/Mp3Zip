import re
import unicodedata
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

NOISE_PATTERNS = [
    r"\[\s*official\s*(?:music\s*)?video\s*\]",
    r"\(\s*official\s*(?:music\s*)?video\s*\)",
    r"\[\s*official\s*audio\s*\]",
    r"\(\s*official\s*audio\s*\)",
    r"\[\s*official\s*visualizer\s*\]",
    r"\(\s*official\s*visualizer\s*\)",
    r"\[\s*official\s*hd\s*video\s*\]",
    r"\[\s*4k(?:\s*uhd)?\s*\]",
    r"\(\s*4k(?:\s*uhd)?\s*\)",
    r"\[\s*hd\s*\]",
    r"\(\s*hd\s*\)",
    r"\[\s*hq\s*\]",
    r"\(\s*hq\s*\)",
    r"\[\s*lyrics?\s*\]",
    r"\(\s*lyrics?\s*\)",
    r"\[\s*lyric\s*video\s*\]",
    r"\(\s*lyric\s*video\s*\)",
    r"\[\s*audio\s*\]",
    r"\(\s*audio\s*\)",
    r"\[\s*visualizer\s*\]",
    r"\(\s*visualizer\s*\)",
    r"\[\s*explicit\s*\]",
    r"\(\s*explicit\s*\)",
    r"\[\s*clean\s*\]",
    r"\(\s*clean\s*\)",
    r"\[\s*remastered(?:\s*\d{4})?\s*\]",
    r"\(\s*remastered(?:\s*\d{4})?\s*\)",
    r"\[\s*\d{4}\s*remaster\s*\]",
    r"\(\s*\d{4}\s*remaster\s*\)",
    r"\[\s*prod(?:\.|\s+by)?\s+[^\]]+\]",
    r"\(\s*prod(?:\.|\s+by)?\s+[^\)]+\)",
    r"\|\s*official\s*(?:music\s*)?video.*$",
    r"\|\s*official\s*audio.*$",
]

def sanitize_filename(name: str) -> str:
    """Sanitize strings for safe filesystem paths cross-platform."""
    if not name:
        return "Unknown"
    # Replace invalid chars with space or dash
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(". ")
    return cleaned if cleaned else "Unknown"

class TrackMetadata(BaseModel):
    artist: str = "Unknown Artist"
    title: str = "Unknown Title"
    album: str = "Single"
    year: Optional[str] = None
    track_number: Optional[int] = None
    raw_input: str
    custom_search_override: Optional[str] = None
    is_direct_url: bool = False

    @property
    def clean_artist(self) -> str:
        return sanitize_filename(self.artist)

    @property
    def clean_title(self) -> str:
        return sanitize_filename(self.title)

    @property
    def clean_album(self) -> str:
        return sanitize_filename(self.album)

    @property
    def relative_target_path(self) -> str:
        """Standard path hierarchy: <Artist>/<Track>.mp3"""
        return f"{self.clean_artist}/{self.clean_artist} - {self.clean_title}.mp3"

    def get_search_query(self) -> str:
        """
        Build optimized search query for YouTube stream resolution.
        SpotDL/Metube pattern: target Topic tracks / official audio studio stream.
        """
        if self.custom_search_override:
            return self.custom_search_override.strip()

        if self.is_direct_url:
            return self.raw_input.strip()

        artist = self.artist.strip() if self.artist else ""
        title = self.title.strip() if self.title else ""

        if artist and artist.lower() not in ["various artists", "unknown artist", "unknown", "youtube", ""]:
            return f"ytsearch1:{artist} - {title} official audio"
        else:
            return f"ytsearch1:{title} official audio"


def clean_text_noise(text: str) -> str:
    """Remove video noise tokens, tags, and excess punctuation."""
    cleaned = text
    for pattern in NOISE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    
    # Normalize dashes and quotes
    cleaned = cleaned.replace("–", "-").replace("—", "-").replace("−", "-")
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("’", "'").replace("`", "'")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def parse_track_input(raw_line: str) -> TrackMetadata:
    """
    Parse and clean an arbitrary input string, CSV row, or direct URL into a TrackMetadata object.
    """
    raw = raw_line.strip()
    if not raw:
        return TrackMetadata(artist="Unknown Artist", title="Unknown Title", raw_input=raw)

    # Check if direct URL (YouTube, YouTube Music, etc.)
    if re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)/", raw):
        return TrackMetadata(
            artist="YouTube",
            title=raw,
            album="Web Stream",
            raw_input=raw,
            is_direct_url=True
        )

    # Check for CSV format (e.g. "Artist,Title" or "Artist,Title,Album")
    if "," in raw and not any(sep in raw for sep in [" - ", " – ", " — "]):
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) >= 3:
            artist = clean_text_noise(parts[0])
            title = clean_text_noise(parts[1])
            album = clean_text_noise(parts[2])
            return TrackMetadata(artist=artist, title=title, album=album or "Single", raw_input=raw)
        elif len(parts) == 2:
            artist = clean_text_noise(parts[0])
            title = clean_text_noise(parts[1])
            return TrackMetadata(artist=artist, title=title, album="Single", raw_input=raw)

    cleaned = clean_text_noise(raw)

    # Pattern: Artist - Title (Album) or Artist - Title
    dash_match = re.split(r"\s+-\s+", cleaned, maxsplit=1)
    if len(dash_match) == 2:
        artist_part, title_part = dash_match[0].strip(), dash_match[1].strip()
        
        # Check if title has album in brackets or parens at the end, e.g. "Song Title (Album Name)"
        album_match = re.search(r"[\(\[](?:from\s+)?(?:album\s+)?([^()\[\]]+)[\)\]]$", title_part, re.IGNORECASE)
        album_name = "Single"
        if album_match and len(album_match.group(1).strip()) > 1:
            potential_album = album_match.group(1).strip()
            # If not a standard noise tag that wasn't stripped
            if not any(k in potential_album.lower() for k in ["feat", "ft.", "deluxe", "bonus", "live", "version"]):
                album_name = potential_album
                title_part = title_part[:album_match.start()].strip()

        return TrackMetadata(
            artist=artist_part or "Unknown Artist",
            title=title_part or "Unknown Title",
            album=album_name,
            raw_input=raw
        )

    # Pattern: Title by Artist
    by_match = re.split(r"\s+by\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
    if len(by_match) == 2:
        title_part, artist_part = by_match[0].strip(), by_match[1].strip()
        return TrackMetadata(
            artist=artist_part or "Unknown Artist",
            title=title_part or "Unknown Title",
            album="Single",
            raw_input=raw
        )

    # Fallback: Whole line as Title without forced artist
    return TrackMetadata(
        artist="",
        title=cleaned,
        album="Single",
        raw_input=raw
    )

def parse_track_batch(text_content: str) -> List[TrackMetadata]:
    """Parse multiple lines of input text, CSV, or Spotify URLs."""
    from .spotify import is_spotify_url, parse_spotify_url
    
    results = []
    lines = [line.strip() for line in text_content.splitlines()]
    for line in lines:
        if not line or line.startswith("#"):
            continue

        if is_spotify_url(line):
            spotify_tracks = parse_spotify_url(line)
            if spotify_tracks:
                results.extend(spotify_tracks)
                continue

        results.append(parse_track_input(line))
    return results
