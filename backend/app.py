import os
import sys
import json
import shutil
import asyncio
import logging
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import config, AppConfig, BASE_DIR
from .system_check import run_system_diagnostics
from .metadata import parse_track_batch, parse_track_input, TrackMetadata
from .queue_manager import queue_manager, JobItem, TaskStage
from mutagen.mp3 import MP3
from mutagen.id3 import ID3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("App")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Studio Music Extraction Engine...")
    diag = run_system_diagnostics()
    if not diag["ready"]:
        logger.warning(f"SYSTEM DEPENDENCY WARNING: {diag.get('troubleshooting')}")
    else:
        logger.info("System dependencies verified: FFmpeg & FFprobe & libmp3lame OK.")

    # Clean any stale scratch folders
    scratch_dir = config.resolve_scratch_path()
    for item in scratch_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)

    await queue_manager.start()
    yield
    # Shutdown
    logger.info("Shutting down worker queues...")
    await queue_manager.stop()

app = FastAPI(
    title="Studio Audio Extractor & Transcoder",
    description="Automated production-grade music extraction and MP3 VBR V0 studio transcoder",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class IngestTextRequest(BaseModel):
    raw_text: str
    custom_override: Optional[str] = None

class RetryRequest(BaseModel):
    custom_override: Optional[str] = None

class UpdateConfigRequest(BaseModel):
    output_dir: Optional[str] = None
    min_jitter_seconds: Optional[float] = None
    max_jitter_seconds: Optional[float] = None
    max_concurrent_workers: Optional[int] = None
    organize_by_artist: Optional[bool] = None

@app.get("/api/system-status")
async def get_system_status():
    """Return diagnostic checks on FFmpeg, FFprobe, and encoders."""
    diag = run_system_diagnostics()
    return {
        "status": "ok" if diag["ready"] else "warning",
        "diagnostics": diag,
        "config": config.model_dump()
    }

@app.get("/api/queue")
async def get_queue():
    """Get active queue state snapshot."""
    return {
        "jobs": queue_manager.get_snapshot(),
        "count": len(queue_manager.jobs)
    }

@app.post("/api/queue/add")
async def add_to_queue(payload: IngestTextRequest):
    """Ingest multi-line raw track text or CSV."""
    if not payload.raw_text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
    
    tracks = parse_track_batch(payload.raw_text)
    if payload.custom_override and len(tracks) == 1:
        tracks[0].custom_search_override = payload.custom_override

    if not tracks:
        raise HTTPException(status_code=400, detail="No valid track titles parsed.")

    new_jobs = queue_manager.add_tracks(tracks)
    return {
        "message": f"Successfully queued {len(new_jobs)} tracks",
        "jobs": [j.model_dump() for j in new_jobs]
    }

@app.post("/api/queue/upload")
async def upload_file_to_queue(file: UploadFile = File(...)):
    """Ingest track list from .txt or .csv file."""
    filename = file.filename or ""
    if not (filename.endswith(".txt") or filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only .txt and .csv files are supported.")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="replace")

    tracks = parse_track_batch(text)
    if not tracks:
        raise HTTPException(status_code=400, detail="File contains no extractable track entries.")

    new_jobs = queue_manager.add_tracks(tracks)
    return {
        "message": f"Successfully queued {len(new_jobs)} tracks from {filename}",
        "jobs": [j.model_dump() for j in new_jobs]
    }

@app.post("/api/queue/{job_id}/retry")
async def retry_job(job_id: str, payload: Optional[RetryRequest] = None):
    """Retry a failed or completed job, with optional manual query override."""
    override = payload.custom_override if payload else None
    job = queue_manager.retry_track(job_id, custom_override=override)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID not found.")
    return {"message": "Job re-queued successfully", "job": job.model_dump()}

@app.post("/api/queue/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a queued or active job."""
    success = queue_manager.cancel_track(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job ID not found or already in terminal state.")
    return {"message": "Job cancelled successfully"}

@app.post("/api/queue/clear")
async def clear_queue(clear_all: bool = Query(default=False)):
    """Clear finished/failed or all jobs from the queue."""
    queue_manager.clear_queue(clear_all=clear_all)
    return {"message": "Queue cleared"}

@app.get("/api/config")
async def get_config():
    return config.model_dump()

@app.post("/api/config")
async def update_config(payload: UpdateConfigRequest):
    if payload.output_dir:
        config.output_dir = payload.output_dir
    if payload.min_jitter_seconds is not None:
        config.min_jitter_seconds = payload.min_jitter_seconds
    if payload.max_jitter_seconds is not None:
        config.max_jitter_seconds = payload.max_jitter_seconds
    if payload.max_concurrent_workers is not None:
        config.max_concurrent_workers = payload.max_concurrent_workers
    if payload.organize_by_artist is not None:
        config.organize_by_artist = payload.organize_by_artist

    return {"message": "Configuration updated", "config": config.model_dump()}

@app.get("/api/library")
async def get_library():
    """Scan the output library for completed MP3 files and return detailed metadata."""
    out_dir = config.resolve_output_path()
    items = []

    for path in out_dir.rglob("*.mp3"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            size_mb = stat.st_size / (1024 * 1024)
            rel_path = str(path.relative_to(out_dir))
            
            # Read ID3 tags
            artist = path.parent.name
            title = path.stem
            album = "Single"
            duration = 0.0

            try:
                audio = MP3(str(path))
                duration = audio.info.length if audio.info else 0.0
                if audio.tags:
                    if "TPE1" in audio.tags:
                        artist = str(audio.tags["TPE1"])
                    if "TIT2" in audio.tags:
                        title = str(audio.tags["TIT2"])
                    if "TALB" in audio.tags:
                        album = str(audio.tags["TALB"])
            except Exception:
                pass

            mins = int(duration // 60)
            secs = int(duration % 60)
            duration_str = f"{mins}:{secs:02d}" if duration > 0 else "--:--"

            import urllib.parse
            cover_url = f"/api/library/cover?path={urllib.parse.quote(rel_path)}"

            items.append({
                "filename": path.name,
                "relative_path": rel_path,
                "full_path": str(path),
                "artist": artist,
                "title": title,
                "album": album,
                "duration_seconds": round(duration, 1),
                "duration_formatted": duration_str,
                "size_mb": round(size_mb, 2),
                "modified_timestamp": stat.st_mtime,
                "cover_url": cover_url
            })
        except Exception as e:
            logger.warning(f"Error reading library file {path}: {e}")

    # Sort descending by last modified
    items.sort(key=lambda x: x["modified_timestamp"], reverse=True)
    return {
        "output_dir": str(out_dir),
        "total_tracks": len(items),
        "tracks": items
    }

@app.get("/api/library/cover")
async def get_cover_art(path: str = Query(..., description="Relative path in output directory")):
    """Extract embedded ID3 APIC cover art image from the MP3 file."""
    out_dir = config.resolve_output_path()
    file_path = (out_dir / path).resolve()

    if not str(file_path).startswith(str(out_dir)) or not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Track not found.")

    try:
        audio = MP3(str(file_path))
        if audio.tags:
            for key in audio.tags.keys():
                if key.startswith("APIC"):
                    apic = audio.tags[key]
                    from fastapi import Response
                    return Response(content=apic.data, media_type=apic.mime or "image/jpeg")
    except Exception as e:
        logger.debug(f"Could not extract APIC cover from {file_path}: {e}")

    raise HTTPException(status_code=404, detail="No embedded cover art found.")

@app.get("/api/library/stream")
async def stream_audio(path: str = Query(..., description="Relative path in output directory")):
    """Stream an MP3 file for the browser audio player with range request support."""
    out_dir = config.resolve_output_path()
    file_path = (out_dir / path).resolve()

    # Security check: ensure path is inside output dir
    if not str(file_path).startswith(str(out_dir)):
        raise HTTPException(status_code=403, detail="Access denied.")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found.")

    return FileResponse(
        str(file_path),
        media_type="audio/mpeg",
        filename=file_path.name,
        headers={"Accept-Ranges": "bytes"}
    )

@app.delete("/api/library")
async def delete_library_track(path: str = Query(..., description="Relative path in output directory")):
    """Delete a downloaded track from the library with folder cleanup."""
    out_dir = config.resolve_output_path()
    file_path = (out_dir / path).resolve()

    # Security check: ensure path is strictly inside output dir
    if not str(file_path).startswith(str(out_dir)):
        raise HTTPException(status_code=403, detail="Access denied.")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Track file not found.")

    try:
        parent_dir = file_path.parent
        file_path.unlink()
        logger.info(f"Deleted library file: {file_path}")

        # Clean up empty parent folder if it's inside out_dir and empty
        if parent_dir != out_dir and parent_dir.is_dir() and not any(parent_dir.iterdir()):
            try:
                parent_dir.rmdir()
                logger.info(f"Removed empty artist folder: {parent_dir}")
            except Exception:
                pass

        return {"success": True, "message": f"Deleted '{file_path.name}' successfully"}
    except Exception as e:
        logger.error(f"Failed to delete track {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete track: {str(e)}")

@app.post("/api/library/open")
async def open_output_folder():
    """Open the output folder in the OS native file manager."""
    out_dir = config.resolve_output_path()
    try:
        if sys.platform == "linux" or sys.platform == "linux2":
            subprocess.Popen(["xdg-open", str(out_dir)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(out_dir)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(out_dir)])
        return {"success": True, "message": f"Opened {out_dir}"}
    except Exception as e:
        logger.error(f"Failed to open output directory: {e}")
        return {"success": False, "error": str(e), "path": str(out_dir)}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time updates via WebSockets."""
    await websocket.accept()
    listener_queue = queue_manager.register_listener()
    
    try:
        # Initial snapshot
        initial_payload = {
            "event": "initial_state",
            "data": {
                "jobs": queue_manager.get_snapshot(),
                "diagnostics": run_system_diagnostics(),
                "config": config.model_dump()
            }
        }
        await websocket.send_text(json.dumps(initial_payload))

        while True:
            # Wait for updates or incoming client message
            try:
                update_msg = await asyncio.wait_for(listener_queue.get(), timeout=1.0)
                await websocket.send_text(json.dumps(update_msg))
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_text(json.dumps({"event": "heartbeat"}))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as e:
        logger.debug(f"WebSocket connection closed: {e}")
    finally:
        queue_manager.unregister_listener(listener_queue)

# Serve Frontend static directory
frontend_path = BASE_DIR / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
