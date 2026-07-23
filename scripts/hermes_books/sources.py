from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .models import BookJob, sha256_file


@dataclass(frozen=True)
class RunPaths:
    raw_dir: Path
    draft_dir: Path
    normalized_dir: Path
    assets_cache_dir: Path
    evidence_cache_dir: Path
    reports_dir: Path


@dataclass(frozen=True)
class SourceSnapshot:
    raw_path: Path
    source_hash: str


def prepare_run_workspace(job: BookJob) -> RunPaths:
    raw_dir = job.run_dir / "raw"
    draft_dir = job.run_dir / "draft"
    normalized_dir = job.run_dir / "normalized"
    assets_cache_dir = job.run_dir / "assets-cache"
    evidence_cache_dir = job.run_dir / "evidence-cache"
    reports_dir = job.run_dir / "reports"
    for path in (
        raw_dir,
        draft_dir,
        normalized_dir,
        assets_cache_dir,
        evidence_cache_dir,
        reports_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        raw_dir,
        draft_dir,
        normalized_dir,
        assets_cache_dir,
        evidence_cache_dir,
        reports_dir,
    )


class LocalFileSource:
    def __init__(self, job: BookJob) -> None:
        self.job = job

    def snapshot(self) -> SourceSnapshot:
        if not self.job.input_path.is_file():
            raise FileNotFoundError(f"Input file not found: {self.job.input_path}")
        paths = prepare_run_workspace(self.job)
        raw_path = paths.raw_dir / self.job.input_path.name
        shutil.copy2(self.job.input_path, raw_path)
        return SourceSnapshot(raw_path=raw_path, source_hash=sha256_file(raw_path))
