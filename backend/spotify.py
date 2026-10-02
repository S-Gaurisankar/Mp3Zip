import re
import json
import logging
from typing import List, Optional, Dict, Any
import requests
from .metadata import TrackMetadata, clean_text_noise

logger = logging.getLogger("SpotifyResolver")

SPOTIFY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"
}

def is_spotify_url(url: str) -> bool:
    return bool(re.search(r"https?://open\.spotify\.com/(playlist|album|track)/[a-zA-Z0-9]+", url))

def parse_spotify_url(url: str) -> List[TrackMetadata]:
    """
    Scrapes and extracts track metadata from public Spotify playlists, albums, and tracks
    without requiring API keys or authentication.
    """
    url = url.strip()
    match = re.search(r"open\.spotify\.com/(playlist|album|track)/([a-zA-Z0-9]+)", url)
    if not match:
        return []

    entity_type = match.group(1) # playlist, album, track
    entity_id = match.group(2)

    embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
    logger.info(f"Resolving Spotify {entity_type}: {embed_url}")

    try:
        resp = requests.get(embed_url, headers=SPOTIFY_HEADERS, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Spotify embed returned status {resp.status_code}")
            return []

        # Find __NEXT_DATA__ JSON script
        json_match = re.search(r'<script\s+id=[\"\']__NEXT_DATA__[\"\']\s+type=[\"\']application/json[\"\']>(.*?)</script>', resp.text, re.DOTALL)
        if not json_match:
            logger.warning("Could not find __NEXT_DATA__ script in Spotify embed response")
            return []

        data = json.loads(json_match.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        
        album_name = entity.get("title") if entity_type in ["album", "playlist"] else "Single"
        track_list = entity.get("trackList", [])
        
        results = []
        for item in track_list:
            raw_title = item.get("title") or ""
            # Clean subtitle which contains artist names separated by comma / non-breaking space
            raw_subtitle = item.get("subtitle") or ""
            artist_str = raw_subtitle.replace("\u00a0", " ").strip()
            
            clean_t = clean_text_noise(raw_title)
            clean_a = clean_text_noise(artist_str) or "Various Artists"
            
            if clean_t:
                results.append(TrackMetadata(
                    artist=clean_a,
                    title=clean_t,
                    album=album_name,
                    raw_input=f"{clean_a} - {clean_t}"
                ))

        logger.info(f"Successfully resolved {len(results)} tracks from Spotify {entity_type}: {album_name}")
        return results

    except Exception as e:
        logger.error(f"Error parsing Spotify URL {url}: {e}", exc_info=True)
        return []
