import os
import shutil
import uuid
import random
import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any

import yt_dlp

from .config import config
from .metadata import TrackMetadata, sanitize_filename
from .transcoder import transcode_to_mp3
from .tagger import embed_id3_tags

logger = logging.getLogger("Downloader")

class DownloadProgressHook:
    def __init__(self, callback: Optional[Callable[[Dict[str, Any]], None]] = None, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.callback = callback
        self.loop = loop

    def _safe_call(self, payload: Dict[str, Any]):
        if not self.callback:
            return
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.callback, payload)
        else:
            try:
                self.callback(payload)
            except Exception:
                pass

    def __call__(self, d: Dict[str, Any]):
        if not self.callback:
            return

        status = d.get("status")
        if status == "downloading":
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            percent = (downloaded / total_bytes * 100) if total_bytes > 0 else 0.0
            
            speed = d.get("speed")
            speed_str = f"{speed / 1024 / 1024:.2f} MB/s" if speed else "N/A"
            
            eta = d.get("eta")
            eta_str = f"{eta}s" if eta is not None else "N/A"

            self._safe_call({
                "stage": "Downloading",
                "progress_percent": round(percent, 1),
                "downloaded_bytes": downloaded,
                "total_bytes": total_bytes,
                "speed_str": speed_str,
                "eta_str": eta_str,
                "filename": d.get("filename", "")
            })
        elif status == "finished":
            self._safe_call({
                "stage": "Transcoding (FFmpeg)",
                "progress_percent": 100.0,
                "speed_str": "Done",
                "eta_str": "0s"
            })

class MusicExtractionPipeline:
    def __init__(self):
        pass

    async def execute(
        self,
        job_id: str,
        track: TrackMetadata,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        cancel_token: Optional[asyncio.Event] = None
    ) -> Dict[str, Any]:
        """
        Full atomic extraction pipeline:
        1. Resolve stream via yt-dlp (Target Topic / Studio Audio)
        2. Download raw audio to isolated scratch folder (.tmp_work/<job_id>/)
        3. Transcode to clean MP3 VBR V0 via FFmpeg
        4. Tag ID3 metadata (Title, Artist, Album, Cover Art)
        5. Atomically move finalized MP3 to target library output/<Artist>/<Track>.mp3
        6. Clean up scratch directory.
        """
        scratch_base = config.resolve_scratch_path()
        job_scratch_dir = scratch_base / job_id
        job_scratch_dir.mkdir(parents=True, exist_ok=True)

        target_base = config.resolve_output_path()

        resolved_info = {}
        final_mp3_path: Optional[Path] = None

        try:
            # Check cancellation
            if cancel_token and cancel_token.is_set():
                raise asyncio.CancelledError("Job cancelled before start")

            # Update stage: Resolving Stream
            if progress_callback:
                progress_callback({
                    "stage": "Resolving Stream",
                    "progress_percent": 0.0,
                    "detail": f"Resolving audio stream: {track.get_search_query()}"
                })

            # Random jitter to prevent 429
            jitter = random.uniform(config.min_jitter_seconds, config.max_jitter_seconds)
            await asyncio.sleep(jitter)

            if cancel_token and cancel_token.is_set():
                raise asyncio.CancelledError("Job cancelled during jitter delay")

            # Setup yt-dlp options
            out_template = str(job_scratch_dir / "raw_audio.%(ext)s")
            loop = asyncio.get_running_loop()
            hook = DownloadProgressHook(progress_callback, loop=loop)

            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": out_template,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "progress_hooks": [hook],
                "retries": 5,
                "fragment_retries": 5,
                "socket_timeout": 20,
                # Prefer studio / official audio
                "default_search": "ytsearch1",
            }

            search_query = track.get_search_query()
            logger.info(f"[{job_id}] Querying yt-dlp with: {search_query}")

            # Run stream resolution and download in thread pool to prevent blocking event loop
            loop = asyncio.get_running_loop()

            def _ytdl_extract_and_download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(search_query, download=True)
                    if not info:
                        raise ValueError(f"No audio stream found for query: '{search_query}'")
                    if "entries" in info and info["entries"]:
                        info = info["entries"][0]
                    return info

            info_dict = await loop.run_in_executor(None, _ytdl_extract_and_download)
            resolved_info = {
                "yt_id": info_dict.get("id"),
                "yt_title": info_dict.get("title"),
                "uploader": info_dict.get("uploader"),
                "duration": info_dict.get("duration"),
                "thumbnail": info_dict.get("thumbnail"),
                "webpage_url": info_dict.get("webpage_url") or info_dict.get("url"),
                "view_count": info_dict.get("view_count"),
            }

            if progress_callback and resolved_info.get("thumbnail"):
                progress_callback({
                    "thumbnail_url": resolved_info["thumbnail"],
                    "detail": f"Stream: {resolved_info.get('yt_title', '')}"
                })

            if cancel_token and cancel_token.is_set():
                raise asyncio.CancelledError("Job cancelled after download")

            # Find the downloaded raw audio file in the scratch folder
            raw_files = list(job_scratch_dir.glob("raw_audio.*"))
            if not raw_files:
                raise FileNotFoundError(f"Raw audio file missing in {job_scratch_dir}")
            raw_audio_file = raw_files[0]

            # Stage: Transcoding (FFmpeg)
            if progress_callback:
                progress_callback({
                    "stage": "Transcoding (FFmpeg)",
                    "progress_percent": 80.0,
                    "thumbnail_url": resolved_info.get("thumbnail"),
                    "detail": "Transcoding to MP3 VBR V0 via FFmpeg..."
                })

            temp_mp3_file = job_scratch_dir / "processed.mp3"
            transcode_success = await transcode_to_mp3(raw_audio_file, temp_mp3_file)
            if not transcode_success:
                raise RuntimeError("FFmpeg audio transcoding failed")

            if cancel_token and cancel_token.is_set():
                raise asyncio.CancelledError("Job cancelled during transcode")

            # Stage: Tagging ID3
            if progress_callback:
                progress_callback({
                    "stage": "Tagging ID3",
                    "progress_percent": 90.0,
                    "thumbnail_url": resolved_info.get("thumbnail"),
                    "detail": "Injecting ID3 metadata & cover art..."
                })

            # Derive clean canonical metadata from yt-dlp audio stream
            yt_uploader = info_dict.get("uploader") or ""
            if yt_uploader.endswith(" - Topic"):
                yt_uploader = yt_uploader[:-8].strip()

            yt_artist = info_dict.get("artist") or info_dict.get("creator") or yt_uploader or ""
            yt_title = info_dict.get("track") or info_dict.get("title") or ""
            yt_album = info_dict.get("album") or ""

            # Clean noise from youtube title
            from .metadata import clean_text_noise
            yt_title = clean_text_noise(yt_title)
            
            # If yt_title contains "Artist - Title", extract them
            if " - " in yt_title:
                parts = yt_title.split(" - ", 1)
                candidate_artist = parts[0].strip()
                candidate_title = parts[1].strip()
                if not yt_artist or yt_artist.lower() in ["youtube", "various artists", ""]:
                    yt_artist = candidate_artist
                yt_title = candidate_title

            # Prioritize canonical YouTube / studio artist and title over raw sloppy user input
            if yt_artist and yt_artist.lower() not in ["youtube", "various artists", ""]:
                artist_to_tag = yt_artist
            elif track.artist and track.artist.lower() not in ["", "unknown artist", "various artists", "youtube"]:
                artist_to_tag = track.artist.strip()
            else:
                artist_to_tag = "Various Artists"

            if yt_title and yt_title.lower() not in ["unknown title", ""]:
                title_to_tag = yt_title
            elif track.title and track.title != "Unknown Title":
                title_to_tag = track.title.strip()
            else:
                title_to_tag = "Unknown Title"

            album_to_tag = track.album if (track.album and track.album != "Single") else (yt_album or "Single")
            thumb_url = resolved_info.get("thumbnail")

            tag_success = embed_id3_tags(
                mp3_file_path=temp_mp3_file,
                title=title_to_tag,
                artist=artist_to_tag,
                album=album_to_tag,
                thumbnail_url=thumb_url,
                comment="Extracted via Studio Audio Engine"
            )
            if not tag_success:
                logger.warning(f"[{job_id}] ID3 tagging finished with warnings, continuing to final save.")

            # Stage: Atomic move to target library
            clean_artist_dir = sanitize_filename(artist_to_tag)
            clean_song_filename = f"{sanitize_filename(artist_to_tag)} - {sanitize_filename(title_to_tag)}.mp3"
            
            if config.organize_by_artist:
                final_target_dir = target_base / clean_artist_dir
                final_target_dir.mkdir(parents=True, exist_ok=True)
                final_mp3_path = final_target_dir / clean_song_filename
                relative_target = f"{clean_artist_dir}/{clean_song_filename}"
            else:
                final_target_dir = target_base
                final_mp3_path = final_target_dir / clean_song_filename
                relative_target = clean_song_filename
            
            # Atomic replace/move
            shutil.move(str(temp_mp3_file), str(final_mp3_path))
            logger.info(f"[{job_id}] Saved final MP3: {final_mp3_path}")

            # Final success status
            if progress_callback:
                progress_callback({
                    "stage": "Completed",
                    "progress_percent": 100.0,
                    "speed_str": "Done",
                    "eta_str": "0s",
                    "thumbnail_url": thumb_url,
                    "detail": f"Saved to {final_mp3_path.name}"
                })

            file_size = final_mp3_path.stat().st_size if final_mp3_path.exists() else 0

            return {
                "success": True,
                "final_path": str(final_mp3_path),
                "relative_path": relative_target,
                "file_size": file_size,
                "file_size_formatted": f"{file_size / (1024*1024):.2f} MB",
                "resolved_info": resolved_info,
                "tagged_metadata": {
                    "artist": artist_to_tag,
                    "title": title_to_tag,
                    "album": album_to_tag
                }
            }

        except asyncio.CancelledError:
            logger.warning(f"[{job_id}] Job was cancelled.")
            if progress_callback:
                progress_callback({
                    "stage": "Failed",
                    "progress_percent": 0.0,
                    "error": "Cancelled by user"
                })
            raise

        except Exception as e:
            logger.error(f"[{job_id}] Pipeline error: {e}", exc_info=True)
            if progress_callback:
                progress_callback({
                    "stage": "Failed",
                    "progress_percent": 0.0,
                    "error": str(e)
                })
            return {
                "success": False,
                "error": str(e),
                "resolved_info": resolved_info
            }

        finally:
            # Auto-purge scratch folder on completion or failure
            if job_scratch_dir.exists():
                try:
                    shutil.rmtree(str(job_scratch_dir), ignore_errors=True)
                    logger.debug(f"Purged scratch dir: {job_scratch_dir}")
                except Exception as cleanup_err:
                    logger.warning(f"Failed to purge scratch directory {job_scratch_dir}: {cleanup_err}")
