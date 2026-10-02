import time
import uuid
import asyncio
import logging
from enum import Enum
from typing import Dict, List, Optional, Any, Set
from pydantic import BaseModel, Field

from .config import config
from .metadata import TrackMetadata, parse_track_input
from .downloader import MusicExtractionPipeline

logger = logging.getLogger("QueueManager")

class TaskStage(str, Enum):
    QUEUED = "Queued"
    RESOLVING = "Resolving Stream"
    DOWNLOADING = "Downloading"
    TRANSCODING = "Transcoding (FFmpeg)"
    TAGGING = "Tagging ID3"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

class JobItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    track: TrackMetadata
    stage: TaskStage = TaskStage.QUEUED
    progress_percent: float = 0.0
    speed_str: str = "0 KB/s"
    eta_str: str = "--"
    detail: str = "Waiting in queue..."
    error: Optional[str] = None
    final_path: Optional[str] = None
    relative_path: Optional[str] = None
    file_size_formatted: Optional[str] = None
    thumbnail_url: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None

class QueueManager:
    def __init__(self):
        self.jobs: Dict[str, JobItem] = {}
        self.order: List[str] = []
        self.queue: asyncio.Queue = asyncio.Queue()
        self.workers: List[asyncio.Task] = []
        self.listeners: Set[asyncio.Queue] = set()
        self.pipeline = MusicExtractionPipeline()
        self.cancel_tokens: Dict[str, asyncio.Event] = {}
        self.is_running = False

    async def start(self):
        """Start worker pool."""
        if self.is_running:
            return
        self.is_running = True
        logger.info(f"Starting QueueManager with {config.max_concurrent_workers} concurrent workers...")
        for i in range(config.max_concurrent_workers):
            task = asyncio.create_task(self._worker_loop(i))
            self.workers.append(task)

    async def stop(self):
        """Stop worker pool."""
        self.is_running = False
        for task in self.workers:
            task.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    def register_listener(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.listeners.add(q)
        return q

    def unregister_listener(self, q: asyncio.Queue):
        self.listeners.discard(q)

    async def broadcast_update(self, event_type: str, data: Any):
        """Broadcast real-time updates to connected WebSockets."""
        message = {"event": event_type, "data": data, "timestamp": time.time()}
        for q in list(self.listeners):
            try:
                q.put_nowait(message)
            except Exception:
                pass

    def add_tracks(self, tracks: List[TrackMetadata]) -> List[JobItem]:
        new_jobs = []
        for t in tracks:
            job = JobItem(track=t)
            self.jobs[job.id] = job
            self.order.append(job.id)
            self.cancel_tokens[job.id] = asyncio.Event()
            self.queue.put_nowait(job.id)
            new_jobs.append(job)
            logger.info(f"Enqueued job {job.id}: {t.artist} - {t.title}")

        asyncio.create_task(self.broadcast_update("queue_batch_added", [j.model_dump() for j in new_jobs]))
        return new_jobs

    def retry_track(self, job_id: str, custom_override: Optional[str] = None) -> Optional[JobItem]:
        job = self.jobs.get(job_id)
        if not job:
            return None

        if custom_override:
            job.track.custom_search_override = custom_override

        job.stage = TaskStage.QUEUED
        job.progress_percent = 0.0
        job.speed_str = "0 KB/s"
        job.eta_str = "--"
        job.detail = "Re-queued for processing..."
        job.error = None
        job.updated_at = time.time()
        job.completed_at = None

        self.cancel_tokens[job_id] = asyncio.Event()
        self.queue.put_nowait(job_id)

        asyncio.create_task(self.broadcast_update("job_updated", job.model_dump()))
        return job

    def cancel_track(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False

        token = self.cancel_tokens.get(job_id)
        if token:
            token.set()

        if job.stage in [TaskStage.QUEUED, TaskStage.RESOLVING, TaskStage.DOWNLOADING, TaskStage.TRANSCODING, TaskStage.TAGGING]:
            job.stage = TaskStage.CANCELLED
            job.detail = "Cancelled by user"
            job.updated_at = time.time()
            asyncio.create_task(self.broadcast_update("job_updated", job.model_dump()))
            return True
        return False

    def clear_queue(self, clear_all: bool = False):
        if clear_all:
            for job_id in list(self.jobs.keys()):
                self.cancel_track(job_id)
            self.jobs.clear()
            self.order.clear()
        else:
            # Clear finished / failed / cancelled
            finished_ids = [
                jid for jid, j in self.jobs.items() 
                if j.stage in [TaskStage.COMPLETED, TaskStage.FAILED, TaskStage.CANCELLED]
            ]
            for jid in finished_ids:
                del self.jobs[jid]
                if jid in self.order:
                    self.order.remove(jid)
                if jid in self.cancel_tokens:
                    del self.cancel_tokens[jid]

        asyncio.create_task(self.broadcast_update("queue_cleared", {"clear_all": clear_all}))

    def get_snapshot(self) -> List[Dict[str, Any]]:
        return [self.jobs[jid].model_dump() for jid in self.order if jid in self.jobs]

    async def _worker_loop(self, worker_id: int):
        logger.info(f"Worker {worker_id} ready.")
        while self.is_running:
            try:
                job_id = await self.queue.get()
            except asyncio.CancelledError:
                break

            job = self.jobs.get(job_id)
            if not job or job.stage == TaskStage.CANCELLED:
                self.queue.task_done()
                continue

            cancel_token = self.cancel_tokens.get(job_id)
            if cancel_token and cancel_token.is_set():
                self.queue.task_done()
                continue

            try:
                logger.info(f"[Worker {worker_id}] Starting job {job_id}: {job.track.artist} - {job.track.title}")
                
                # Progress dispatcher
                def _on_progress(p_data: Dict[str, Any]):
                    if not job:
                        return
                    stage_str = p_data.get("stage")
                    if stage_str:
                        try:
                            job.stage = TaskStage(stage_str)
                        except ValueError:
                            pass
                    if "progress_percent" in p_data:
                        job.progress_percent = p_data["progress_percent"]
                    if "speed_str" in p_data:
                        job.speed_str = p_data["speed_str"]
                    if "eta_str" in p_data:
                        job.eta_str = p_data["eta_str"]
                    if "detail" in p_data:
                        job.detail = p_data["detail"]
                    if "error" in p_data:
                        job.error = p_data["error"]
                    if "thumbnail_url" in p_data and p_data["thumbnail_url"]:
                        job.thumbnail_url = p_data["thumbnail_url"]

                    job.updated_at = time.time()
                    asyncio.create_task(self.broadcast_update("job_updated", job.model_dump()))

                # Execute pipeline
                result = await self.pipeline.execute(
                    job_id=job_id,
                    track=job.track,
                    progress_callback=_on_progress,
                    cancel_token=cancel_token
                )

                if result.get("success"):
                    job.stage = TaskStage.COMPLETED
                    job.progress_percent = 100.0
                    job.final_path = result.get("final_path")
                    job.relative_path = result.get("relative_path")
                    job.file_size_formatted = result.get("file_size_formatted")
                    job.thumbnail_url = result.get("resolved_info", {}).get("thumbnail") or job.thumbnail_url
                    tagged = result.get("tagged_metadata") or {}
                    if tagged.get("artist") and tagged.get("title"):
                        job.track.artist = tagged["artist"]
                        job.track.title = tagged["title"]
                        if tagged.get("album"):
                            job.track.album = tagged["album"]
                    job.detail = f"Saved: {job.relative_path}"
                    job.completed_at = time.time()
                else:
                    job.stage = TaskStage.FAILED
                    job.error = result.get("error", "Unknown error")
                    job.detail = f"Failed: {job.error}"

            except asyncio.CancelledError:
                job.stage = TaskStage.CANCELLED
                job.detail = "Job cancelled"
                logger.warning(f"[Worker {worker_id}] Job {job_id} cancelled")

            except Exception as e:
                logger.error(f"[Worker {worker_id}] Unexpected error on job {job_id}: {e}", exc_info=True)
                job.stage = TaskStage.FAILED
                job.error = str(e)
                job.detail = f"Error: {e}"

            finally:
                job.updated_at = time.time()
                await self.broadcast_update("job_updated", job.model_dump())
                self.queue.task_done()

# Global queue manager singleton
queue_manager = QueueManager()
