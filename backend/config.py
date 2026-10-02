import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"
SCRATCH_DIR = BASE_DIR / ".tmp_work"

class AppConfig(BaseModel):
    output_dir: str = Field(default=str(DEFAULT_OUTPUT_DIR))
    scratch_dir: str = Field(default=str(SCRATCH_DIR))
    audio_format: str = Field(default="mp3")
    audio_codec: str = Field(default="libmp3lame")
    vbr_quality: int = Field(default=0, description="FFmpeg -q:a 0 (VBR V0 ~245kbps)")
    sample_rate: int = Field(default=44100, description="Resample to 44.1kHz")
    min_jitter_seconds: float = Field(default=2.0)
    max_jitter_seconds: float = Field(default=5.0)
    max_concurrent_workers: int = Field(default=2)
    embed_thumbnail: bool = Field(default=True)
    clean_filenames: bool = Field(default=True)
    organize_by_artist: bool = Field(default=True, description="Organize into Artist subfolders")

    def resolve_output_path(self) -> Path:
        p = Path(self.output_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolve_scratch_path(self) -> Path:
        p = Path(self.scratch_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

# Global singleton configuration instance
config = AppConfig()
